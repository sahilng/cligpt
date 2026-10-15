import asyncio
import os
import unittest
from unittest.mock import patch

from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import DummyInput, create_pipe_input
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.renderer import CPR_Support

from terminal_ui import HINT, TerminalUI, Transcript


class ResizableOutput(DummyOutput):
    size = Size(rows=24, columns=80)
    bell_count = 0

    def get_size(self):
        return self.size

    def get_rows_below_cursor_position(self):
        return self.size.rows

    def bell(self):
        self.bell_count += 1


class ReportingOutput(ResizableOutput):
    on_cursor_request = None

    @property
    def responds_to_cpr(self):
        return True

    def ask_for_cpr(self):
        if self.on_cursor_request:
            self.on_cursor_request()


class TranscriptTest(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_only_changed_entries_are_reformatted_until_resize(self):
        transcript = Transcript()
        transcript.append("user", "question\n")
        transcript.append("assistant", "```python\nanswer = 42\n```")
        with patch.object(transcript, "_render_entry", wraps=transcript._render_entry) as render:
            original = transcript.create_content(80, 20)
            self.assertEqual(render.call_count, 2)
            self.assertIs(transcript.create_content(80, 30), original)
            self.assertEqual(render.call_count, 2)

            transcript.append("user", "next\n")
            transcript.create_content(80, 20)
            self.assertEqual(render.call_count, 3)
            transcript.append("assistant", "partial")
            transcript.create_content(80, 20)
            self.assertEqual(render.call_count, 4)
            transcript.replace_last("completed reply")
            transcript.create_content(80, 20)
            self.assertEqual(render.call_count, 5)
            self.assertEqual(render.call_args.args[:2], ("assistant", "completed reply"))

            # Incremental rendering must match a fresh render, including spacing.
            fresh = Transcript()
            for role, text in transcript.entries:
                fresh.append(role, text)
            fresh.create_content(80, 20)
            self.assertEqual(transcript._lines, fresh._lines)

            transcript.create_content(40, 20)
            self.assertEqual(render.call_count, 9)
            fresh.create_content(40, 20)
            self.assertEqual(transcript._lines, fresh._lines)

    def test_code_background_is_rebuilt_at_each_width(self):
        transcript = Transcript()
        transcript.append("assistant", "Before\n\n```python\nprint('hello')\n```\n\nAfter")
        for width in (79, 29, 109, 9, 79):
            with self.subTest(width=width):
                content = transcript.create_content(width, 20)
                background_lines = [
                    content.get_line(index) for index in range(content.line_count)
                    if any("bg:" in style for style, _ in content.get_line(index))
                ]
                self.assertTrue(background_lines)
                for line in background_lines:
                    self.assertEqual(sum(len(text) for _, text in line), width)
                self.assertIn("After", "".join(
                    text for index in range(content.line_count)
                    for _, text in content.get_line(index)
                ))

    def test_plain_output_preserves_ansi_and_wraps_on_resize(self):
        transcript = Transcript(markdown=False)
        transcript.append("assistant", "\x1b[31m" + "hello " * 30 + "\x1b[0m")
        wide = transcript.create_content(80, 20)
        narrow = transcript.create_content(20, 20)
        self.assertGreater(narrow.line_count, wide.line_count)
        self.assertTrue(any("ansired" in style for style, _ in narrow.get_line(0)))

    def test_markdown_links_do_not_leak_terminal_control_sequences(self):
        transcript = Transcript()
        transcript.append("assistant", "[Example](https://example.com)")
        content = transcript.create_content(80, 20)
        text = "".join(
            text for index in range(content.line_count)
            for _, text in content.get_line(index)
        )
        self.assertIn("Example", text)
        visible_text = "".join(
            text for index in range(content.line_count)
            for style, text in content.get_line(index)
            if "[ZeroWidthEscape]" not in style
        )
        self.assertEqual(visible_text.strip(), "Example")
        self.assertIn("https://example.com", text)

    def test_original_header_and_blank_line_after_response(self):
        ui = TerminalUI("test", input=DummyInput(), output=ResizableOutput())
        self.assertFalse(ui.application.full_screen)
        ui.transcript.append("user", "hello\n")
        ui.append_response("A reply.")
        content = ui.transcript.create_content(100, 30)
        lines = ["".join(text for _, text in content.get_line(index))
                 for index in range(content.line_count)]
        self.assertEqual(lines[:3], ["Model: test", HINT, ""])
        self.assertEqual([line.rstrip() for line in lines[-2:]], ["A reply.", ""])

    def test_submitted_entry_stays_white_without_echoing_an_extra_newline(self):
        transcript = Transcript()
        transcript.append("user", "first\nsecond\n")
        content = transcript.create_content(80, 20)
        lines = ["".join(text for _, text in content.get_line(index))
                 for index in range(content.line_count)]
        self.assertEqual(lines, ["> first", "second", ""])
        self.assertEqual(content.get_line(0)[0], ("ansicyan", "> "))
        self.assertTrue(all(
            "ansiwhite" in style
            for index in range(content.line_count)
            for style, text in content.get_line(index)
            if text and text != "> "
        ))
        self.assertEqual(transcript.entries[-1][1], "first\nsecond\n")


class TerminalUITest(unittest.IsolatedAsyncioTestCase):
    async def test_submit_after_external_clear_keeps_only_new_visible_text(self):
        with create_pipe_input() as pipe:
            output = ReportingOutput()
            ui = TerminalUI("test", input=pipe, output=output)
            ui.append_response("old answer")
            entered = asyncio.Event()
            release = asyncio.Event()
            received = []

            async def respond(text):
                received.append(text)
                entered.set()
                await release.wait()
                ui.append_response("new answer")

            task = asyncio.create_task(ui.run(respond))
            try:
                await asyncio.sleep(0.05)
                ui.application.renderer.cpr_support = CPR_Support.SUPPORTED
                # Cmd-K moves the real cursor up without notifying the renderer.
                output.on_cursor_request = lambda: pipe.send_text("\x1b[1;1R")
                pipe.send_text("new message\r")
                await asyncio.sleep(0.03)
                pipe.send_text("\r")
                await asyncio.wait_for(entered.wait(), 2)
                self.assertEqual(received, ["new message\n"])
                self.assertEqual(ui.transcript.entries, [("user", "new message\n")])
                self.assertIsNone(ui._cursor_probe)
                self.assertTrue(ui._loading_painted.is_set())
                release.set()
                await asyncio.sleep(0.05)
                self.assertEqual(ui.transcript.entries[-1], ("assistant", "new answer"))

                # An ordinary later submission must retain the displayed history.
                def report_current_position():
                    row = ui._cursor_probe.expected_row
                    pipe.send_text(f"\x1b[{row};1R")

                output.on_cursor_request = report_current_position
                entered.clear()
                pipe.send_text("followup\r\r")
                await asyncio.wait_for(entered.wait(), 2)
                self.assertEqual(received, ["new message\n", "followup\n"])
                self.assertIn(("user", "new message\n"), ui.transcript.entries)
                pipe.send_text("\x03")
                await asyncio.wait_for(task, 2)
            finally:
                if not task.done():
                    ui.application.exit()
                    await task

    async def test_unanswered_cursor_probe_does_not_stall_submission(self):
        with create_pipe_input() as pipe:
            output = ReportingOutput()
            ui = TerminalUI("test", input=pipe, output=output)
            entered = asyncio.Event()

            async def respond(text):
                entered.set()
                ui.append_response("answer")

            task = asyncio.create_task(ui.run(respond))
            try:
                await asyncio.sleep(0.05)
                renderer = ui.application.renderer
                renderer.cpr_support = CPR_Support.SUPPORTED
                pipe.send_text("hello\r\r")
                await asyncio.wait_for(entered.wait(), 0.5)
                probe = ui._cursor_probe
                self.assertIsNotNone(probe)
                self.assertFalse(probe.blocking)
                before = renderer._min_available_height
                # A late reply belongs to our probe, not toolkit's layout CPR.
                pipe.send_text(f"\x1b[{probe.expected_row};1R")
                await asyncio.sleep(0.03)
                self.assertIsNone(ui._cursor_probe)
                self.assertEqual(renderer._min_available_height, before)
                self.assertIn(("user", "hello\n"), ui.transcript.entries)
                pipe.send_text("\x03")
                await asyncio.wait_for(task, 2)
            finally:
                if not task.done():
                    ui.application.exit()
                    await task

    async def test_spinner_is_painted_before_request_and_repeated_enter_is_ignored(self):
        with create_pipe_input() as pipe:
            output = ResizableOutput()
            ui = TerminalUI("test", input=pipe, output=output)
            events = []
            entered = asyncio.Event()
            release = asyncio.Event()
            received = []

            def after_render(app):
                if ui.loading:
                    events.append("paint")

            ui.application.after_render += after_render

            async def respond(text):
                self.assertEqual(events[-1], "paint")
                events.append("request")
                received.append(text)
                entered.set()
                await release.wait()
                ui.append_response("done")

            task = asyncio.create_task(ui.run(respond))
            try:
                await asyncio.sleep(0.05)
                pipe.send_text("hello\r\r")
                await asyncio.wait_for(entered.wait(), 2)
                self.assertEqual(events[:2], ["paint", "request"])
                pipe.send_text("\r\r\n\n")
                await asyncio.sleep(0.05)
                self.assertEqual(received, ["hello\n"])
                self.assertEqual(ui.buffer.text, "")
                self.assertEqual(output.bell_count, 0)
                release.set()
                await asyncio.sleep(0.05)
                self.assertFalse(ui.busy)
                self.assertEqual(ui.buffer.text, "")
                entered.clear()
                pipe.send_text("next\r\r")
                await asyncio.wait_for(entered.wait(), 2)
                self.assertEqual(received, ["hello\n", "next\n"])
                pipe.send_text("\x03")
                await asyncio.wait_for(task, 2)
            finally:
                if not task.done():
                    ui.application.exit()
                    await task

    async def test_entry_follows_short_conversation_when_window_grows(self):
        with create_pipe_input() as pipe:
            output = ResizableOutput()
            ui = TerminalUI("test", input=pipe, output=output)
            ui.append_response("A short reply.")
            task = asyncio.create_task(ui.run(lambda text: asyncio.sleep(0)))
            try:
                await asyncio.sleep(0.05)
                pipe.send_text("draft")
                await asyncio.sleep(0.05)
                def cursor():
                    return ui.application.renderer._last_screen.get_cursor_position(ui.input_window)

                original_row = cursor().y
                self.assertGreater(original_row, 0)
                self.assertLess(original_row, 10)
                for rows in (40, 15, 24):
                    output.size = Size(rows=rows, columns=80)
                    ui.application._on_resize()
                    await asyncio.sleep(0.02)
                    self.assertEqual(cursor().y, original_row)
                    self.assertEqual(ui.buffer.text, "draft")
                ui.append_response("Another reply.")
                await asyncio.sleep(0.05)
                self.assertGreater(cursor().y, original_row)
                pipe.send_text("\x03")
                await asyncio.wait_for(task, 2)
            finally:
                if not task.done():
                    ui.application.exit()
                    await task

    async def test_resize_keeps_draft_cursor_and_code_background_in_bounds(self):
        with create_pipe_input() as pipe:
            output = ResizableOutput()
            ui = TerminalUI("test", input=pipe, output=output)
            ui.append_response("```python\nprint('hello')\n```\n\n" + "long reply " * 80)
            task = asyncio.create_task(ui.run(lambda text: asyncio.sleep(0)))
            try:
                await asyncio.sleep(0.05)
                pipe.send_text("draft text that should survive a resize")
                await asyncio.sleep(0.05)
                draft = ui.buffer.document
                for rows, columns in ((12, 30), (40, 120), (6, 12), (24, 80)):
                    output.size = Size(rows=rows, columns=columns)
                    ui.application._on_resize()
                    await asyncio.sleep(0.02)
                    self.assertEqual(ui.buffer.document, draft)
                    info = ui.input_window.render_info
                    self.assertIsNotNone(info)
                    cursor = ui.application.renderer._last_screen.get_cursor_position(ui.input_window)
                    self.assertLess(cursor.y, rows)
                    self.assertLess(cursor.x, columns)
                    self.assertEqual(info.window_width, columns)
                    self.assertEqual(ui.transcript._cache_key[0], columns)
                pipe.send_text("\x03")
                await asyncio.wait_for(task, 2)
            finally:
                if not task.done():
                    ui.application.exit()
                    await task

    async def test_resize_during_request_and_submit_bindings(self):
        with create_pipe_input() as pipe:
            output = ResizableOutput()
            ui = TerminalUI("test", input=pipe, output=output)
            release = asyncio.Event()
            received = []
            frames = []
            ui.application.after_render += lambda app: frames.append(1)

            async def respond(text):
                received.append(text)
                await release.wait()
                ui.append_response("```python\nanswer = 42\n```")

            task = asyncio.create_task(ui.run(respond))
            try:
                await asyncio.sleep(0.05)
                pipe.send_text("hello")
                await asyncio.sleep(0.05)
                screen = ui.application.renderer._last_screen
                cursor = screen.get_cursor_position(ui.input_window)
                for x in range(cursor.x - len("hello"), cursor.x):
                    self.assertIn("ansiwhite", screen.data_buffer[cursor.y][x].style)
                pipe.send_text("\r")
                await asyncio.sleep(0.05)
                self.assertEqual(received, [])
                self.assertEqual(ui.buffer.text, "hello\n")
                pipe.send_text("\r")
                await asyncio.sleep(0.05)
                self.assertEqual(received, ["hello\n"])
                self.assertTrue(ui.busy)
                self.assertTrue(ui.loading)
                content = ui.transcript.create_content(80, 24)
                self.assertEqual("".join(
                    text for _, text in content.get_line(content.line_count - 2)
                ), "> hello")
                self.assertEqual("".join(
                    text for _, text in content.get_line(content.line_count - 1)
                ), "")
                with patch("terminal_ui.monotonic", side_effect=[0, 0.08]):
                    self.assertNotEqual(ui._spinner(), ui._spinner())
                output.size = Size(rows=10, columns=25)
                ui.application._on_resize()
                release.set()
                await asyncio.sleep(0.05)
                self.assertFalse(ui.busy)
                self.assertFalse(ui.loading)
                self.assertEqual(ui.transcript.entries[-1][0], "assistant")
                self.assertEqual(ui.transcript._cache_key[0], 25)
                frame_count = len(frames)
                await asyncio.sleep(0.18)
                self.assertEqual(len(frames), frame_count, "Idle UI should not keep redrawing")
                self.assertTrue(ui._spinner_task.done())
                pipe.send_text("\x04")
                await asyncio.wait_for(task, 2)
            finally:
                if not task.done():
                    ui.application.exit()
                    await task


if __name__ == "__main__":
    unittest.main()
