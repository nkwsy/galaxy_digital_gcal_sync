#!/bin/bash

SERVICE_NAME="galaxy_sync.service"
WORKING_DIR="/home/debmin/galaxy_digital_gcal_sync"
VENV_DIR="$WORKING_DIR/env"
EXEC_CMD="python run_cal_update.py"
USER="debmin"
GROUP="debmin"

# Create the service file
sudo bash -c "cat <<EOT > /etc/systemd/system/$SERVICE_NAME
[Unit]
Description=Galaxy Digital Google Calendar Sync
After=network.target

[Service]
WorkingDirectory=$WORKING_DIR
ExecStart=$VENV_DIR/bin/$EXEC_CMD
Environment=\"PATH=$VENV_DIR/bin\"
Restart=always
User=$USER
Group=$GROUP

[Install]
WantedBy=multi-user.target
EOT"

# Reload systemd daemon to apply the new service
sudo systemctl daemon-reload

# Enable the service to start on boot
sudo systemctl enable $SERVICE_NAME

# Start the service immediately
sudo systemctl start $SERVICE_NAME

# Check the status of the service
sudo systemctl status $SERVICE_NAME
