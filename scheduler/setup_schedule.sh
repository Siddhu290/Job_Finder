#!/usr/bin/env bash
# Manage the twice-daily (08:00 and 20:00 Asia/Kolkata) systemd user timer for Fresher Data Job Finder.
# Usage: scheduler/setup_schedule.sh install|status|run-now|disable|enable|uninstall
set -euo pipefail

NAME=fresher-job-finder
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
PY="$PROJECT_DIR/.venv/bin/python"

install() {
  echo "Use exactly ONE scheduler. If this project is deployed to Vercel with crons enabled, do not install this timer."
  read -r -p "Install the local systemd timer? [y/N] " ok; [[ "$ok" == [yY]* ]] || { echo "Cancelled."; exit 1; }
  [[ -x "$PY" ]] || { echo "virtualenv missing: run 'python3 -m venv .venv && .venv/bin/pip install -r requirements.txt' first"; exit 1; }
  mkdir -p "$UNIT_DIR"
  cat > "$UNIT_DIR/$NAME.service" <<EOF
[Unit]
Description=Fresher Data Job Finder (discover + verify + write to Google Sheets)
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$PROJECT_DIR
# systemd never starts a still-running oneshot twice; main.py also holds a file lock against manual runs
ExecStart=$PY $PROJECT_DIR/main.py --use-saved-settings --trigger cron
TimeoutStartSec=45min
KillSignal=SIGTERM
TimeoutStopSec=120
Nice=10
EOF
  cat > "$UNIT_DIR/$NAME.timer" <<EOF
[Unit]
Description=Run Fresher Data Job Finder at 08:00 and 20:00 India time

[Timer]
OnCalendar=*-*-* 08,20:00:00 Asia/Kolkata
Persistent=true
RandomizedDelaySec=120

[Install]
WantedBy=timers.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now "$NAME.timer"
  if ! loginctl show-user "$USER" -p Linger 2>/dev/null | grep -q yes; then
    echo "NOTE: to run while you are logged out, enable lingering once:  sudo loginctl enable-linger $USER"
  fi
  status
}

status() {
  systemctl --user list-timers "$NAME.timer" --all
  echo; echo "Recent logs: journalctl --user -u $NAME.service -n 50   (app log: $PROJECT_DIR/logs/job_finder.log)"
}

case "${1:-}" in
  install)   install ;;
  status)    status ;;
  run-now)   systemctl --user start "$NAME.service" && journalctl --user -u "$NAME.service" -n 40 --no-pager ;;
  disable)   systemctl --user disable --now "$NAME.timer" && echo "timer disabled (unit files kept)" ;;
  enable)    systemctl --user enable --now "$NAME.timer" && status ;;
  uninstall) systemctl --user disable --now "$NAME.timer" 2>/dev/null || true
             rm -f "$UNIT_DIR/$NAME.timer" "$UNIT_DIR/$NAME.service"
             systemctl --user daemon-reload && echo "schedule removed" ;;
  *) echo "usage: $0 install|status|run-now|disable|enable|uninstall"; exit 1 ;;
esac
