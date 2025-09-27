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
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"next_post_time": None}

    @staticmethod
    def _save_state(state: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

    @staticmethod
    def _append_log(event: str, data: Dict[str, Any] | None = None) -> None:
        entry = {"timestamp": dt.datetime.now().isoformat(), "event": event, **(data or {})}
        try:
            logs = []
            if os.path.exists(STRUCTURED_LOGS):
                with open(STRUCTURED_LOGS, "r", encoding="utf-8") as f:
                    logs = json.load(f) or []
        except Exception:
            logs = []
        logs.append(entry)
        with open(STRUCTURED_LOGS, "w", encoding="utf-8") as f:
            json.dump(logs, f, indent=2)

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