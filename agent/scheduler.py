import os
import json
import datetime as dt
import yaml
from typing import Any, Dict

STATE_PATH = "agent/state.json"
STRUCTURED_LOGS = "structured_logs.json"

class Scheduler:
    @staticmethod
    def _load_state() -> Dict[str, Any]:
        # In-memory only: do not persist scheduler state to disk
        return {"next_post_time": None}

    @staticmethod
    def _save_state(state: Dict[str, Any]) -> None:
        # No-op: avoid writing state to disk
        return

    @staticmethod
    def _append_log(event: str, data: Dict[str, Any] | None = None) -> None:
        # No-op structured logs to avoid writing files
        return

    @staticmethod
    def should_post_now(force: bool = False) -> bool:
        if force:
            return True
        try:
            state = Scheduler._load_state()
            npt = state.get("next_post_time")
            if not npt:
                return True
            return dt.datetime.now() >= dt.datetime.fromisoformat(npt)
        except Exception:
            return False

    @staticmethod
    def update_next_post_time() -> str:
        cfg = yaml.safe_load(open("agent/config.yaml", encoding="utf-8"))
        inc = int(cfg["posting"].get("time_increment", 30))
        state = Scheduler._load_state()
        now = dt.datetime.now()
        prev_iso = state.get("next_post_time")
        if prev_iso:
            try:
                base = dt.datetime.fromisoformat(prev_iso)
            except Exception:
                base = now
        else:
            try:
                start_str = cfg["posting"]["start_time"]
                hh, mm = map(int, start_str.split(":"))
                base = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            except Exception:
                base = now
        if base < now:
            base = now
        next_time = base + dt.timedelta(minutes=inc)
        state["next_post_time"] = next_time.isoformat()
        Scheduler._save_state(state)
        Scheduler._append_log("schedule_update", {"next_post_time": state["next_post_time"]})
        return state["next_post_time"]

# Public API facades

def should_post_now(force: bool = False) -> bool:
    return Scheduler.should_post_now(force=force)

def update_next_post_time() -> str:
    return Scheduler.update_next_post_time()