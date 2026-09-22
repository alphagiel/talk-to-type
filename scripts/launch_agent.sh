#!/bin/bash
# Manages a macOS LaunchAgent so talk-to-type starts automatically at
# login instead of needing to be run from a terminal every time.
#
# Usage:
#   scripts/launch_agent.sh install    # start now + on every future login
#   scripts/launch_agent.sh uninstall  # stop and remove the auto-start
#   scripts/launch_agent.sh status     # check whether it's running
set -euo pipefail

PACKAGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$PACKAGE_ROOT/venv/bin/python"
LABEL="com.talk-to-type.agent"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/PTTDictation"

install_agent() {
  if [ ! -x "$VENV_PYTHON" ]; then
    echo "Python virtual environment not found at $VENV_PYTHON"
    echo "Run 'npm install' (or set up venv/requirements.txt manually) first."
    exit 1
  fi

  mkdir -p "$LOG_DIR"
  mkdir -p "$HOME/Library/LaunchAgents"

  cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$VENV_PYTHON</string>
        <string>-m</string>
        <string>ptt_dictation.main</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PACKAGE_ROOT</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/stderr.log</string>
</dict>
</plist>
PLIST

  launchctl unload "$PLIST_PATH" 2>/dev/null || true
  launchctl load -w "$PLIST_PATH"

  echo "Installed and started. It will now launch automatically every time you log in."
  echo "Logs: $LOG_DIR/stdout.log and $LOG_DIR/stderr.log"
}

uninstall_agent() {
  if [ -f "$PLIST_PATH" ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"
    echo "Removed. It will no longer start automatically at login."
  else
    echo "Not installed (no plist found at $PLIST_PATH)."
  fi
}

status_agent() {
  if launchctl list | grep -q "$LABEL"; then
    echo "Running (managed by launchd)."
    launchctl list | grep "$LABEL"
  else
    echo "Not running."
  fi
}

case "${1:-}" in
  install) install_agent ;;
  uninstall) uninstall_agent ;;
  status) status_agent ;;
  *)
    echo "Usage: $0 {install|uninstall|status}"
    exit 1
    ;;
esac
