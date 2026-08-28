#!/bin/zsh
set -euo pipefail

APP="/Users/mo/OptionsAgent"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export OA_DASHBOARD_HOST="127.0.0.1"
export PORT="8765"

cd "$APP"
exec python3 -m harness.dashboard_server
