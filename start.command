#!/bin/bash
# Double-click this file to make storybooks.
# First run: installs everything it needs into a private ".venv" folder.
# After that: checks your API key and runs the generator.

cd "$(dirname "$0")" || exit 1

pause() {
  echo
  read -r -p "Press Enter to close this window..." _
}

# --- 1. Install (first run, or after requirements.txt changes) ---------------
if [ ! -x .venv/bin/python ] || [ requirements.txt -nt .venv/.installed ]; then
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
    echo "Download it from https://www.python.org/downloads/ , install it, then double-click start.command again."
    pause
    exit 1
  fi

  echo "Setting up (only needed once, takes a minute or two)..."
  if ! { [ -x .venv/bin/python ] || "$PYTHON" -m venv .venv; } ||
     ! .venv/bin/python -m pip install --quiet --upgrade pip ||
     ! .venv/bin/python -m pip install --quiet -r requirements.txt; then
    echo
    echo "Setup failed - see the messages above. Check your internet connection and try again."
    rm -rf .venv
    pause
    exit 1
  fi
  touch .venv/.installed
  echo "Setup complete."
  echo
fi

# --- 2. API key ---------------------------------------------------------------
if [ ! -f .env ]; then
  cp .env.example .env
fi
if ! grep -Eq '^GEMINI_API_KEY=[^[:space:]]+' .env; then
  echo "Almost ready! Your Gemini API key is missing."
  echo
  echo "A file called .env has opened in TextEdit."
  echo "Paste your key right after GEMINI_API_KEY= (no spaces), save it,"
  echo "then double-click start.command again."
  open -e .env
  pause
  exit 1
fi

# --- 3. Run -------------------------------------------------------------------
.venv/bin/python run.py "$@"
status=$?
echo
if [ $status -eq 0 ]; then
  echo "All done. Your books are in the \"output\" folder."
else
  echo "Finished with problems (see above). Double-click start.command again to retry;"
  echo "finished work is kept."
fi
pause
exit $status
