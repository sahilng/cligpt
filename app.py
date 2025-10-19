import os
from openai import OpenAI
from dotenv import dotenv_values
from yaspin import yaspin
from yaspin.spinners import Spinners

CYAN = "\033[36m"
RESET = "\033[0m"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, '.env')
env_values = dotenv_values(env_path)

OPENAI_API_KEY = env_values.get('OPENAI_API_KEY') or input('OPENAI_API_KEY=')
MODEL = env_values.get('MODEL') or input('MODEL=')
STREAM = env_values.get('STREAM', '').lower().strip() == 'true'
WEBSEARCH = env_values.get('WEBSEARCH', '').lower().strip() == 'true'

TOOLS = [{"type": "web_search"}] if WEBSEARCH else []

client = OpenAI(api_key=OPENAI_API_KEY)
messages = []

try:
    while True:
        messages.append({
            "role": "user",
            "content": input('\n> '),
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
                        if not first_token:
                            sp.stop()
                            print("\r", end="")
                            print(CYAN, end="")  # Start cyan text
                            first_token = True
                        print(event.delta, end='', flush=True)

                    if event.type == "response.output_text.done":
                        final_output = event.text

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
            print(f"{CYAN}{final_output}{RESET}")

        messages.append({
            "role": "assistant",
            "content": final_output,
        })

except KeyboardInterrupt:
    print("\n")
