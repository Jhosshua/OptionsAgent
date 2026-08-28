#!/bin/zsh
set -euo pipefail

APP="/Users/mo/OptionsAgent"
LABEL="com.optionsagent.dashboard"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_TARGET="$PLIST_DIR/$LABEL.plist"

mkdir -p "$PLIST_DIR" "$APP/data/logs"
cp "$APP/deploy/$LABEL.plist" "$PLIST_TARGET"
chmod 644 "$PLIST_TARGET"

launchctl bootout "gui/$UID/$LABEL" >/dev/null 2>&1 || true
for _ in {1..10}; do
  launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1 || break
  sleep 1
done
launchctl bootstrap "gui/$UID" "$PLIST_TARGET"
launchctl enable "gui/$UID/$LABEL" >/dev/null 2>&1 || true
launchctl kickstart -k "gui/$UID/$LABEL"

healthy=false
for _ in {1..10}; do
  if curl -fsS http://127.0.0.1:8765/healthz >/dev/null 2>&1; then
    healthy=true
    break
  fi
  sleep 1
done
if [ "$healthy" != true ]; then
  echo "Dashboard failed its health check." >&2
  echo "Inspect $APP/data/logs/dashboard-local.err.log" >&2
  exit 1
fi

echo "OptionsAgent dashboard is running at http://127.0.0.1:8765"
echo "LaunchAgent: $PLIST_TARGET"
