# We assume this script is sourced: source shortcut.sh

# Determine the directory of this script (portable!)
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-${(%):-%x}}")" && pwd)"

# Detect current shell type (since we're sourced, $SHELL might not reflect it)
if [ -n "$ZSH_VERSION" ]; then
  shell_rc="${ZDOTDIR:-$HOME}/.zshrc"
elif [ -n "$BASH_VERSION" ]; then
  shell_rc="$HOME/.bashrc"
else
  shell_rc="$HOME/.profile"
fi

# Add alias if not already present
if ! grep -q "alias ?=" "$shell_rc" 2>/dev/null; then
  echo "alias '?'=\"$BASE_DIR/run.sh\"" >> "$shell_rc"
  echo "✅ Added alias to $shell_rc"
else
  echo "ℹ️ Alias already present in $shell_rc"
fi

# Apply it immediately in this session
alias '?'="$BASE_DIR/run.sh"
echo "✅ Alias '?' now active. You can run it right away!"

