#!/usr/bin/env bash
# Pionex Lab one-line installer for macOS and Linux (paper trading only; no API keys, no real orders).
#
#   curl -fsSL https://raw.githubusercontent.com/rgriesel/pionex/main/tools/install/unix.sh | bash
#
# Clones (or updates) the repo into ~/pionex, runs init/verify/capability, starts the supervised
# runtime (collector + paper engine + dashboard + automatic daily research) in the background, and
# adds an @reboot crontab entry so it starts again after a restart. Re-running it is safe.
set -euo pipefail

REPO_URL="${PIONEX_LAB_REPO:-https://github.com/rgriesel/pionex.git}"
DIR="${PIONEX_LAB_DIR:-$HOME/pionex}"
step() { printf '\n==> %s\n' "$1"; }

echo "Pionex Lab installer - paper trading only. No API keys are needed or used."

step "Checking Python 3.11+ and Git"
PY=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$(command -v "$candidate")"; break
  fi
done
if [ -z "$PY" ]; then
  if command -v brew >/dev/null 2>&1; then brew install python@3.12; PY="$(brew --prefix)/bin/python3.12"
  elif command -v apt-get >/dev/null 2>&1 && [ "$(id -u)" = 0 ]; then apt-get update && apt-get install -y python3; PY="$(command -v python3)"
  else echo "Python 3.11+ is required. Install it, then run this installer again." >&2; exit 1; fi
fi
command -v git >/dev/null 2>&1 || { echo "Git is required. Install it, then run this installer again." >&2; exit 1; }
echo "Using $PY"

step "Getting the code into $DIR"
if [ -d "$DIR/.git" ]; then git -C "$DIR" pull --ff-only; else git clone "$REPO_URL" "$DIR"; fi
cd "$DIR"

if command -v npm >/dev/null 2>&1; then
  step "Installing the pinned official Pionex CLI (dry-run previews only)"
  npm ci --prefix tools/pionex-cli --ignore-scripts --no-audit --no-fund || echo "npm install failed; the built-in dry-run renderer will be used."
fi

step "Initialising and verifying"
"$PY" -m pionex_lab init
"$PY" -m pionex_lab verify

step "Checking that this computer can reach the Pionex public API"
"$PY" -m pionex_lab capability || echo "Some Pionex endpoints did not respond. The runtime keeps retrying and freezes entries until data is fresh."

step "Starting the runtime in the background"
mkdir -p var/logs
if pgrep -f "pionex_lab run" >/dev/null 2>&1; then pkill -f "pionex_lab run" || true; sleep 2; fi
nohup "$PY" -m pionex_lab run >var/logs/run-console.log 2>&1 &
if command -v crontab >/dev/null 2>&1; then
  ENTRY="@reboot cd $DIR && $PY -m pionex_lab run >>$DIR/var/logs/run-console.log 2>&1"
  { crontab -l 2>/dev/null | grep -v "pionex_lab run" || true; echo "$ENTRY"; } | crontab -
  echo "Added an @reboot crontab entry."
fi

URL="http://127.0.0.1:8765/#token=$(cat var/dashboard.token)"
echo
echo "Done. Pionex Lab is running in the background."
echo "Dashboard (open on this computer only): $URL"
echo "Logs: $DIR/var/logs    Stop: pkill -f 'pionex_lab run'"
echo "Paper trading only: no exchange account is connected and no real orders are sent."
