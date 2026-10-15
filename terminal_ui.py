"""A single renderer owns the transcript, input, and terminal resize handling."""

import asyncio
from dataclasses import dataclass
from io import StringIO
import re
from time import monotonic

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.data_structures import Point, Size
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI, to_formatted_text
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import ConditionalContainer, HSplit, Layout, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl, UIContent, UIControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.renderer import CPR_Support, HeightIsUnknownError
from yaspin.spinners import Spinners
from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text

from input_bindings import create_key_bindings

HINT = "Enter twice to submit. Ctrl-C to exit."
HYPERLINK = re.compile(r"\x1b\]8;[^\x07\x1b]*(?:\x07|\x1b\\)")


@dataclass
class CursorProbe:
    expected_row: int
    size: Size
    cleared_entries: int
    blocking: bool = True


class TerminalApplication(Application):
    """Don't draw using stale coordinates while checking an external clear."""

    defer_redraw = None

    def _redraw(self, *args, **kwargs):
        if not self.is_done and self.defer_redraw and self.defer_redraw():
            return
        super()._redraw(*args, **kwargs)


class Transcript(UIControl):
    def __init__(self, markdown=True):
        self.markdown = markdown
        self.entries = []
        self.revision = 0
        self._cache_key = None
        self._lines = [[]]
        self._entry_lines = []
        self._dirty_from = 0
        self._content = None

    def append(self, role, text):
        self.entries.append((role, text))
        self.revision += 1

    def replace_last(self, text):
        role, _ = self.entries[-1]
        self.entries[-1] = (role, text)
        self.revision += 1
        self._dirty_from = min(self._dirty_from, len(self.entries) - 1)

    def discard_before(self, index):
        # The API conversation lives separately; this only clears displayed text.
        del self.entries[:index]
        self.revision += 1
        self._dirty_from = 0

    def preferred_height(self, width, max_available_height, wrap_lines, get_line_prefix):
        content = self.create_content(width, max_available_height)
        return min(content.line_count, max_available_height)

    def create_content(self, width, height):
        key = (max(1, width), self.revision)
        if key != self._cache_key:
            # Only resizing requires reformatting completed messages. Appending
            # or streaming a reply leaves the earlier rendered entries intact.
            if self._cache_key is None or key[0] != self._cache_key[0]:
                self._dirty_from = 0
            del self._entry_lines[self._dirty_from:]
            for role, text in self.entries[self._dirty_from:]:
                self._entry_lines.append(self._render_entry(role, text, key[0]))
            self._dirty_from = len(self.entries)
            self._lines = [line for entry in self._entry_lines for line in entry] or [[]]
            self._cache_key = key
            # Reuse UIContent too, so prompt_toolkit can cache line heights and
            # screen fragments between keystrokes and spinner frames.
            lines = self._lines
            self._content = UIContent(
                get_line=lines.__getitem__, line_count=len(lines),
                cursor_position=Point(x=0, y=len(lines) - 1), show_cursor=False,
            )
        return self._content

    def _render_entry(self, role, text, width):
        output = StringIO()
        console = Console(
            file=output, width=width, force_terminal=True,
            color_system="truecolor", highlight=False,
        )
        if role == "assistant" and self.markdown:
            console.print(Markdown(text))
        elif role == "user":
            # Enter already supplies the line ending. Keep the separator below
            # without echoing another Enter.
            console.print(Text("> ", style="cyan") + Text(text, style="bright_white"),
                          end="" if text.endswith("\n") else "\n")
        else:
            style = "cyan" if role == "assistant" else "bright_black"
            console.print(Text.from_ansi(text, style=style))
        if role != "header":
            console.print()
        rendered = output.getvalue().removesuffix("\n")
        rendered = HYPERLINK.sub(lambda match: "\001" + match[0] + "\002", rendered)
        lines = [[]]
        for style, text, *_ in to_formatted_text(ANSI(rendered)):
            for index, part in enumerate(text.split("\n")):
                if index:
                    lines.append([])
                if not part:
                    continue
                # ANSI yields individual characters. Keep style runs together
                # to reduce allocations and work in the terminal renderer.
                if lines[-1] and lines[-1][-1][0] == style:
                    lines[-1][-1] = (style, lines[-1][-1][1] + part)
                else:
                    lines[-1].append((style, part))
        return lines

