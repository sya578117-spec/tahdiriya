#!/bin/bash
# Watchdog: restart tahdiriya bot if it's not polling. Reads secrets from .env (600).
DIR="$HOME/workspace/baccalaureate-bot/tahdiriya"
if pgrep -f "[b]ot_runner.py" > /dev/null; then
  exit 0
fi
cd "$DIR" || exit 1
set -a
. "$DIR/.env"
set +a
nohup "$DIR/.venv/bin/python" bot_runner.py >> "$DIR/logs/bot.log" 2>&1 &
echo "watchdog: restarted bot at $(date -u +%FT%TZ)"
