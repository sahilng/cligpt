import os
from openai import OpenAI
from dotenv import dotenv_values
from yaspin import yaspin
from yaspin.spinners import Spinners
from prompt_toolkit import PromptSession
from input_bindings import create_key_bindings
from rich.console import Console
from rich.markdown import Markdown

CYAN = "\033[36m"
GRAY = "\033[90m"
RESET = "\033[0m"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, '.env')
env_values = dotenv_values(env_path)

OPENAI_API_KEY = env_values.get('OPENAI_API_KEY') or input('OPENAI_API_KEY=')
MODEL = env_values.get('MODEL') or input('MODEL=')
STREAM = env_values.get('STREAM', '').lower().strip() == 'true'
WEBSEARCH = env_values.get('WEBSEARCH', '').lower().strip() == 'true'
MARKDOWN = env_values.get('MARKDOWN', 'true').lower().strip() == 'true'

TOOLS = [{"type": "web_search"}] if WEBSEARCH else []

client = OpenAI(api_key=OPENAI_API_KEY)
console = Console()
messages = []

def print_assistant_output(text):
    if MARKDOWN:
        console.print(Markdown(text))
    else:
        print(f"{CYAN}{text}{RESET}")

prompt_session = PromptSession(key_bindings=create_key_bindings(), multiline=True)

print(f"{GRAY}Model: {MODEL}{RESET}")
print(f"{GRAY}Enter for newline; Enter twice to submit. Multiline paste supported. Ctrl-C to exit.{RESET}")

try:
    while True:
        user_input = prompt_session.prompt('\n> ')
        messages.append({
            "role": "user",
            "content": user_input,
        })
        print()

        if STREAM:
            with yaspin(Spinners.dots, color="cyan", text="") as sp:
                response = client.responses.create(
                    model=MODEL,
                    instructions="You are an assistant that is called from the CLI. Keep that in mind when responding, for the sake of brevity, format, etc. If the user asks to exit, advise them to use Ctrl-C.",
                    input=messages,
                    stream=True,
                    tools=TOOLS
                )

                first_token = False
                final_output = ''

                for event in response:
                    if event.type == "response.output_text.delta":
                        if MARKDOWN:
                            continue

                        if not first_token:
                            sp.stop()
                            print("\r", end="")
                            print(CYAN, end="")  # Start cyan text
                            first_token = True
                        print(event.delta, end='', flush=True)

                    if event.type == "response.output_text.done":
                        final_output = event.text

                if MARKDOWN:
                    sp.stop()
                    print("\r", end="")
                    print_assistant_output(final_output)
                else:
                    print(RESET)  # Reset color

        else:
            with yaspin(Spinners.dots, color="cyan", text="") as sp:
                response = client.responses.create(
                    model=MODEL,
                    instructions="You are an assistant that is called from the CLI. Keep that in mind when responding, for the sake of brevity, format, etc. If the user asks to exit, advise them to use Ctrl-C.",
                    input=messages,
                    stream=False,
                    tools=TOOLS
                )
                sp.stop()
                print("\r", end="")

            final_output = response.output_text
            print_assistant_output(final_output)

        messages.append({
            "role": "assistant",
            "content": final_output,
        })

except (KeyboardInterrupt, EOFError):
    print("\n")
