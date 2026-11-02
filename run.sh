#!/usr/bin/env bash
#
# Launch Meeting Transcriber. Run ./setup.sh first.
#
#   ./run.sh
#
# Set MT_NO_BROWSER=1 to skip opening the browser (the .app launcher does its
# own opening, so it sets this to avoid a duplicate tab).
#
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  printf "\033[31m✗ No .venv found. Run ./setup.sh first.\033[0m\n"
  exit 1
fi

# shellcheck disable=SC1091
source .venv/bin/activate

PORT="${MS_PORT:-5001}"

# Open the browser once the server is actually accepting connections, so the
# first-run model download doesn't greet the user with "connection refused".
if [ -z "${MT_NO_BROWSER:-}" ]; then
  (
    until curl -s "http://127.0.0.1:${PORT}" >/dev/null 2>&1; do sleep 1; done
    open "http://127.0.0.1:${PORT}"
  ) >/dev/null 2>&1 &
fi

# caffeinate -i keeps the Mac awake during long transcriptions.
exec caffeinate -i python3 app.py
