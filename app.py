import asyncio
import os

from openai import AsyncOpenAI
from dotenv import dotenv_values

from terminal_ui import TerminalUI

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, '.env')
env_values = dotenv_values(env_path)

OPENAI_API_KEY = env_values.get('OPENAI_API_KEY') or input('OPENAI_API_KEY=')
MODEL = env_values.get('MODEL') or input('MODEL=')
STREAM = env_values.get('STREAM', '').lower().strip() == 'true'
WEBSEARCH = env_values.get('WEBSEARCH', '').lower().strip() == 'true'
MARKDOWN = env_values.get('MARKDOWN', 'true').lower().strip() == 'true'

REASONING_EFFORT = (env_values.get('REASONING_EFFORT') or '').lower().strip() or 'medium'

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

async def main():
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    ui = TerminalUI(MODEL, markdown=MARKDOWN)
    messages = []

    async def respond(user_input):
        request_messages = messages + [{"role": "user", "content": user_input}]

        async def request():
            response = await client.responses.create(
                model=MODEL,
                instructions=INSTRUCTIONS,
                input=request_messages,
                stream=STREAM,
                tools=TOOLS,
                **REASONING_OPTIONS,
            )
            if not STREAM:
                return response.output_text, False

            chunks = []
            final_parts = []
            started = False
            # Close the stream on completion or failure.
            async with response:
                async for event in response:
                    if event.type == "response.output_text.delta":
                        chunks.append(event.delta)
                        if not MARKDOWN:
                            if not started:
                                ui.append_response("")
                                started = True
                            ui.update_response("".join(chunks))
                    elif event.type == "response.output_text.done":
                        final_parts.append(event.text)
                    elif event.type in ("response.failed", "response.incomplete", "error"):
                        raise RuntimeError("The response did not complete. Please try again.")
            return "\n".join(final_parts) if final_parts else "".join(chunks), started

        final_output, streamed = await request()
        if streamed:
            ui.update_response(final_output)
        else:
            ui.append_response(final_output)
        messages.extend([
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": final_output},
        ])

    try:
        await ui.run(respond)
    finally:
        await client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, EOFError):
        pass
