from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys


def create_key_bindings():
    bindings = KeyBindings()
    newline_pending = False

    @bindings.add('enter')
    @bindings.add('c-j')
    def enter(event):
        nonlocal newline_pending
        buffer = event.current_buffer
        previous = event.previous_key_sequence
        consecutive_enter = (
            len(previous) == 1
            and previous[0].key in (Keys.ControlM, Keys.ControlJ)
        )
        if buffer.document.current_line_before_cursor.endswith('\\'):
            buffer.delete_before_cursor(count=1)
            buffer.insert_text('\n')
            newline_pending = False
        elif newline_pending and consecutive_enter:
            newline_pending = False
            buffer.validate_and_handle()
        else:
            buffer.insert_text('\n')
            newline_pending = True

    # Terminals can encode Return as either CR or LF, prefixed by Escape
    # when Alt/Option is configured to send Meta. These submit immediately.
    @bindings.add('escape', 'enter', eager=True)
    @bindings.add('escape', 'c-j', eager=True)
    def submit(event):
        nonlocal newline_pending
        newline_pending = False
        event.current_buffer.validate_and_handle()

    return bindings
