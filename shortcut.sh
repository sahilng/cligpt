#!/bin/bash
set -e  # exit on any error

# Determine the directory of this script (portable!)
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"

# Detect user's login shell
case "$SHELL" in
  */zsh)
    shell_rc="${ZDOTDIR:-$HOME}/.zshrc"
    ;;
  */bash)
    shell_rc="$HOME/.bashrc"
    ;;
  *)
    shell_rc="$HOME/.profile"
    ;;
esac

echo "alias '?'=\"$BASE_DIR/run.sh\"" >> "$shell_rc"
echo "Added to $shell_rc"
