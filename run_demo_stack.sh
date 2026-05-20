#!/usr/bin/env bash
# Soak-test the full stack against the RangersTest demo calendar.
#
# Run this in one terminal -- it brings up:
#   - run_cal_update.py  (sync loop: 2h refresh, 60s scan in hot window)
#   - run_web.py         (live FastAPI page on :8765 with SSE)
#
# Both processes inherit CALENDAR_ID from this script's env, so the
# production calendar in .env stays untouched. Send SIGINT (Ctrl-C) to
# stop everything; the trap below kills both children.
#
# Required first time:  ./bootstrap.sh && source env/bin/activate
# Required always:      WEB_PASSWORD set in .env (the web viewer
#                       refuses to serve otherwise).

set -uo pipefail
cd "$(dirname "$0")"

DEMO_CAL='c_92420fb59cb6fcf9ed6753e7224ce02ee704ffee45de20039137fac50c6ac452@group.calendar.google.com'
export CALENDAR_ID="$DEMO_CAL"
# Same SQLite file as prod; the data layer is shared, only the gcal
# push target differs. If you want full isolation use GALAXY_DB_PATH.
# export GALAXY_DB_PATH="galaxy_demo.sqlite3"

if [ ! -d env ]; then
  echo "ERR: env/ not present. Run ./bootstrap.sh first." >&2
  exit 1
fi

# shellcheck disable=SC1091
source env/bin/activate

mkdir -p logs
LOG_SYNC="logs/sync.log"
LOG_WEB="logs/web.log"
: > "$LOG_SYNC"
: > "$LOG_WEB"

echo ">> calendar target: ...${DEMO_CAL: -30}"
echo ">> tailing logs:    $LOG_SYNC and $LOG_WEB"
echo ">> web viewer at:   http://127.0.0.1:${WEB_PORT:-8765}"
echo

python run_cal_update.py >"$LOG_SYNC" 2>&1 &
SYNC_PID=$!
python run_web.py        >"$LOG_WEB"  2>&1 &
WEB_PID=$!

# Live-tail both logs prefixed by source, so you can watch the dance.
( tail -F "$LOG_SYNC" | sed 's/^/[sync] /' ) &
TAIL_SYNC_PID=$!
( tail -F "$LOG_WEB"  | sed 's/^/[web]  /' ) &
TAIL_WEB_PID=$!

cleanup() {
  # Idempotent: trap fires for both INT and EXIT; bail on the second.
  [ -n "${_CLEANUP_DONE:-}" ] && return
  _CLEANUP_DONE=1
  echo
  echo ">> stopping (sync=$SYNC_PID web=$WEB_PID tails=$TAIL_SYNC_PID,$TAIL_WEB_PID)"
  # Kill the tails first so `wait` below doesn't hang on them
  # (tail -F never exits on its own).
  kill "$TAIL_SYNC_PID" "$TAIL_WEB_PID" 2>/dev/null
  kill "$SYNC_PID" "$WEB_PID" 2>/dev/null
  # Give them a moment to clean up; then SIGKILL anything still alive.
  sleep 1
  kill -9 "$SYNC_PID" "$WEB_PID" "$TAIL_SYNC_PID" "$TAIL_WEB_PID" 2>/dev/null
  echo ">> done."
}
trap cleanup EXIT INT TERM

# Block on the sync loop -- if it exits we shut everything down. Wait
# only on the specific PID, NOT bare `wait`, otherwise we also wait for
# the tail -F children which never terminate on their own.
wait "$SYNC_PID"
