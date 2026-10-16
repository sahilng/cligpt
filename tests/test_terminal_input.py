import os
import unittest
from unittest.mock import Mock

from terminal_input import read_message, readline


class NativeInputTest(unittest.TestCase):
    def read(self, lines):
        return read_message(read_line=Mock(side_effect=lines))

    def test_two_enters_submit_and_keep_first_newline(self):
        self.assertEqual(self.read(['hello', '']), 'hello\n')

    def test_multiple_lines(self):
        self.assertEqual(self.read(['one', 'two', '']), 'one\ntwo\n')

    def test_empty_message(self):
        self.assertEqual(self.read(['', '']), '\n')

    def test_backslash_allows_a_blank_line(self):
        self.assertEqual(self.read(['one\\', '', 'three', '']), 'one\n\nthree\n')

    def test_multiline_paste_including_empty_lines_is_one_input(self):
        self.assertEqual(self.read(['one\n\nthree\n', '']), 'one\n\nthree\n\n')

    def test_only_first_line_has_a_prompt(self):
        read_line = Mock(side_effect=['one', 'two', ''])
        read_message(read_line=read_line)
        self.assertTrue(read_line.call_args_list[0].args[0])
        self.assertEqual([call.args[0] for call in read_line.call_args_list[1:]], ['', ''])

    def test_ctrl_c_and_eof_propagate_to_application(self):
        for error in (KeyboardInterrupt, EOFError):
            with self.subTest(error=error):
                with self.assertRaises(error):
                    read_message(read_line=Mock(side_effect=error))


@unittest.skipUnless(os.name == 'posix' and readline is not None
                     and 'GNU readline' in (readline.__doc__ or ''),
                     'PTY bracketed-paste tests require POSIX and GNU readline')
class NativePtyTest(unittest.TestCase):
    def run_input(self, pasted, expected):
        import fcntl
        import json
        import os
        from pathlib import Path
        import pty
        import select
        import struct
        import subprocess
        import sys
        import termios
        from time import monotonic

        master, slave = pty.openpty()

        def own_terminal():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        script = (
            'import json; from terminal_input import read_message; '
            'print("Earlier conversation", flush=True); '
            'answer=read_message(); print("RESULT:"+json.dumps(answer), flush=True)'
        )
        process = subprocess.Popen(
            [sys.executable, '-c', script], stdin=slave, stdout=slave, stderr=slave,
            cwd=Path(__file__).resolve().parents[1], preexec_fn=own_terminal,
            env={**os.environ, 'TERM': 'xterm-256color'},
        )
        os.close(slave)
        output = bytearray()

        def until(marker):
            deadline = monotonic() + 3
            while marker not in output and monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 0.05)
                if ready:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output.extend(chunk)
            self.assertIn(marker, output, repr(output))

        try:
            until(b'>')
            self.assertIn(b'\x1b[?2004h', output)
            os.write(master, pasted)
            until(b'hello')
            # TIOCSWINSZ sends real SIGWINCH events to the native line editor.
            for rows, columns in ((65, 163), (12, 30), (40, 100), (24, 80)):
                fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', rows, columns, 0, 0))
            os.write(master, b'\r\r')
            until(b'RESULT:')
            process.wait(timeout=3)
            until(('RESULT:' + json.dumps(expected)).encode())
            self.assertEqual(process.returncode, 0)
            self.assertEqual(output.count(b'Earlier conversation'), 1)
            self.assertNotIn(b'\x1b[?1049h', output)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=3)
            os.close(master)

    def test_native_editor_preserves_draft_through_real_resize_signals(self):
        self.run_input(b'hello', 'hello\n')

    def test_native_bracketed_paste_keeps_blank_lines_during_resize(self):
        self.run_input(b'\x1b[200~hello\n\nthere\n\x1b[201~', 'hello\n\nthere\n\n')
