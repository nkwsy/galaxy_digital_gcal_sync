#!/usr/bin/env bash
# Install systemd units that run the sync loop and web viewer on boot.
#
# Two units get created:
#   galaxy_sync.service   -- runs run_cal_update.py forever
#   galaxy_web.service    -- runs run_web.py (FastAPI on 127.0.0.1:8765)
#
# Each one:
#   - Lives under /etc/systemd/system/
#   - Starts after the network is up
#   - Restarts on crash with a 5s backoff
#   - Reads its env from $WORKING_DIR/.env (so secrets stay out of the unit)
#   - Runs as $USER:$GROUP (customize below)
#
# Run with sudo:
#     sudo ./setup_galaxy_sync_service.sh
#
# Override paths / user via env if your layout differs:
#     WORKING_DIR=/opt/galaxy USER=galaxy sudo -E ./setup_galaxy_sync_service.sh

set -euo pipefail

SYNC_SERVICE="${SYNC_SERVICE:-galaxy_sync.service}"
WEB_SERVICE="${WEB_SERVICE:-galaxy_web.service}"
WORKING_DIR="${WORKING_DIR:-/home/debmin/galaxy_digital_gcal_sync}"
VENV_DIR="${VENV_DIR:-$WORKING_DIR/env}"
USER_NAME="${USER:-debmin}"
GROUP_NAME="${GROUP:-debmin}"
ENV_FILE="${ENV_FILE:-$WORKING_DIR/.env}"

if [ "$(id -u)" -ne 0 ]; then
  echo "this script must be run as root (try: sudo $0)" >&2
  exit 1
fi

if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "no venv at $VENV_DIR -- run ./bootstrap.sh first." >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "no .env at $ENV_FILE -- copy .env.example and fill it in." >&2
  exit 1
fi

# --- galaxy_sync.service ---------------------------------------------------
cat <<EOT > /etc/systemd/system/$SYNC_SERVICE
[Unit]
Description=Galaxy Digital -> Google Calendar sync loop
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$WORKING_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$VENV_DIR/bin/python $WORKING_DIR/run_cal_update.py
Restart=always
RestartSec=5
User=$USER_NAME
Group=$GROUP_NAME
# loguru writes to debug.log inside WorkingDirectory; this also pipes
# stdout/stderr to journald so 'journalctl -u $SYNC_SERVICE -f' works.
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOT

# --- galaxy_web.service ----------------------------------------------------
cat <<EOT > /etc/systemd/system/$WEB_SERVICE
[Unit]
Description=Galaxy Digital live web viewer (FastAPI/uvicorn)
After=network-online.target $SYNC_SERVICE
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$WORKING_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$VENV_DIR/bin/python $WORKING_DIR/run_web.py
Restart=always
RestartSec=5
User=$USER_NAME
Group=$GROUP_NAME
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOT

systemctl daemon-reload
systemctl enable "$SYNC_SERVICE" "$WEB_SERVICE"
systemctl restart "$SYNC_SERVICE" "$WEB_SERVICE"

echo
echo ">> installed and started:"
systemctl --no-pager --lines=4 status "$SYNC_SERVICE" || true
echo
systemctl --no-pager --lines=4 status "$WEB_SERVICE" || true
echo
cat <<TIPS

Management:
  sudo systemctl status   $SYNC_SERVICE $WEB_SERVICE
  sudo systemctl restart  $SYNC_SERVICE
  sudo systemctl stop     $SYNC_SERVICE $WEB_SERVICE
  sudo systemctl disable  $SYNC_SERVICE $WEB_SERVICE   # stop autostart

Logs:
  sudo journalctl -u $SYNC_SERVICE -f
  sudo journalctl -u $WEB_SERVICE  -f
  tail -F $WORKING_DIR/debug.log

Web viewer:
  http://127.0.0.1:\${WEB_PORT:-8765}
  (set WEB_PASSWORD in .env first or every request returns 503)
TIPS
