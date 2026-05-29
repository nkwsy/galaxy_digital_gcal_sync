"""Volunteer check-in status derivation for Galaxy Digital.

The Galaxy Digital API doesn't expose check-in state as a clean flag:
- `hour_status` reflects manager-approval flow (pending/approved/denied),
  not whether the volunteer is currently at the kiosk.
- `hour_date_end` is always populated from the shift's scheduled end, so it
  is NOT a checkout signal.
- The only reliable signal is `hour_source`, a free-text audit log that
  contains substrings like `/kiosk/storeCheckin/` and `/kiosk/storeCheckout/`
  when the kiosk actions fire.

This module turns hours + responses into a clean status enum.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import pytz

CHICAGO = pytz.timezone("America/Chicago")

# Status values surfaced to gcal / digest / webpage.
SIGNED_UP = "signed_up"          # response exists, no hour row yet
CHECKED_IN = "checked_in"        # at the kiosk, not checked out yet
CHECKED_OUT = "checked_out"      # full kiosk flow completed
MANAGER_ENTERED = "manager_entered"  # hours added by a manager; treat as completed
NO_SHOW = "no_show"              # signup active, no hour, shift end past
CANCELLED = "cancelled"          # volunteer un-registered before the shift

# Statuses that should NOT count toward "X / N filled" -- a cancellation
# frees up the slot, a manual no-show does not.
FILLED_STATUSES = (CHECKED_IN, CHECKED_OUT, MANAGER_ENTERED, SIGNED_UP, NO_SHOW)

STATUS_EMOJI = {
    SIGNED_UP:       "🔘",
    CHECKED_IN:      "🟡",    # at the kiosk, not yet checked out
    CHECKED_OUT:     "🟢",    # full kiosk flow complete
    MANAGER_ENTERED: "🟣",
    NO_SHOW:         "🔴",
    CANCELLED:       "⚪",    # registered, then un-registered; doesn't count as no-show
}


@dataclass
class HourSignal:
    """Minimal projection of an /hours row used for status derivation."""

    response_id: str | None
    user_id: str | None
    source: str
    status: str  # raw hour_status
    date_start: str | None
    date_end: str | None

    @classmethod
    def from_api(cls, row: dict) -> "HourSignal":
        return cls(
            response_id=str(row["hour_response_id"]) if row.get("hour_response_id") else None,
            user_id=str(row.get("user", {}).get("id")) if row.get("user") else None,
            source=(row.get("hour_source") or ""),
            status=(row.get("hour_status") or ""),
            date_start=row.get("hour_date_start"),
            date_end=row.get("hour_date_end"),
        )

    @property
    def kiosk_checked_in(self) -> bool:
        return "/kiosk/storecheckin/" in self.source.lower()

    @property
    def kiosk_checked_out(self) -> bool:
        return "/kiosk/storecheckout/" in self.source.lower()

    @property
    def manager_entered(self) -> bool:
        s = self.source.lower()
        return "/manager/" in s and not self.kiosk_checked_in


def classify_hour(h: HourSignal) -> str:
    """Map one hour record to a status. Returns CHECKED_IN/OUT or MANAGER_ENTERED."""
    if h.kiosk_checked_out:
        return CHECKED_OUT
    if h.kiosk_checked_in:
        return CHECKED_IN
    if h.manager_entered:
        return MANAGER_ENTERED
    # Hours present but no recognizable source -- treat as completed since the
    # row exists at all, but flag with manager_entered so it's visible.
    return MANAGER_ENTERED


def build_hour_index(hours: Iterable[dict]) -> dict[str, HourSignal]:
    """Map response_id -> HourSignal. When response_id is missing (rare ~3%),
    fall back to user_id so the volunteer still shows as present, with the
    caveat that two same-day same-need shifts for one user become ambiguous.

    Returns a dict keyed by `r:<response_id>` or `u:<user_id>`. Lookups should
    try the response key first.
    """
    idx: dict[str, HourSignal] = {}
    for row in hours:
        h = HourSignal.from_api(row)
        if h.response_id:
            idx[f"r:{h.response_id}"] = h
        elif h.user_id:
            idx.setdefault(f"u:{h.user_id}", h)
    return idx


def status_for(response_id: str, user_id: str, shift_end_iso: str | None,
               hour_index: dict[str, HourSignal], now: datetime | None = None) -> str:
    """Resolve status for a single (response, user) row at the current time."""
    h = hour_index.get(f"r:{response_id}") or hour_index.get(f"u:{user_id}")
    if h is not None:
        return classify_hour(h)
    # No hour row. Decide between SIGNED_UP and NO_SHOW based on shift end.
    if shift_end_iso:
        try:
            end = datetime.strptime(shift_end_iso, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return SIGNED_UP
        end = CHICAGO.localize(end) if end.tzinfo is None else end
        current = now or datetime.now(CHICAGO)
        if current > end:
            return NO_SHOW
    return SIGNED_UP
