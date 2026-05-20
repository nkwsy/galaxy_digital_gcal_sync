# Deploying to a Linux VM

End-to-end procedure to get the sync loop and live web viewer auto-starting
on boot. Tested on Debian/Ubuntu with systemd; should work on any modern
systemd distro.

## Prerequisites

- **Python 3.11+** (3.10 might work but isn't tested; 3.9 will crash --
  the codebase uses PEP 604 `X | None` unions). `bootstrap.sh` checks
  this and aborts with an upgrade recipe if too old.
- **systemd** for the auto-start units. If your box is something else
  you can still run `run_cal_update.py` + `run_web.py` under any
  supervisor (e.g. `supervisord`, `runit`, a `screen` session).
- **Google Calendar OAuth credentials** (`credentials.json`) and a
  cached `token.json` (created on first OAuth flow).

### Bringing a Debian 11 box up to Python 3.11 via pyenv

The OS default on bullseye is 3.9. Easiest non-invasive upgrade:

```bash
sudo apt update
sudo apt install -y build-essential libssl-dev zlib1g-dev libbz2-dev \
    libreadline-dev libsqlite3-dev libffi-dev liblzma-dev curl git

curl https://pyenv.run | bash
# Add the three lines pyenv-installer prints to ~/.bashrc, then:
exec bash

pyenv install 3.11.9
cd ~/galaxy_digital_gcal_sync
pyenv local 3.11.9        # writes .python-version, scoped to this dir
```

After this `python --version` inside the repo reports 3.11.9, and
`./bootstrap.sh` will use it automatically.

## 1. Get the code onto the box

```bash
ssh debmin@<vm>
cd ~
git clone https://github.com/nkwsy/galaxy_digital_gcal_sync.git
cd galaxy_digital_gcal_sync
git checkout claude/sleepy-beaver-2c133a    # or the merged main once the PR lands
```

## 2. Bootstrap the virtualenv

```bash
./bootstrap.sh                  # creates env/, installs deps
source env/bin/activate
```

## 3. Drop the secrets in

```bash
cp .env.example .env
$EDITOR .env
```

At minimum set:

| Variable | What for |
|---|---|
| `API_KEY` / `EMAIL` / `PASSWORD` | Galaxy Digital API user |
| `CALENDAR_ID` | Production Google Calendar id |
| `WEB_PASSWORD` | Required -- web viewer refuses 100% of requests without it |
| `WEB_HOST` | `127.0.0.1` (default) or `0.0.0.0` if you'll reverse-proxy |
| `WEB_PORT` | `8765` (default) |
| `DIGEST_EMAIL_TO` / `SMTP_*` | Only if you want the daily email |

Then bring over the Google Calendar OAuth files **once**:

```bash
# from the machine that already has them, or do the OAuth flow here:
scp credentials.json token.json debmin@<vm>:~/galaxy_digital_gcal_sync/
```

If you don't have `token.json`, run `python verify_galaxy_creds.py` once
interactively -- it will open the OAuth browser flow and write the token.

## 4. Initial ingest (one-time)

Populates SQLite before the systemd unit starts hammering the API:

```bash
python initial_ingest.py
```

You should see ~8k responses + ~20 recent hours + ~7k backfilled no-shows.

## 5. Preview what would change on the production calendar

```bash
python preview_production_sync.py --days 30
```

Look at the INSERT / UPDATE / NO-OP / ORPHAN counts. Zero inserts means
event ids match between the existing data and the new code -- no
duplicates. Backup the production calendar first if you want a safety net:

```bash
# Google Calendar Settings -> "Export calendar" downloads everything as
# an .ics zip. Save it somewhere safe.
```

## 6. Install the systemd units

```bash
sudo ./setup_galaxy_sync_service.sh
```

This writes two unit files and enables-and-starts both:

| Unit | Purpose |
|---|---|
| `galaxy_sync.service` | runs `run_cal_update.py` -- the 2h full refresh + 60s scan loop |
| `galaxy_web.service`  | runs `run_web.py` -- FastAPI on `127.0.0.1:8765` |

Customize paths via env if your layout differs:

```bash
WORKING_DIR=/opt/galaxy USER=galaxy sudo -E ./setup_galaxy_sync_service.sh
```

## 7. Verify

```bash
sudo systemctl status galaxy_sync.service galaxy_web.service
sudo journalctl -u galaxy_sync -f          # watch the sync log
curl -u volunteer:$WEB_PASSWORD http://127.0.0.1:8765/ | head
```

After a few minutes you should see lines like:

```
Scan tick: pushed 1 shift updates
update_responses: pushing 36 changed shift(s) to gcal
```

## Management cheatsheet

```bash
sudo systemctl restart galaxy_sync.service
sudo systemctl stop    galaxy_sync.service galaxy_web.service
sudo systemctl disable galaxy_sync.service galaxy_web.service   # remove from boot

# logs
sudo journalctl -u galaxy_sync.service -f
sudo journalctl -u galaxy_web.service -f
tail -F /home/debmin/galaxy_digital_gcal_sync/debug.log

# one-off digest preview
sudo -u debmin -E env GALAXY_DB_PATH=/home/debmin/galaxy_digital_gcal_sync/galaxy_sync.sqlite3 \
  /home/debmin/galaxy_digital_gcal_sync/env/bin/python -m digest --dry-run
```

## Upgrades

```bash
cd /home/debmin/galaxy_digital_gcal_sync
git pull
source env/bin/activate
pip install -r requirements.txt   # if requirements changed
sudo systemctl restart galaxy_sync.service galaxy_web.service
```

## Exposing the web viewer beyond localhost

By default `WEB_HOST=127.0.0.1` -- only reachable on the box. To make it
LAN-accessible behind nginx with TLS:

```nginx
server {
  listen 443 ssl;
  server_name volunteer-status.example.org;
  ssl_certificate     /etc/letsencrypt/live/.../fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/.../privkey.pem;

  location / {
    proxy_pass http://127.0.0.1:8765;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    # SSE: keep the stream open
    proxy_buffering off;
    proxy_read_timeout 1h;
    proxy_http_version 1.1;
  }
}
```

The HTTP Basic auth from `WEB_PASSWORD` continues to gate access; nginx
just adds TLS on the outside.
