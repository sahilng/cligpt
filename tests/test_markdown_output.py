from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

from rich.console import Console
from rich.text import Text


class MarkdownOutputTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch('dotenv.dotenv_values', return_value={
            'OPENAI_API_KEY': 'test', 'MODEL': 'test',
        }), patch('openai.OpenAI'), patch('terminal_input.read_message', side_effect=KeyboardInterrupt), \
                redirect_stdout(StringIO()):
            cls.app = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'app.py'))

    def render(self, text, width):
        output = StringIO()
        render = self.app['print_assistant_output']
        with patch.dict(render.__globals__, {
            'console': Console(file=output, width=width, force_terminal=True,
                               color_system='standard'),
        }):
            render(text)
        return output.getvalue()

    def test_short_paragraph_preserves_text(self):
        for width in (80, 110, 163):
            with self.subTest(width=width):
                rendered = self.render('Hi! How can I help?', width)
                self.assertEqual(Text.from_ansi(rendered).plain.rstrip(), 'Hi! How can I help?')

    def test_wrapped_paragraph_keeps_all_text_and_markdown_styles(self):
        text = 'This is a **bold** word. ' * 12
        rendered = self.render(text, 40)
        plain = Text.from_ansi(rendered).plain
        self.assertEqual(plain.count('bold'), 12)
        self.assertTrue(all(len(line) <= 40 for line in plain.splitlines()))
        self.assertIn('\x1b[1m', rendered)
        self.assertNotIn('**', plain)

    def test_long_list_items_and_code_lines_are_not_truncated(self):
        for text in ('- ' + 'marker ' * 40, '```text\n' + 'marker ' * 40 + '\n```'):
            with self.subTest(text=text[:10]):
                plain = Text.from_ansi(self.render(text, 40)).plain
                self.assertEqual(''.join(plain.split()).count('marker'), 40)
