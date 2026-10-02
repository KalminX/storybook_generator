#!/bin/bash
# Double-click this file to launch Storybook Studio in your browser.

cd "$(dirname "$0")" || exit 1

pause() {
  echo
  read -r -p "Press Enter to close this window..." _
}

# 1. Verify / Setup venv
if [ ! -x .venv/bin/python ]; then
  PYTHON=""
  for candidate in python3.13 python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
      PYTHON="$candidate"
      break
    fi
  done
  if [ -z "$PYTHON" ]; then
    echo "Python 3.11 or newer is needed."
    pause
    exit 1
  fi
  echo "Setting up Storybook Studio (takes a minute)..."
  "$PYTHON" -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
fi

# 2. Check API key
if [ ! -f .env ]; then
  cp .env.example .env
fi
if ! grep -Eq '^GEMINI_API_KEY=[^[:space:]]+' .env; then
  echo "Your Gemini API key is missing from .env."
  open -e .env
  pause
  exit 1
fi

# 3. Launch Web App
.venv/bin/python run_web.py
pause
