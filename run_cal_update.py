import get_connected as gc
import gcal
import importlib
import time
from loguru import logger
import os
from datetime import datetime, timezone
import pytz
from dotenv import load_dotenv
import requests
import json

import db
import digest as digest_mod

load_dotenv()
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
CHICAGO = pytz.timezone('America/Chicago')

# Digest schedule: cron-light. Examples:
#   DIGEST_SCHEDULE=daily@21:00      every day at 9pm CT
#   DIGEST_SCHEDULE=hourly           every hour at :00
#   DIGEST_SCHEDULE=off              never
DIGEST_SCHEDULE = os.getenv('DIGEST_SCHEDULE', 'daily@21:00')


def _digest_due(now_ct: datetime, last_sent_iso: str | None) -> bool:
    """Decide whether the current tick should fire the digest. Returns True
    if we've crossed the scheduled boundary since `last_sent_iso`.
    """
    sched = (DIGEST_SCHEDULE or '').lower().strip()
    if sched in ('off', 'never', ''):
        return False
    last_sent = None
    if last_sent_iso:
        try:
            last_sent = datetime.fromisoformat(last_sent_iso)
        except ValueError:
            last_sent = None
    if sched == 'hourly':
        boundary = now_ct.replace(minute=0, second=0, microsecond=0)
    elif sched.startswith('daily@'):
        try:
            hh, mm = map(int, sched.split('@', 1)[1].split(':'))
        except (ValueError, IndexError):
            hh, mm = 21, 0
        boundary = now_ct.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if now_ct < boundary:
            return False
    else:
        return False
    if last_sent is None:
        return now_ct >= boundary
    # Convert last_sent (UTC iso) to CT for comparison.
    if last_sent.tzinfo is None:
        last_sent = pytz.UTC.localize(last_sent).astimezone(CHICAGO)
    else:
        last_sent = last_sent.astimezone(CHICAGO)
    return last_sent < boundary <= now_ct


def maybe_send_digest():
    """Fire the digest if we've crossed a schedule boundary. No-op otherwise."""
    db.init()
    with db.connect() as conn:
        last_sent_iso = db.get_state(conn, 'last_digest_sent_at')
    if not _digest_due(datetime.now(CHICAGO), last_sent_iso):
        return
    try:
        data = digest_mod.collect(days_back=int(os.getenv('DIGEST_LOOKBACK_DAYS', '1')))
        html = digest_mod.render_html(data)
        text = digest_mod.render_text(data)
        ok = digest_mod.send(data, html, text)
        if ok:
            with db.connect() as conn:
                db.set_state(conn, 'last_digest_sent_at',
                             datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec='seconds'))
            logger.info('digest sent')
        else:
            logger.info('digest skipped (missing DIGEST_EMAIL_TO or SMTP_HOST)')
    except Exception as e:
        logger.error(f'digest failed: {e}')

def post_to_slack( message):
    headers = {'Content-Type': 'application/json'}
    data = json.dumps({'text': message})
    
    response = requests.post(WEBHOOK_URL, headers=headers, data=data)
    if response.status_code == 200:
        print("Message posted successfully!")
    else:
        print(f"Failed to post message. Status code: {response.status_code}, Response: {response.text}")
    return response

def update_cal():
    """Main loop.

    Cadence:
      - Full /responses refresh every 2 hours (REFRESH_INTERVAL_S).
      - Check-in scan every 60s when a shift is happening soon, just ended,
        or is currently in progress (window: -1h .. +1h of a shift boundary).
      - Otherwise sleep 5 minutes between idle ticks.

    Both helpers are now corrected:
      - get_next_shift() -> seconds UNTIL next start (inf if none)
      - get_last_shift() -> seconds SINCE last end       (inf if none)
    """
    REFRESH_INTERVAL_S = 2 * 3600
    SCAN_HOT_WINDOW_S = 3600
    fail_count = 0
    last_refresh = 0.0
    while True:
        try:
            gcc = gc.GalaxyAPI()
            now = time.time()
            if now - last_refresh > REFRESH_INTERVAL_S:
                gcc.update_responses()
                last_refresh = now
                logger.debug("Full /responses refresh complete")

            next_in = gcc.get_next_shift()    # seconds until next start
            since_last = gcc.get_last_shift()  # seconds since last end
            hot = (next_in < SCAN_HOT_WINDOW_S) or (since_last < SCAN_HOT_WINDOW_S)

            if hot:
                changed = gcc.user_checkin_update()
                logger.debug(f"Scan tick: pushed {len(changed) if changed else 0} shift updates")
                maybe_send_digest()
                time.sleep(60)
            else:
                logger.debug(f"Idle: next shift in {next_in:.0f}s, last ended {since_last:.0f}s ago")
                maybe_send_digest()
                time.sleep(300)

            importlib.reload(gc)
            importlib.reload(gcal)
            fail_count = 0
        except Exception as e:
            fail_count += 1
            logger.error(f"failed: {fail_count}. {e}")
            post_to_slack(f"Galaxy_gcal_sync \n failed: {fail_count} sleeptime:{fail_count*60}.\n {e}")
            time.sleep(fail_count * 60)
update_cal()
