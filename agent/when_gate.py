"""Posting-time gate with candidate-slot rotation.

Config (agent/config.yaml → posting):
  start_time:       "11:00"            fallback slot
  candidate_times:  ["11:00", ...]     optional; slots rotate by day so different
                                       posting times can be A/B tested (posted_at
                                       is stored per post, so performance per slot
                                       can be compared later)
  time_window_end:  120                minutes the window stays open after the slot
  timezone:         "Asia/Karachi"

State lives in the SQLite store (survives CI runs via the committed DB) and is
mirrored to agent/state.json for easy inspection.
"""

import yaml
import datetime as dt
import json
import os

import pytz

from agent import storage

STATE_FILE = "agent/state.json"
CONFIG_PATH = "agent/config.yaml"

LAST_POSTED_KEY = "last_posted_date"
NEXT_POST_KEY = "next_post_time"


def _load_posting_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return cfg.get("posting", {})


def _get_timezone(posting_cfg: dict):
    return pytz.timezone(posting_cfg.get("timezone", "Asia/Karachi"))


def _candidate_times(posting_cfg: dict) -> list:
    times = posting_cfg.get("candidate_times")
    if isinstance(times, list) and times:
        return [str(t) for t in times]
    return [str(posting_cfg.get("start_time", "11:00"))]


def parse_time_with_timezone(time_str, timezone, day=None):
    """Parse HH:MM into a timezone-aware datetime for the given day (default today)."""
    hours, minutes = map(int, str(time_str).split(":"))
    now = dt.datetime.now(timezone)
    day = day or now.date()
    return timezone.localize(dt.datetime(day.year, day.month, day.day, hours, minutes))


def get_slot_for_day(day: dt.date, posting_cfg: dict = None) -> str:
    """Deterministic slot for a calendar day: rotates through candidate_times."""
    posting_cfg = posting_cfg or _load_posting_config()
    times = _candidate_times(posting_cfg)
    return times[day.timetuple().tm_yday % len(times)]


def _write_state_mirror(state: dict) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"Warning: could not write {STATE_FILE}: {e}")


def should_post_now(force: bool = False) -> bool:
    """True when inside today's posting window and nothing was posted today yet."""
    if force:
        return True
    try:
        posting_cfg = _load_posting_config()
        timezone = _get_timezone(posting_cfg)
        now = dt.datetime.now(timezone)
        today = now.date()

        last_posted = storage.get_state(LAST_POSTED_KEY)
        if last_posted == today.isoformat():
            return False  # already posted today

        slot = parse_time_with_timezone(get_slot_for_day(today, posting_cfg), timezone, today)
        window_minutes = int(posting_cfg.get("time_window_end", 120))
        window_end = slot + dt.timedelta(minutes=window_minutes)

        return slot <= now <= window_end
    except Exception as e:
        print(f"Error in should_post_now: {e}")
        # Default to False on error to prevent unintended posts
        return False


def update_next_post_time():
    """Record that today's post happened; schedule tomorrow's slot.

    Returns the next post time as an ISO 8601 string (or None on error).
    """
    try:
        posting_cfg = _load_posting_config()
        timezone = _get_timezone(posting_cfg)
        now = dt.datetime.now(timezone)
        today = now.date()
        tomorrow = today + dt.timedelta(days=1)

        next_time = parse_time_with_timezone(get_slot_for_day(tomorrow, posting_cfg), timezone, tomorrow)

        storage.set_state(LAST_POSTED_KEY, today.isoformat())
        storage.set_state(NEXT_POST_KEY, next_time.isoformat())
        _write_state_mirror({
            LAST_POSTED_KEY: today.isoformat(),
            NEXT_POST_KEY: next_time.isoformat(),
        })
        return next_time.isoformat()
    except Exception as e:
        print(f"Error in update_next_post_time: {e}")
        return None


if __name__ == "__main__":
    print(f"Today's slot: {get_slot_for_day(dt.date.today())}")
    print(f"Should post now: {should_post_now()}")
