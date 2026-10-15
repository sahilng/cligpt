import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

with patch("dotenv.dotenv_values", return_value={"OPENAI_API_KEY": "test", "MODEL": "test"}):
    import app


class ResponseStream:
    def __init__(self):
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def __aiter__(self):
        yield SimpleNamespace(type="response.output_text.delta", delta="hello ")
        yield SimpleNamespace(type="response.output_text.delta", delta="world")
        yield SimpleNamespace(type="response.output_text.done", text="hello world")


class FakeUI:
    def __init__(self, *args, **kwargs):
        self.responses = []
        self.updates = []

    def append_response(self, text):
        self.responses.append(text)

    def update_response(self, text):
        self.responses[-1] = text
        self.updates.append(text)

    async def run(self, respond):
        await respond("first")
        await respond("second")


class AppTest(unittest.IsolatedAsyncioTestCase):
    async def test_requests_and_history_in_all_render_modes(self):
        for streaming in (False, True):
            for markdown in (False, True):
                with self.subTest(streaming=streaming, markdown=markdown):
                    streams = [ResponseStream(), ResponseStream()]
                    create = AsyncMock(side_effect=streams if streaming else [
                        SimpleNamespace(output_text="hello world"),
                        SimpleNamespace(output_text="hello world"),
                    ])
                    client = SimpleNamespace(
                        responses=SimpleNamespace(create=create), close=AsyncMock(),
                    )
                    ui = FakeUI()
                    with patch.object(app, "STREAM", streaming), patch.object(app, "MARKDOWN", markdown), \
                            patch.object(app, "AsyncOpenAI", return_value=client), \
                            patch.object(app, "TerminalUI", return_value=ui):
                        await app.main()
                    self.assertEqual(ui.responses, ["hello world", "hello world"])
                    self.assertEqual(bool(ui.updates), streaming and not markdown)
                    self.assertEqual(create.call_args.kwargs["reasoning"], {"effort": "medium"})
                    self.assertEqual(create.call_args.kwargs["input"], [
                        {"role": "user", "content": "first"},
                        {"role": "assistant", "content": "hello world"},
                        {"role": "user", "content": "second"},
                    ])
                    if streaming:
                        self.assertTrue(all(stream.closed for stream in streams))
                    client.close.assert_awaited_once()
