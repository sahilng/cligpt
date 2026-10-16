from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from openai import APIConnectionError


def response(text='answer', status='completed'):
    return SimpleNamespace(output_text=text, status=status, error=None,
                           incomplete_details=SimpleNamespace(reason='max_output_tokens'))


class Stream:
    def __init__(self, events, error=None):
        self.events = events
        self.error = error
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def __iter__(self):
        yield from self.events
        if self.error is not None:
            raise self.error


def stream(text='answer', status='completed'):
    return Stream([
        SimpleNamespace(type='response.output_text.delta', delta=text),
        SimpleNamespace(type='response.output_text.done', text=text),
        SimpleNamespace(type='response.' + status, response=response(text, status)),
    ])


class Client:
    def __init__(self, results):
        self.calls = []
        self.results = iter(results)
        self.responses = SimpleNamespace(create=self.create)
        self.close = Mock()

    def create(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        result = next(self.results)
        if isinstance(result, BaseException):
            raise result
        return result

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class AppTest(unittest.TestCase):
    def run_app(self, results, *, streaming=True, markdown=True, websearch=True,
                inputs=None, config=None, key_error=None):
        values = {'OPENAI_API_KEY': 'test', 'MODEL': 'test',
                  'STREAM': str(streaming), 'MARKDOWN': str(markdown),
                  'WEBSEARCH': str(websearch), 'REASONING_EFFORT': 'high'}
        values.update(config or {})
        with patch('dotenv.dotenv_values', return_value=values):
            app = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'app.py'))
        state = app['main'].__globals__
        client = Client(results)
        factory = Mock(return_value=client)
        spinners = []

        def spinner(*args, **kwargs):
            item = Mock()
            spinners.append(item)
            return item

        getpass = Mock(return_value='fake-key', side_effect=key_error)
        ordinary_input = Mock(side_effect=AssertionError('Unexpected ordinary input() call'))
        output = StringIO()
        with patch.dict(state, {
            'OpenAI': factory, 'yaspin': spinner, 'getpass': getpass,
            'input': ordinary_input,
            'read_message': Mock(side_effect=inputs or ['first\n', 'second\n', KeyboardInterrupt]),
        }), redirect_stdout(output):
            app['main']()
        return SimpleNamespace(client=client, factory=factory, spinners=spinners,
                               output=output.getvalue(), getpass=getpass,
                               ordinary_input=ordinary_input)

    def assert_clean(self, run):
        run.client.close.assert_called_once_with()
        for spinner in run.spinners:
            spinner.start.assert_called_once_with()
            spinner.stop.assert_called_once_with()

    def test_requests_and_conversation_in_all_output_modes(self):
        for streaming in (False, True):
            for markdown in (False, True):
                for websearch in (False, True):
                    with self.subTest(streaming=streaming, markdown=markdown, websearch=websearch):
                        replies = [stream(), stream('followup')] if streaming else [response(), response('followup')]
                        run = self.run_app(replies, streaming=streaming, markdown=markdown, websearch=websearch)
                        first, second = run.client.calls
                        self.assertEqual(first['input'], [{'role': 'user', 'content': 'first\n'}])
                        self.assertEqual(second['input'], [
                            {'role': 'user', 'content': 'first\n'},
                            {'role': 'assistant', 'content': 'answer'},
                            {'role': 'user', 'content': 'second\n'},
                        ])
                        self.assertEqual(first['stream'], streaming)
                        self.assertEqual(first['reasoning'], {'effort': 'high'})
                        self.assertEqual(first['tools'], [{'type': 'web_search'}] if websearch else [])
                        self.assertIn('Markdown rendering is ' + ('enabled' if markdown else 'disabled'), first['instructions'])
                        self.assertIn('answer', run.output)
                        self.assert_clean(run)

    def test_completed_response_retains_all_streamed_text_parts(self):
        for markdown in (False, True):
            with self.subTest(markdown=markdown):
                parts = Stream([
                    SimpleNamespace(type='response.output_text.delta', delta='First part. '),
                    SimpleNamespace(type='response.output_text.done', text='First part. '),
                    SimpleNamespace(type='response.output_text.delta', delta='Second part.'),
                    SimpleNamespace(type='response.output_text.done', text='Second part.'),
                    SimpleNamespace(type='response.completed', response=response('First part. Second part.')),
                ])
                run = self.run_app([parts, stream('next')], markdown=markdown)
                self.assertEqual(run.client.calls[1]['input'][1]['content'], 'First part. Second part.')
                self.assertEqual(run.output.count('First part.'), 1)
                self.assertEqual(run.output.count('Second part.'), 1)
                self.assertTrue(parts.closed)
                self.assert_clean(run)

    def test_failed_or_incomplete_reply_is_reported_and_excluded_from_history(self):
        for streaming in (False, True):
            for status in ('failed', 'incomplete'):
                with self.subTest(streaming=streaming, status=status):
                    results = ([stream('earlier'), stream('partial', status), stream('next')]
                               if streaming else [response('earlier'), response('partial', status), response('next')])
                    run = self.run_app(results, streaming=streaming,
                                       inputs=['first\n', 'failed question\n', 'third\n', KeyboardInterrupt])
                    self.assertIn('Request failed:', run.output)
                    self.assertNotIn('partial', run.output)
                    self.assertEqual(run.client.calls[2]['input'], [
                        {'role': 'user', 'content': 'first\n'},
                        {'role': 'assistant', 'content': 'earlier'},
                        {'role': 'user', 'content': 'third\n'},
                    ])
                    if streaming:
                        self.assertTrue(all(item.closed for item in results))
                    self.assert_clean(run)

    def test_network_error_returns_to_prompt_without_failed_turn_in_history(self):
        error = APIConnectionError(request=SimpleNamespace(method='POST', url='https://example.invalid'))
        run = self.run_app([error, stream('recovered')])
        self.assertIn('Request failed:', run.output)
        self.assertIn('recovered', run.output)
        self.assertEqual(run.client.calls[1]['input'], [{'role': 'user', 'content': 'second\n'}])
        self.assert_clean(run)

    def test_truncated_stream_without_completion_is_not_saved(self):
        truncated = Stream([SimpleNamespace(type='response.output_text.done', text='partial')])
        run = self.run_app([truncated, stream('recovered')])
        self.assertIn('stream ended before completion', run.output)
        self.assertEqual(run.client.calls[1]['input'], [{'role': 'user', 'content': 'second\n'}])
        self.assertTrue(truncated.closed)
        self.assert_clean(run)

    def test_stream_error_event_is_reported_and_stream_is_closed(self):
        failed = Stream([SimpleNamespace(type='error', message='simulated server error')])
        run = self.run_app([failed, stream('recovered')])
        self.assertIn('Request failed: simulated server error', run.output)
        self.assertTrue(failed.closed)
        self.assertEqual(run.client.calls[1]['input'], [{'role': 'user', 'content': 'second\n'}])
        self.assert_clean(run)

    def test_plain_stream_network_failure_resets_color_before_error(self):
        failed = Stream([SimpleNamespace(type='response.output_text.delta', delta='partial')],
                        error=APIConnectionError(request=SimpleNamespace(method='POST', url='https://example.invalid')))
        run = self.run_app([failed, stream('recovered')], markdown=False)
        self.assertIn('partial\033[0m\nRequest failed:', run.output)
        self.assertTrue(failed.closed)
        self.assertEqual(run.client.calls[1]['input'], [{'role': 'user', 'content': 'second\n'}])
        self.assert_clean(run)

    def test_interrupted_plain_stream_closes_resources_and_resets_color(self):
        partial = Stream([SimpleNamespace(type='response.output_text.delta', delta='partial')],
                         error=KeyboardInterrupt())
        run = self.run_app([partial], markdown=False)
        self.assertIn('partial\033[0m', run.output)
        self.assertTrue(partial.closed)
        self.assertEqual(len(run.client.calls), 1)
        self.assert_clean(run)

    def test_missing_api_key_uses_hidden_prompt_instead_of_readline(self):
        run = self.run_app([], config={'OPENAI_API_KEY': None}, inputs=[KeyboardInterrupt])
        run.getpass.assert_called_once_with('OPENAI_API_KEY=')
        run.ordinary_input.assert_not_called()
        run.factory.assert_called_once_with(api_key='fake-key')
        self.assertNotIn('fake-key', run.output)
        self.assert_clean(run)

    def test_interrupt_during_credential_prompt_exits_cleanly(self):
        run = self.run_app([], config={'OPENAI_API_KEY': None}, key_error=KeyboardInterrupt())
        run.factory.assert_not_called()

    def test_response_without_text_is_reported(self):
        run = self.run_app([response(''), response('recovered')], streaming=False)
        self.assertIn('completed without a text reply', run.output)
        self.assertEqual(run.client.calls[1]['input'], [{'role': 'user', 'content': 'second\n'}])
        self.assert_clean(run)
