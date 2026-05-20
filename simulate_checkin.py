"""Forge a kiosk check-in / check-out locally for soak-testing.

This writes a synthetic hours row directly into SQLite. It does NOT
touch the Galaxy Digital API -- the next sync_hours() run would
overwrite anything you fake here, but in the meantime the gcal pusher
and the web viewer will both react as if a real volunteer just walked
up to the kiosk.

Usage:
    # List today's signups so you can pick a response_id
    python simulate_checkin.py list

    # Mark someone checked-in (yellow dot)
    python simulate_checkin.py in  <response_id>

    # Mark them checked-out (green dot)
    python simulate_checkin.py out <response_id>

    # Clear the simulated record (revert to signed_up)
    python simulate_checkin.py clear <response_id>
"""
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

import checkin
import db


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def cmd_list(_args):
    db.init()
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT sg.id AS rid, u.fname, u.lname, u.email,
                      s.id AS sid, s.start_ts, n.title,
                      h.classification
               FROM signups sg
               JOIN users u  ON u.id = sg.user_id
               JOIN shifts s ON s.id = sg.shift_id
               LEFT JOIN needs n ON n.id = s.need_id
               LEFT JOIN hours h ON h.response_id = sg.id
               WHERE date(s.start_ts) = date('now','localtime')
               ORDER BY s.start_ts, u.lname
            """,
        ).fetchall()
    if not rows:
        print("no signups for today")
        return
    print(f"{'response_id':>12}  {'shift_start':16}  {'status':14}  who")
    print("-" * 90)
    for r in rows:
        st = r["classification"] or checkin.SIGNED_UP
        emoji = checkin.STATUS_EMOJI.get(st, "?")
        print(f"{r['rid']:>12}  {r['start_ts'][:16]}  {emoji} {st:12}  "
              f"{r['fname']} {r['lname']}  {(r['title'] or '')[:40]}")


def _write_hour(rid: str, source: str) -> None:
    db.init()
    with db.connect() as conn:
        sg = conn.execute(
            "SELECT sg.user_id, sg.shift_id, sg.need_id "
            "FROM signups sg WHERE sg.id = ?", (rid,)
        ).fetchone()
        if not sg:
            print(f"no signup with response_id={rid}", file=sys.stderr)
            sys.exit(1)
        # Use a synthetic id that won't collide with real /hours rows
        # (real ids are numeric strings; ours starts with "sim-").
        hid = f"sim-{uuid.uuid4().hex[:10]}"
        conn.execute("BEGIN")
        # Idempotent: if a simulated row already exists for this rid,
        # update it rather than insert a second one.
        existing = conn.execute(
            "SELECT id FROM hours WHERE response_id = ? AND id LIKE 'sim-%' LIMIT 1",
            (rid,)
        ).fetchone()
        if existing:
            hid = existing["id"]
            classification = checkin.classify_hour(checkin.HourSignal.from_api({
                "hour_response_id": rid,
                "hour_source": source,
                "user": {"id": sg["user_id"]},
            }))
            conn.execute(
                "UPDATE hours SET source=?, classification=?, updated_at=? WHERE id=?",
                (source, classification, _now(), hid),
            )
        else:
            db.ingest_hour(conn, {
                "id": hid,
                "hour_response_id": rid,
                "user": {"id": sg["user_id"]},
                "need": {"id": sg["need_id"]},
                "hour_source": source,
                "hour_status": "approved",
                "hour_date_start": _now(),
                "hour_date_end": _now(),
                "created_at": _now(),
                "updated_at": _now(),
            })
        # Also stamp the gcal fingerprint key so the next user_checkin_update
        # tick will actually push -- without this the sync loop would compute
        # the same fingerprint it had cached and skip.
        conn.execute(
            "DELETE FROM scan_state WHERE key = ?",
            (f"gcal_fp:{sg['shift_id']}",),
        )
        conn.execute("COMMIT")
    print(f"wrote simulated hour {hid} for response_id={rid}")
    print("  source:", source)
    print("  Next sync tick (~60s in hot window) will push the change.")


def cmd_in(args):
    _write_hour(args.response_id,
                "Added at: /kiosk/storeCheckin/ by simulate_checkin.py")


def cmd_out(args):
    _write_hour(args.response_id,
                "Added at: /kiosk/storeCheckin/ by simulate_checkin.py "
                "Updated at: /kiosk/storeCheckout/ by simulate_checkin.py")


def cmd_clear(args):
    db.init()
    with db.connect() as conn:
        n = conn.execute(
            "DELETE FROM hours WHERE response_id = ? AND id LIKE 'sim-%'",
            (args.response_id,),
        ).rowcount
        # Force a gcal repush.
        sg = conn.execute("SELECT shift_id FROM signups WHERE id=?",
                          (args.response_id,)).fetchone()
        if sg:
            conn.execute("DELETE FROM scan_state WHERE key=?",
                         (f"gcal_fp:{sg['shift_id']}",))
    print(f"cleared {n} simulated hour(s) for response_id={args.response_id}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    pi = sub.add_parser("in");   pi.add_argument("response_id")
    po = sub.add_parser("out");  po.add_argument("response_id")
    pc = sub.add_parser("clear"); pc.add_argument("response_id")
    args = p.parse_args()
    {"list": cmd_list, "in": cmd_in, "out": cmd_out, "clear": cmd_clear}[args.cmd](args)


if __name__ == "__main__":
    main()