class TerminalUI:
    def __init__(self, model, markdown=True, *, input=None, output=None):
        self.transcript = Transcript(markdown)
        self.transcript.append("header", f"Model: {model}")
        self.transcript.append("status", HINT)
        self.busy = False
        self.loading = False
        self._spinner_task = None
        self._loading_painted = asyncio.Event()
        self._cursor_probe = None
        self.on_submit = None
        self.buffer = Buffer(
            multiline=True, accept_handler=self._submit,
            read_only=Condition(lambda: self.busy),
        )
        self.input_control = BufferControl(buffer=self.buffer)
        self.input_window = Window(
            self.input_control, height=Dimension(min=1),
            wrap_lines=True, dont_extend_height=True, style="ansiwhite",
            get_line_prefix=lambda line, wrap: [("ansicyan", "> " if line == 0 and wrap == 0 else "")],
        )
        bindings = KeyBindings()

        @bindings.add(Keys.CPRResponse, save_before=lambda event: False)
        def cursor_position(event):
            row, _ = map(int, event.data[2:-1].split(";"))
            self._report_cursor_position(row)

        @bindings.add("enter", filter=Condition(lambda: self.busy), eager=True)
        @bindings.add("c-j", filter=Condition(lambda: self.busy), eager=True)
        def ignore_enter_while_busy(event):
            # A held submission key must not edit the read-only buffer or ring
            # the terminal bell while the spinner is replacing the prompt.
            pass

        @bindings.add("c-c")
        def exit_app(event):
            event.app.exit()

        @bindings.add("c-d")
        def exit_empty(event):
            if not self.buffer.text and not self.busy:
                event.app.exit()

        self.application = TerminalApplication(
            layout=Layout(HSplit([
                Window(self.transcript, dont_extend_height=True),
                ConditionalContainer(
                    Window(FormattedTextControl(self._spinner), height=1),
                    filter=Condition(lambda: self.loading),
                ),
                ConditionalContainer(self.input_window, filter=Condition(lambda: not self.busy)),
            ]), focused_element=self.input_control),
            key_bindings=merge_key_bindings([create_key_bindings(), bindings]),
            full_screen=False, input=input, output=output,
            after_render=self._after_render,
        )
        self.application.defer_redraw = lambda: (
            self._cursor_probe is not None and self._cursor_probe.blocking
        )

    def _check_cursor_position(self):
        renderer = self.application.renderer
        if (self._cursor_probe is not None or renderer.waiting_for_cpr
                or renderer.cpr_support != CPR_Support.SUPPORTED):
            return
        try:
            expected_row = renderer.rows_above_layout + renderer._cursor_pos.y + 1
        except HeightIsUnknownError:
            return
        probe = CursorProbe(expected_row, renderer.output.get_size(), len(self.transcript.entries))
        self._cursor_probe = probe
        renderer.output.ask_for_cpr()
        renderer.output.flush()
        self.application.create_background_task(self._cursor_probe_timeout(probe))

    async def _cursor_probe_timeout(self, probe):
        # Never leave submission waiting on a terminal that stops answering.
        await asyncio.sleep(0.05)
        if self._cursor_probe is probe:
            probe.blocking = False
            self.application.invalidate()

    def _report_cursor_position(self, row):
        renderer = self.application.renderer
        probe = self._cursor_probe
        if probe is None:
            renderer.report_absolute_cursor_row(row)
            return
        self._cursor_probe = None
        if row < probe.expected_row and renderer.output.get_size() == probe.size:
            # Cmd-K can move the cursor to the top without sending a key to the
            # process. Forget only text printed before that clear, retaining the
            # new submission, draft, and API conversation.
            self.transcript.discard_before(probe.cleared_entries)
            renderer.output.reset_attributes()
            renderer.output.cursor_goto(0, 0)
            renderer.output.erase_down()
            renderer.output.flush()
            renderer.reset()
            renderer.report_absolute_cursor_row(1)
        self.application.invalidate()

    def _after_render(self, app):
        if self.loading:
            self._loading_painted.set()

    def _spinner(self):
        spinner = Spinners.dots
        frame = int(monotonic() * 1000 / spinner.interval) % len(spinner.frames)
        return [("ansicyan", spinner.frames[frame])]

    async def _animate_spinner(self):
        while self.loading:
            await asyncio.sleep(Spinners.dots.interval / 1000)
            if self.loading:
                self.application.invalidate()

    def _submit(self, buffer):
        if self.busy:
            return True
        self._check_cursor_position()
        text = buffer.text
        self.transcript.append("user", text)
        self.busy = True
        self.loading = True
        self._loading_painted.clear()
        if self._spinner_task is None or self._spinner_task.done():
            self._spinner_task = self.application.create_background_task(self._animate_spinner())
        self.application.create_background_task(self._respond(text))
        self.application.invalidate()
        return False

    async def _respond(self, text):
        try:
            # Request setup can do synchronous work before its first await.
            # Flush the submission feedback to the terminal before starting it.
            await self._loading_painted.wait()
            await self.on_submit(text)
        except Exception as error:
            self.transcript.append("status", f"Request failed: {error}")
        finally:
            self.busy = False
            self.loading = False
            self.application.invalidate()

    def append_response(self, text):
        self.loading = False
        self.transcript.append("assistant", text)
        self.application.invalidate()

    def update_response(self, text):
        self.transcript.replace_last(text)
        self.application.invalidate()

    async def run(self, on_submit):
        self.on_submit = on_submit
        await self.application.run_async()
