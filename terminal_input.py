"""Read messages with Python's native line editor and ordinary terminal output."""

import sys

try:
    import readline  # Installs native editing/history for input().
except ImportError:
    readline = None

if readline is not None and 'GNU readline' in (readline.__doc__ or ''):
    # Keep pasted empty lines inside one input() call instead of submitting.
    readline.parse_and_bind('set enable-bracketed-paste on')


def read_message(*, read_line=None):
    read_line = input if read_line is None else read_line
    # Readline's markers keep ANSI color codes out of its prompt-width count.
    prompt = ('\001\033[36m\002>\001\033[0m\002 '
              if readline is not None and sys.stdin.isatty() and sys.stdout.isatty()
              else '> ')
    lines = []
    escaped = False
    while True:
        line = read_line(prompt if not lines else '')
        if not line and lines and not escaped:
            return ''.join(lines)
        escaped = line.endswith('\\')
        lines.append((line[:-1] if escaped else line) + '\n')
