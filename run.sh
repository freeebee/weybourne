#!/usr/bin/env bash
#
# Start the Weybourne Investment Connector.
#
#   ./run.sh                          launch the app
#   ./run.sh --server.port 8600       pass any extra flags through to Streamlit
#   ./run.sh --setup-only             prepare the environment but don't launch
#
# Safe to run as often as you like: the virtual environment and dependencies are
# only created/installed when they're missing or out of date.
set -euo pipefail

cd "$(dirname "$0")"

VENV=".venv"
STAMP="$VENV/.deps-installed"
MIN_PYTHON="3.10"

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*"; }
die()  { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

SETUP_ONLY=0
STREAMLIT_ARGS=()
for arg in "$@"; do
    if [ "$arg" = "--setup-only" ]; then
        SETUP_ONLY=1
    else
        STREAMLIT_ARGS+=("$arg")
    fi
done

# --------------------------------------------------------------------------- #
# 1. Find a suitable Python
# --------------------------------------------------------------------------- #
find_python() {
    for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 &&
           "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

if [ ! -x "$VENV/bin/python" ]; then
    PYTHON="$(find_python)" || die \
"Could not find Python $MIN_PYTHON or newer.

  macOS:    brew install python
  Windows:  https://python.org  (tick 'Add Python to PATH' during install)
  Linux:    sudo apt install python3 python3-venv

Then run ./run.sh again."

    say "Creating the virtual environment (one-off, ~10 seconds)..."
    "$PYTHON" -m venv "$VENV" || die \
"Failed to create the virtual environment.
On Debian/Ubuntu this usually means python3-venv is missing:
  sudo apt install python3-venv"
fi

PY="$VENV/bin/python"

# --------------------------------------------------------------------------- #
# 2. Install dependencies, but only when they've changed
# --------------------------------------------------------------------------- #
requirements_hash() {
    if command -v shasum >/dev/null 2>&1; then
        shasum requirements.txt | cut -d' ' -f1
    else
        sha1sum requirements.txt | cut -d' ' -f1
    fi
}

WANT="$(requirements_hash)"
HAVE="$(cat "$STAMP" 2>/dev/null || true)"

# Reinstall when requirements change, and also whenever Streamlit isn't actually
# importable - a stamp file can outlive a half-built environment.
if [ "$WANT" != "$HAVE" ] || ! "$PY" -c "import streamlit" >/dev/null 2>&1; then
    say "Installing dependencies (one-off, a minute or two)..."
    "$PY" -m pip install --quiet --upgrade pip
    "$PY" -m pip install --quiet -r requirements.txt || die \
"Dependency installation failed. Scroll up for the reason - a re-run often fixes
a transient network error."
    echo "$WANT" > "$STAMP"
fi

"$PY" -c "import streamlit" >/dev/null 2>&1 || die \
"Streamlit did not install correctly. Delete the .venv folder and run ./run.sh again."

# --------------------------------------------------------------------------- #
# 3. Check the AI backend (a warning, never a blocker)
# --------------------------------------------------------------------------- #
if [ "${LLM_BACKEND:-claude_cli}" = "claude_cli" ]; then
    if ! command -v claude >/dev/null 2>&1; then
        warn "Note: Claude Code isn't installed, so AI features (triage, screening,
      drafting) will be unavailable. Everything else still works on sample data.
      Install it from https://claude.com/claude-code, or set LLM_BACKEND=api
      with an ANTHROPIC_API_KEY to use an Anthropic API account instead."
    fi
fi

if [ "$SETUP_ONLY" = "1" ]; then
    say "Environment ready. Run ./run.sh to start the app."
    exit 0
fi

# --------------------------------------------------------------------------- #
# 4. Launch
# --------------------------------------------------------------------------- #
say "Starting the app - your browser will open automatically."
echo "   (press Ctrl+C here to stop it)"
echo
# "python -m streamlit" rather than the streamlit shim: works even when the
# script shim is missing or the PATH is unusual.
exec "$PY" -m streamlit run dashboard/Home.py ${STREAMLIT_ARGS+"${STREAMLIT_ARGS[@]}"}
