import os
from getpass import getpass

from openai import OpenAI, OpenAIError
from dotenv import dotenv_values
from yaspin import yaspin
from yaspin.spinners import Spinners
from terminal_input import read_message
from rich.console import Console
from rich.markdown import CodeBlock, Markdown
from rich.syntax import Syntax

CYAN = "\033[36m"
GRAY = "\033[90m"
RESET = "\033[0m"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, '.env')
env_values = dotenv_values(env_path)

OPENAI_API_KEY = env_values.get('OPENAI_API_KEY')
MODEL = env_values.get('MODEL')
STREAM = env_values.get('STREAM', '').lower().strip() == 'true'
WEBSEARCH = env_values.get('WEBSEARCH', '').lower().strip() == 'true'
MARKDOWN = env_values.get('MARKDOWN', 'true').lower().strip() == 'true'
REASONING_EFFORT = (env_values.get('REASONING_EFFORT') or '').lower().strip() or 'low'

TOOLS = [{"type": "web_search"}] if WEBSEARCH else []
REASONING_OPTIONS = {"reasoning": {"effort": REASONING_EFFORT}}

INSTRUCTIONS = (
    "You are an assistant in an interactive terminal CLI. "
    "Keep replies concise and readable at typical terminal widths. "
    "The terminal supports ANSI escape sequences for colors and text styles. "
    "When using ANSI styling, emit actual escape characters, not literal escaped "
    "strings such as \\x1b or \\033, and reset styling afterward. "
    "If the user asks to exit, advise them to use Ctrl-C. "
    + (
        "Markdown rendering is enabled via Rich: use Markdown for headings, lists, "
        "code blocks, and tables. Prefer Markdown for ordinary formatting; "
        "use ANSI colors when requested."
        if MARKDOWN else
        "Markdown rendering is disabled: output is printed directly to the terminal. "
        "Use plain text and optional ANSI styling instead of Markdown formatting."
    )
)

console = Console()


class ResponseError(Exception):
    """A response failed, ended early, or contained no text to display."""


def completed_text(response):
    if response.status != 'completed':
        error = getattr(response, 'error', None)
        incomplete = getattr(response, 'incomplete_details', None)
        detail = getattr(error, 'message', None) or getattr(incomplete, 'reason', None)
        raise ResponseError(f'Response {response.status}' + (f': {detail}' if detail else '.'))
    if not response.output_text:
        raise ResponseError('The response completed without a text reply.')
    return response.output_text


class CopyableCodeBlock(CodeBlock):
    """Keep code lines intact so terminal selections copy usable source."""

    def __rich_console__(self, console, options):
        code = Syntax(
            str(self.text), self.lexer_name, theme=self.theme,
            background_color='default',
        ).highlight(str(self.text))
        code.justify = 'default'
        code.no_wrap = True
        code.overflow = 'ignore'
        code.end = ''
        yield code


class TerminalMarkdown(Markdown):
    elements = {**Markdown.elements, 'fence': CopyableCodeBlock,
                'code_block': CopyableCodeBlock}


def print_assistant_output(text):
    if MARKDOWN:
        # Let the terminal soft-wrap long code lines without adding newlines.
        console.print(TerminalMarkdown(text), crop=False)
    else:
        print(f"{CYAN}{text}{RESET}")

def request_response(client, model, messages):
    spinner = yaspin(Spinners.dots, color='cyan', text='')
    spinner.start()
    spinning = True
    plain_started = False

    def stop_spinner():
        nonlocal spinning
        if spinning:
            spinner.stop()
            spinning = False

    try:
        response = client.responses.create(
            model=model, instructions=INSTRUCTIONS, input=messages,
            stream=STREAM, tools=TOOLS, **REASONING_OPTIONS,
        )
        if STREAM:
            final_response = None
            with response:
                for event in response:
                    if event.type == 'response.output_text.delta' and not MARKDOWN:
                        if not plain_started:
                            stop_spinner()
                            print(CYAN, end='')
                            plain_started = True
                        print(event.delta, end='', flush=True)
                    elif event.type == 'response.completed':
                        final_response = event.response
                    elif event.type in ('response.failed', 'response.incomplete'):
                        completed_text(event.response)
                    elif event.type == 'error':
                        raise ResponseError(event.message)
            if final_response is None:
                raise ResponseError('The response stream ended before completion.')
            final_output = completed_text(final_response)
        else:
            final_output = completed_text(response)
        stop_spinner()
        if not plain_started:
            print_assistant_output(final_output)
        return final_output
    finally:
        stop_spinner()
        if plain_started:
            print(RESET)


def main():
    try:
        api_key = OPENAI_API_KEY or getpass('OPENAI_API_KEY=')
        model = MODEL or input('MODEL=')
        with OpenAI(api_key=api_key) as client:
            print(f'{GRAY}Model: {model}{RESET}')
            print(f'{GRAY}Enter for newline; Enter twice to submit. Multiline paste supported. Ctrl-C to exit.{RESET}')
            messages = []
            while True:
                print()
                user_input = read_message()
                user_message = {'role': 'user', 'content': user_input}
                try:
                    final_output = request_response(client, model, messages + [user_message])
                except (OpenAIError, ResponseError) as error:
                    print(f'Request failed: {error}')
                    continue
                messages.extend([user_message, {'role': 'assistant', 'content': final_output}])
    except (KeyboardInterrupt, EOFError):
        print(f'{RESET}\n')


if __name__ == '__main__':
    main()
