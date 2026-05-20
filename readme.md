# quick start

```bash
./bootstrap.sh                     # creates env/, installs deps (one-time)
source env/bin/activate
cp .env.example .env               # then fill in API_KEY, EMAIL, PASSWORD, etc.

python verify_galaxy_creds.py      # smoke-test API credentials
python run_cal_update.py           # sync loop + digest scheduler
python run_web.py                  # live web viewer (separate process)
python -m digest --dry-run         # render the digest to stdout
```

If you skip `bootstrap.sh` and `python3 -m venv env` was never run, the
README's old `source env/bin/activate` will fail with "no such file or
directory" -- that's why the bootstrap script exists.

# Galaxy Digital Google Calendar Sync

This project synchronizes events from Galaxy Digital to a Google Calendar.
It also:

- Tracks live check-in / check-out state per volunteer (kiosk-source
  detection -- `hour_status` and `hour_date_end` are not reliable signals).
- Stores everything in a local SQLite database (`galaxy_sync.sqlite3`) so
  the calendar push, email digest, and web page all share one source of
  truth.
- Sends a daily HTML email digest (signed up / checked in / checked out /
  no-show + repeat-offender table). Schedule and recipient configurable in
  `.env`.
- Exposes a local FastAPI page (default `http://127.0.0.1:8765`) for
  real-time monitoring during shifts.

## Architecture

```
              ┌──────────────────┐
              │ Galaxy Digital   │
              │   /responses     │
              │   /hours         │
              └────────┬─────────┘
                       │ poll
                       ▼
   ┌────────────────────────────────────┐
   │ sync.py   (ingest)                 │
   │   ↳ checkin.py  (classify hours)   │
   │   ↳ db.py       (SQLite I/O)       │
   └────┬───────────────┬───────────────┘
        │ shifts        │ status_history
        ▼               ▼
   ┌────────┐      ┌──────────┐      ┌──────────┐
   │ gcal.py│      │ digest.py│      │ web.py   │
   │  push  │      │  email   │      │  FastAPI │
   └────────┘      └──────────┘      └──────────┘
```

`run_cal_update.py` drives the sync loop (2h full refresh, 60s scan when a
shift is within ±1h, idle sleep otherwise) and fires the digest when the
configured schedule (`DIGEST_SCHEDULE=daily@21:00` etc.) crosses a
boundary. The web app reads the SQLite DB independently.

## Table of Contents

- [to run](#to-run)
- [Galaxy Digital Google Calendar Sync](#galaxy-digital-google-calendar-sync)
  - [Table of Contents](#table-of-contents)
  - [Features](#features)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Configuration](#configuration)
  - [Usage](#usage)
  - [Setting Up as a Systemd Service](#setting-up-as-a-systemd-service)
  - [Managing the Service](#managing-the-service)

## Features

- **Automated Syncing**: Automatically fetches events from Galaxy Digital and updates your Google Calendar.
- **Virtual Environment**: Uses a Python virtual environment for dependency management.
- **Systemd Service**: Can be set up as a systemd service to run at system startup.
- **Customizable**: Easily configurable to suit different environments and requirements.

## Prerequisites

- **Python 3.x** installed on your system.
- **pip** package installer.
- **virtualenv** for creating a virtual environment.
- **Git** (if cloning the repository).
- **Google Calendar API Credentials**:
  - Access to the [Google Calendar API](https://developers.google.com/calendar).
  - A `credentials.json` file obtained from Google Cloud Console.
- **Galaxy Digital API Access**
  - #Galaxy Digital [API docs](http://api.galaxydigital.com/docs/#/Event)

## Installation

1. **Clone the Repository**

   ````bash
   git clone https://github.com/nkwsy/galaxy_digital_gcal_sync.git
   cd galaxy_digital_gcal_sync```
   ````

2. **Create and Activate Virtual Environment:**

   ````bash
    python -m venv env
    source env/bin/activate```
   ````

3. **Install Dependencies**

   ```bash
   pip install -r requirements.txt
   ```

## Configuration

1. **Google Calendar API Setup:**

- Enable the Google Calendar API in the Google API Console.
- [gCal python api quickstart](https://developers.google.com/calendar/api/quickstart/python)
- Obtain OAuth 2.0 client credentials (`credentials.json`) and place it in the project root.

2. **Galaxy Digital API Setup:**

- Obtain API credentials from your Galaxy Digital account.
- Update any configuration files (e.g., config.json) with your API credentials.

## Usage

Run the sync script:

```bash
source env/bin/activate
python run_cal_update.py
```

## Setting Up as a Systemd Service

1. Make the Setup Script Executable:

```bash
chmod +x setup_galaxy_sync_service.sh
```

2. Run the Setup Script:

```bash
sudo ./setup_galaxy_sync_service.sh
```

## Managing the Service

You can manage the `galaxy_sync.service` using standard `systemctl` commands:

- **Start the Service**

  ```bash
  sudo systemctl start galaxy_sync.service
  ```

- **Stop the Service**

  ```bash
  sudo systemctl stop galaxy_sync.service
  ```

- **Restart the Service**

  ```bash
  sudo systemctl restart galaxy_sync.service
  ```

- **Check the Status of the Service**

  ```bash
  sudo systemctl status galaxy_sync.service
  ```

- **Enable the Service at Boot**

  ```bash
  sudo systemctl enable galaxy_sync.service
  ```

- **Disable the Service at Boot**

  ```bash
  sudo systemctl disable galaxy_sync.service
  ```

- **View Service Logs**

  ```bash
  sudo journalctl -u galaxy_sync.service
  ```

**Note**: Replace `galaxy_sync.service` with the name of your service file if it's different.

This section allows you to control the service that runs your Galaxy Digital Google Calendar Sync script, ensuring it operates as expected and providing commands to troubleshoot if necessary.

This will create and start a systemd service that runs the sync script at system startup.
