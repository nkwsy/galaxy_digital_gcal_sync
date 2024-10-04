# to run

`source env/bin/activate`
`python run_cal_update`

# Galaxy Digital Google Calendar Sync

This project synchronizes events from Galaxy Digital to a Google Calendar. It automates the process of updating your Google Calendar with events managed in Galaxy Digital, ensuring that your calendar stays up-to-date without manual intervention.

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
