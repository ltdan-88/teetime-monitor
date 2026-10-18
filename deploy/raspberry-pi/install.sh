#!/usr/bin/env bash
# Teetime Monitor as a web server on a Raspberry Pi (or any Debian-like Linux), 2026-10-11.
#
#   curl -fsSL https://raw.githubusercontent.com/ltdan-88/teetime-monitor/main/deploy/raspberry-pi/install.sh | bash
#
# What it does: puts the program in its own Python environment under ~/.local/share/teetime-monitor-server,
# asks you for a password (the web UI is protected by it), and -- when systemd is there -- installs a
# service that starts at boot and restarts after a crash. Run it again any time to update.
#
# Options (as `bash install.sh --port 9000`, or after `| bash -s --`):
#   --port N        listen on this port (default 8765)
#   --version vX.Y.Z  install this release instead of the newest
#   --no-service    do not touch systemd; start it yourself with  ~/.local/share/teetime-monitor-server/venv/bin/teetime-monitor-web --serve
#   --no-password   do not ask for a password (you set it later with  teetime-monitor-web --set-password)
# Environment: TEETIME_SOURCE=<path or URL pip can install> installs that instead of a release (for testing).
set -euo pipefail

REPO="ltdan-88/teetime-monitor"
PORT=8765
VERSION=""
SERVICE=1
PASSWORD=1
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    --no-service) SERVICE=0; shift ;;
    --no-password) PASSWORD=0; shift ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\n%s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -ne 0 ] || die "Run this as your normal user (not root, not with sudo): the program keeps its settings in your home folder. It asks for sudo itself where it needs it."

PYTHON="${PYTHON:-python3}"
command -v "$PYTHON" >/dev/null || die "Python 3 is missing. Install it with:  sudo apt install python3 python3-venv"
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
  || die "Teetime Monitor needs Python 3.11 or newer; this is $("$PYTHON" -V). Raspberry Pi OS 'Bookworm' (12) or newer has it."

APP="$HOME/.local/share/teetime-monitor-server"
mkdir -p "$APP"
if [ ! -x "$APP/venv/bin/python" ]; then
  say "Creating the Python environment"
  "$PYTHON" -m venv "$APP/venv" || die "Could not create a virtual environment. Install the missing package with:  sudo apt install python3-venv"
fi

if [ -n "${TEETIME_SOURCE:-}" ]; then
  SOURCE="$TEETIME_SOURCE"
else
  if [ -z "$VERSION" ]; then
    say "Looking up the newest release"
    VERSION="$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" | "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])')" \
      || die "Could not reach GitHub. Is the Pi online?"
  fi
  SOURCE="https://github.com/$REPO/archive/refs/tags/$VERSION.tar.gz"
fi
say "Installing ${VERSION:-from $SOURCE} (a few minutes on a Pi: some packages are built from source if no ready-made one exists)"
"$APP/venv/bin/python" -m pip install --quiet --upgrade pip
"$APP/venv/bin/python" -m pip install --quiet --upgrade "$SOURCE"
WEB="$APP/venv/bin/teetime-monitor-web"
"$WEB" --version

if [ "$PASSWORD" -eq 1 ]; then
  if "$APP/venv/bin/python" -c 'from src.webui import auth; raise SystemExit(0 if auth.is_configured() else 1)'; then
    echo "A password is already set (change it any time with:  $WEB --set-password)."
  else
    say "Choose the password for the web page (everyone on your network will need it)"
    "$WEB" --set-password </dev/tty || die "No password was set. Run:  $WEB --set-password"
  fi
fi

if [ "$SERVICE" -eq 1 ]; then
  if command -v systemctl >/dev/null && [ -d /run/systemd/system ]; then
    say "Installing the service (asks for your sudo password)"
    UNIT=/etc/systemd/system/teetime-monitor.service
    sudo tee "$UNIT" >/dev/null <<UNIT_EOF
[Unit]
Description=Teetime Monitor web server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(id -un)
ExecStart=$WEB --serve --port $PORT
Restart=on-failure
RestartSec=10
# Nothing here needs more than its own settings and data folders.
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
UNIT_EOF
    sudo systemctl daemon-reload
    sudo systemctl enable teetime-monitor.service >/dev/null
    sudo systemctl restart teetime-monitor.service
    sleep 3
    if systemctl is-active --quiet teetime-monitor.service; then
      say "It is running."
    else
      echo "The service did not start. See why with:  journalctl -u teetime-monitor -n 30" >&2
    fi
  else
    echo "No systemd here: start it with  $WEB --serve --port $PORT" >&2
  fi
fi

HOST="$(hostname)"
say "Open it from any device on this network:"
echo "  http://$HOST.local:$PORT"
IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
[ -z "$IP" ] || echo "  http://$IP:$PORT"
echo
echo "Next: log in with the password, then Settings > pc caddie login."
