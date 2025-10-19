#!/bin/bash
set -e  # exit on any error

# Determine the directory of this script (portable!)
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
echo $BASE_DIR
VENV_DIR="$BASE_DIR/venv"
SCRIPT="$BASE_DIR/?.py"
REQS="$BASE_DIR/requirements.txt"

# Create virtual environment if missing
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi

# Activate it
source "$VENV_DIR/bin/activate"

# Install dependencies (quietly if possible)
if [ -f "$REQS" ]; then
  pip install -r "$REQS" -qqq
fi

# Run the script
python "$SCRIPT"