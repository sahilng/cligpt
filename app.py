import os
from openai import OpenAI
from dotenv import dotenv_values

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

env_path = os.path.join(BASE_DIR, '.env')

env_values = dotenv_values(env_path)

OPENAI_API_KEY = env_values.get('OPENAI_API_KEY') or input('OPENAI_API_KEY=')

client = OpenAI(api_key=OPENAI_API_KEY)

MODEL = env_values.get('MODEL') or input('MODEL=')

stream_bool = env_values.get('STREAM', '').lower().strip() == 'true'

messages = []

try:
	while True:
		messages.append(
			{
				"role": "user",
				"content": input('\n> '),
			},
		)

		response = client.responses.create(
			model=MODEL,
			instructions="You are an assistant that is called from the CLI. Keep that in mind when responding, for the sake of brevity, format, etc. If the user asks to exit, advise them to use Ctrl-C.",
			input=messages,
			stream=stream_bool,
		)

		if stream_bool:
			print()
			final_output = ''
			for event in response:
				if event.type == "response.output_text.delta":
					print(event.delta, end='')
				if event.type == "response.output_text.done":
					final_output = event.text
			print()

		else:
			print()
			final_output = response.output_text
			print(final_output)
		
		messages.append(
			{
				"role": "assistant",
				"content": final_output,
			},
		)

except KeyboardInterrupt:
    print()
