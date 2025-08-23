import yaml, datetime as dt, json, os

STATE_PATH = "agent/state.json"
STRUCTURED_LOGS = "structured_logs.json"


def _load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    return {"next_post_time": None}


def _save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def _append_structured_log(event: str, data: dict):
    entry = {"timestamp": dt.datetime.now().isoformat(), "event": event, **(data or {})}
    try:
        if os.path.exists(STRUCTURED_LOGS):
            with open(STRUCTURED_LOGS, "r", encoding="utf-8") as f:
                logs = json.load(f)
        else:
            logs = []
    except Exception:
        logs = []
    logs.append(entry)
    with open(STRUCTURED_LOGS, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2)


def should_post_now(force=False):
    if force:
        return True
    try:
        state = _load_state()
        npt = state.get("next_post_time")
        if not npt:
            return True
        next_post_time = dt.datetime.fromisoformat(npt)
        return dt.datetime.now() >= next_post_time
    except Exception as e:
        print(f"Error checking post time: {e}")
        return False


def update_next_post_time():
    """Increment next post time by configured increment and persist to state + logs.
    Returns ISO timestamp string of the next post time.
    """
    cfg = yaml.safe_load(open("agent/config.yaml"))
    inc = int(cfg["posting"].get("time_increment", 30))

    state = _load_state()
    now = dt.datetime.now()

    # Determine base time: if we have a previous next_post_time in the past, start from now; else from previous
    prev_iso = state.get("next_post_time")
    if prev_iso:
        try:
            base = dt.datetime.fromisoformat(prev_iso)
        except Exception:
            base = now
    else:
        # Use today's configured start_time as initial base
        try:
            start_str = cfg["posting"]["start_time"]
            base = now.replace(hour=int(start_str.split(":")[0]), minute=int(start_str.split(":")[1]), second=0, microsecond=0)
        except Exception:
            base = now

    # If base is in the past, move to now
    if base < now:
        base = now

    next_time = base + dt.timedelta(minutes=inc)
    state["next_post_time"] = next_time.isoformat()
    _save_state(state)

    _append_structured_log("schedule_update", {"next_post_time": state["next_post_time"]})
    return state["next_post_time"]
