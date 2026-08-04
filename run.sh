#!/usr/bin/env bash
# Start the Weybourne Investment Connector (macOS / Linux).
# React front-end + FastAPI backend at http://localhost:8000
#
#   ./run.sh                launch the app
#   ./run.sh --setup-only   prepare the environment but don't launch
#   ./run.sh --dev          also start the Vite dev server (hot reload, :5173)
#
# Safe to run repeatedly: the venv, dependencies and front-end build are only
# created/refreshed when missing or out of date.
set -euo pipefail
cd "$(dirname "$0")"

VENV=.venv
REQ_COPY="$VENV/.deps-requirements.txt"
SETUP_ONLY=0
DEV=0
# This machine only by default: the app has no login, so anything that can
# reach it can read your mail and notes. --lan opts into the network.
LAN=0
HOST=127.0.0.1
for arg in "$@"; do
  [ "$arg" = "--setup-only" ] && SETUP_ONLY=1
  [ "$arg" = "--dev" ] && DEV=1
  [ "$arg" = "--lan" ] && { LAN=1; HOST=0.0.0.0; }
done

# -- 1. Python environment --------------------------------------------------- #
if [ ! -x "$VENV/bin/python" ]; then
  PY=""
  for p in python3 python; do
    if command -v "$p" >/dev/null 2>&1 &&
       "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)'; then
      PY="$p"; break
    fi
  done
  [ -z "$PY" ] && { echo "Python 3.10+ not found — install it from python.org"; exit 1; }
  echo "Creating the virtual environment..."
  "$PY" -m venv "$VENV"
fi
PY="$VENV/bin/python"

# -- 2. Python dependencies -------------------------------------------------- #
NEED=0
"$PY" -c 'import fastapi, uvicorn' >/dev/null 2>&1 || NEED=1
{ [ -f "$REQ_COPY" ] && cmp -s requirements.txt "$REQ_COPY"; } || NEED=1
if [ "$NEED" = 1 ]; then
  echo "Installing dependencies..."
  "$PY" -m pip install --upgrade pip
  "$PY" -m pip install -r requirements.txt
  cp requirements.txt "$REQ_COPY"
fi

# -- 3. Front-end ------------------------------------------------------------ #
command -v npm >/dev/null 2>&1 || { echo "npm (Node.js LTS) not found — install from nodejs.org"; exit 1; }
if [ ! -d web/node_modules ]; then
  (cd web && npm install --no-audit --no-fund)
fi
if [ ! -f web/dist/index.html ]; then
  (cd web && npm run build)
fi

# -- 4. AI backend note ------------------------------------------------------ #
command -v claude >/dev/null 2>&1 || echo "Note: Claude Code not installed — AI features unavailable (sample data still works)."

[ "$SETUP_ONLY" = 1 ] && { echo "Environment ready."; exit 0; }
[ "$DEV" = 1 ] && (cd web && npm run dev &)

# -- 5. Launch --------------------------------------------------------------- #
echo "Starting the app at http://localhost:8000 (Ctrl+C to stop)"
if [ "$LAN" = 1 ]; then
  echo "NETWORK MODE: reachable by other devices on this Wi-Fi, and the app has"
  echo "no login. Only do this on a network you trust."
  echo "On your phone: http://<this-machine's-IP>:8000, then Add to Home Screen."
else
  echo "This machine only. For phone access on the same Wi-Fi: ./run.sh --lan"
fi
exec "$PY" -m uvicorn api.main:app --host "$HOST" --port 8000
