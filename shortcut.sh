#!/bin/bash
set -e  # exit on any error

# Determine the directory of this script (portable!)
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"

shell_rc="${ZDOTDIR:-$HOME}/.zshrc"
[ -n "$BASH_VERSION" ] && shell_rc="$HOME/.bashrc"
echo "alias '?'=\"$BASE_DIR/run.sh\"" >> "$shell_rc" && echo "Added to $shell_rc"
