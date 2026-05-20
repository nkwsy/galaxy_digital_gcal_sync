"""Preview what the first sync to production would do.

Compares the shifts currently in SQLite against what's actually on the
production calendar (read-only) and prints a per-shift diff plan:

  INSERT   shift_id  start  title    (no matching event on cal)
  UPDATE   shift_id  start  title    (event exists, description/location/title differ)
  NO-OP    shift_id  start  title    (event exists, content identical)
  ORPHAN   event_id  start  title    (event on cal has no matching Galaxy shift)

Reads the production CALENDAR_ID from .env. Does NOT write anything.

Usage:
    python preview_production_sync.py [--days N]
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

import checkin  # noqa: E402
import db  # noqa: E402
import gcal  # noqa: E402


def build_expected_event(shift: dict) -> dict:
    """Mirror what gcal.update_calendar_events would compose."""
    lines = ["Signups:"]
    for u in shift["users"]:
        st = u.get("checkin_status") or checkin.SIGNED_UP
        emoji = checkin.STATUS_EMOJI.get(st, "🔘")
        lines.append(f"{emoji} {u.get('fname','')} {u.get('lname','')} "
                     f"email: {u.get('email','')}")
    description = "\n".join(lines) + "\n"
    return {
        "summary": f"{shift['title']} - ({shift['slots_filled']}/{shift['slots']}) ",
        "location": shift.get("location") or "",
        "description": description,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=14,
                   help="how many days forward to inspect (default 14)")
    args = p.parse_args()

    cal_id = os.getenv("CALENDAR_ID")
    if not cal_id:
        print("CALENDAR_ID is not set in .env", file=sys.stderr)
        return 1
    print(f"-> production calendar id: ...{cal_id[-30:]}")
    print(f"-> window: today + {args.days}d")
    print(f"-> mode: READ ONLY -- nothing will be written.\n")

    # Build what we would push.
    now_ct = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    horizon = (datetime.now() + timedelta(days=args.days)).strftime("%Y-%m-%d %H:%M:%S")
    expected: dict[str, dict] = {}
    with db.connect() as conn:
        shifts = conn.execute(
            """SELECT s.id, s.start_ts, s.end_ts, s.slots, s.need_id,
                      n.title, n.location
               FROM shifts s LEFT JOIN needs n ON n.id = s.need_id
               WHERE s.start_ts >= ? AND s.start_ts < ?
               ORDER BY s.start_ts
            """,
            (now_ct, horizon),
        ).fetchall()
        for s in shifts:
            sgs = db.signups_for_shift(conn, s["id"])
            users = []
            for sg in sgs:
                users.append({
                    "fname": sg["fname"], "lname": sg["lname"], "email": sg["email"],
                    "response_id": sg["response_id"],
                    "checkin_status": sg["classification"] or checkin.SIGNED_UP,
                })
            expected[s["id"]] = {
                "id": s["id"],
                "start": s["start_ts"],
                "title": s["title"],
                "slots": s["slots"],
                "slots_filled": len(users),
                "location": s["location"],
                "users": users,
            }

    # Pull existing calendar events in the same window.
    svc = gcal.get_service()
    time_min = datetime.now().isoformat() + "Z"
    time_max = (datetime.now() + timedelta(days=args.days)).isoformat() + "Z"
    actual: dict[str, dict] = {}
    page_token = None
    while True:
        resp = svc.events().list(
            calendarId=cal_id, maxResults=2500,
            timeMin=time_min, timeMax=time_max,
            singleEvents=True, pageToken=page_token,
        ).execute()
        for e in resp.get("items", []):
            actual[e["id"]] = e
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    inserts, updates, noops, orphans = [], [], [], []
    for sid, shift in expected.items():
        ev = actual.get(sid)
        if ev is None:
            inserts.append(shift)
            continue
        want = build_expected_event(shift)
        diffs = []
        if (ev.get("summary") or "") != want["summary"]:
            diffs.append("summary")
        if (ev.get("location") or "") != want["location"]:
            diffs.append("location")
        if (ev.get("description") or "") != want["description"]:
            diffs.append("description")
        if diffs:
            updates.append((shift, diffs))
        else:
            noops.append(shift)

    for eid, ev in actual.items():
        if eid not in expected:
            orphans.append(ev)

    def _fmt(s):
        return f"{s['start'][:16]}  ({s['slots_filled']}/{s['slots']})  {(s['title'] or '')[:50]}"

    print(f"=== INSERT ({len(inserts)}) -- shifts that would be created ===")
    for s in inserts:
        print(f"  + {_fmt(s)}")
    print()
    print(f"=== UPDATE ({len(updates)}) -- existing events that would be rewritten ===")
    for s, diffs in updates:
        print(f"  ~ {_fmt(s)}    [{','.join(diffs)}]")
    print()
    print(f"=== NO-OP ({len(noops)}) -- already up to date ===")
    for s in noops[:10]:
        print(f"    {_fmt(s)}")
    if len(noops) > 10:
        print(f"    ... and {len(noops) - 10} more")
    print()
    print(f"=== ORPHANS ({len(orphans)}) -- on the cal but no matching Galaxy shift ===")
    for ev in orphans[:10]:
        start = ((ev.get("start") or {}).get("dateTime") or "")[:16]
        print(f"  ? id={ev['id']:>20}  {start}  {ev.get('summary','')[:50]}")
    if len(orphans) > 10:
        print(f"  ? ... and {len(orphans) - 10} more  (these stay untouched)")
    print()
    print(f"Summary: {len(inserts)} inserts + {len(updates)} updates + "
          f"{len(noops)} no-ops + {len(orphans)} orphans (left alone)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
