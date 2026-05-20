"""Unit tests for the status classifier.

These are the lowest-stakes most-frequently-broken bits: getting the
hour_source substring matching wrong, or the kiosk-in vs kiosk-out
priority backwards. Lock the behavior down here.
"""
from __future__ import annotations

import pytest

import checkin


def _hour(source: str = "", response_id: str | None = "r1",
          user_id: str | None = "u1", status: str = "approved") -> dict:
    return {
        "id": "h1",
        "hour_response_id": response_id,
        "hour_source": source,
        "hour_status": status,
        "hour_date_start": "2026-05-19 10:00:00",
        "hour_date_end": "2026-05-19 12:00:00",
        "user": {"id": user_id} if user_id else None,
    }


def test_classify_kiosk_checkin_only():
    h = checkin.HourSignal.from_api(_hour(source="Added at: /kiosk/storeCheckin/ by user 1"))
    assert checkin.classify_hour(h) == checkin.CHECKED_IN


def test_classify_kiosk_full_roundtrip():
    h = checkin.HourSignal.from_api(_hour(
        source="Added at: /kiosk/storeCheckin/ by user 1 Updated at: /kiosk/storeCheckout/ by user 1"
    ))
    assert checkin.classify_hour(h) == checkin.CHECKED_OUT


def test_classify_manager_added():
    h = checkin.HourSignal.from_api(_hour(
        source="Added at: /manager/hours_edit/ by Someone"
    ))
    assert checkin.classify_hour(h) == checkin.MANAGER_ENTERED


def test_classify_kiosk_in_then_manager_edit_stays_checked_in():
    """A kiosk-checked-in volunteer whose record was later touched by a
    manager (but not checked out) is still checked_in, not manager_entered.
    The kiosk_checked_in property must take priority over manager_entered.
    """
    h = checkin.HourSignal.from_api(_hour(
        source="Added at: /kiosk/storeCheckin/ by user 1 Updated at: /manager/hours/ by Maya"
    ))
    assert checkin.classify_hour(h) == checkin.CHECKED_IN


def test_status_for_no_hour_future_shift_is_signed_up():
    s = checkin.status_for(
        response_id="r1", user_id="u1",
        shift_end_iso="2099-01-01 00:00:00",
        hour_index={},
    )
    assert s == checkin.SIGNED_UP


def test_status_for_no_hour_past_shift_is_no_show():
    s = checkin.status_for(
        response_id="r1", user_id="u1",
        shift_end_iso="2000-01-01 00:00:00",
        hour_index={},
    )
    assert s == checkin.NO_SHOW


def test_status_for_prefers_response_match_over_user():
    """If a user has two simultaneous shifts under one need, only the
    response_id that matches the hour should be marked checked_in.
    """
    h = _hour(source="Added at: /kiosk/storeCheckin/", response_id="r_matched", user_id="u1")
    idx = checkin.build_hour_index([h])
    matched = checkin.status_for("r_matched", "u1", None, idx)
    other = checkin.status_for("r_other_simultaneous", "u1", "2099-01-01 00:00:00", idx)
    # The matched shift sees CHECKED_IN; the other shift falls back to the
    # user-id key, which is still that same hour (best-effort -- documented
    # ambiguity when response_id isn't set on the hour).
    assert matched == checkin.CHECKED_IN
    # When the hour HAS a response_id we should NOT spill to other shifts
    # via the user-id fallback. Verify the fallback key isn't populated.
    assert "u:u1" not in idx
    assert other == checkin.SIGNED_UP


def test_build_hour_index_user_fallback_when_no_response_id():
    h = _hour(source="Added at: /kiosk/storeCheckin/", response_id=None, user_id="u1")
    idx = checkin.build_hour_index([h])
    assert "u:u1" in idx
    assert idx["u:u1"].kiosk_checked_in is True
