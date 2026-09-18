import asyncio
import unittest

from prompt_toolkit import PromptSession
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from input_bindings import create_key_bindings


class InputBindingsTest(unittest.IsolatedAsyncioTestCase):
    async def prompt_with(self, chunks):
        with create_pipe_input() as pipe:
            session = PromptSession(
                input=pipe,
                output=DummyOutput(),
                key_bindings=create_key_bindings(),
                multiline=True,
            )

            async def run_prompt():
                # Catch inside the task so asyncio doesn't stop the test loop.
                try:
                    return await session.prompt_async()
                except (KeyboardInterrupt, EOFError) as error:
                    return error

            task = asyncio.create_task(run_prompt())
            try:
                for index, chunk in enumerate(chunks):
                    pipe.send_text(chunk)
                    await asyncio.sleep(0.05)
                    if index < len(chunks) - 1:
                        self.assertFalse(task.done(), 'Input submitted before the final key')
                return await asyncio.wait_for(task, timeout=2)
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    async def test_submit_encodings(self):
        for submit in ('\r', '\n'):
            with self.subTest(submit=repr(submit)):
                self.assertEqual(
                    await self.prompt_with(['hello' + submit, submit]), 'hello\n'
                )

    async def test_typing_between_enters_does_not_submit(self):
        self.assertEqual(
            await self.prompt_with(['one\r', 'two\r', '\r']), 'one\ntwo\n'
        )

    async def test_cursor_movement_breaks_consecutive_enters(self):
        self.assertEqual(
            await self.prompt_with(['one\r', '\x1b[D\x1b[C\r', '\r']),
            'one\n\n',
        )

    async def test_paste_between_enters_does_not_submit(self):
        self.assertEqual(
            await self.prompt_with(['one\r', '\x1b[200~two\n\x1b[201~\r', '\r']),
            'one\ntwo\n\n',
        )

    async def test_split_escape_sequence(self):
        self.assertEqual(await self.prompt_with(['hello\x1b', '\r']), 'hello')

    async def test_backslash_enter_inserts_newlines(self):
        self.assertEqual(
            await self.prompt_with(['one\\\r', '\r', 'three\r', '\r']),
            'one\n\nthree\n',
        )

    async def test_bracketed_paste_preserves_newlines(self):
        self.assertEqual(
            await self.prompt_with(['\x1b[200~one\ntwo\n\x1b[201~', '\r', '\r']),
            'one\ntwo\n\n',
        )

    async def test_split_bracketed_paste_with_crlf(self):
        self.assertEqual(
            await self.prompt_with(['\x1b[200~one\r', '\ntwo\r\n\x1b[201~', '\r', '\r']),
            'one\ntwo\n\n',
        )

    async def test_literal_trailing_backslash(self):
        self.assertEqual(await self.prompt_with(['hello\\\x1b\r']), 'hello\\')

    async def test_ctrl_d_does_not_submit_text(self):
        self.assertEqual(await self.prompt_with(['hello\x04', '\r', '\r']), 'hello\n')

    async def test_ctrl_d_exits_empty_prompt(self):
        self.assertIsInstance(await self.prompt_with(['\x04']), EOFError)

    async def test_ctrl_c_exits(self):
        self.assertIsInstance(await self.prompt_with(['\x03']), KeyboardInterrupt)


if __name__ == '__main__':
    unittest.main()
