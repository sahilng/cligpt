# cligpt (aka ?)

*A quick and easy way to use GPT in the CLI.*

## Usage

To add the `?` shortcut, do `source shortcut.sh`.

Then, use `?` in your terminal to launch cligpt from anywhere.

Create a `.env` based on `.env.example` to save API key, model, streaming, and web-search preferences.

Set `MARKDOWN=false` to disable terminal markdown rendering. When `STREAM=true` and markdown rendering is enabled, responses render after completion so lists, code blocks, and tables format correctly.

### Key bindings

| Key | Action |
|-----|--------|
| `Enter` | New line |
| `Alt+Enter` | Submit |
| `Ctrl-C` | Exit |

> **Note:** `Cmd+Enter` and `Shift+Enter` are not supported — terminals don't forward these key combinations to applications.

![screenshpt](screenshot.png)
