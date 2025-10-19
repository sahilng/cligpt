# cligpt (aka ?)

A quick and easy way to use GPT in the CLI.

To use, execute `run.sh` (prerequisite: Python).

Create a `.env` based on `.env.example` to save API key, model, and streaming preference.

Add `alias "?"="[path/to]/cligpt/run.sh"` to `.zsrhc` or equivalent, replacing `[path/to]` with the path to the clone of this repository.

You can use this snippet to do so as well:
```sh
shell_rc="${ZDOTDIR:-$HOME}/.zshrc"
[ -n "$BASH_VERSION" ] && shell_rc="$HOME/.bashrc"
echo "alias '?'=\"\$PWD/run.sh\"" >> "$shell_rc" && echo "Added to $shell_rc"
```

Then, use `?` in your terminal to launch cligpt from anywhere.
