import yaml
import datetime as dt
import pytz
import json
import os

def should_post_now():
    """
    Determines if the current time falls within the posting window based on configuration.
    Returns True if we should post now, False otherwise.
    """
    try:
        # Load configuration
        with open("agent/config.yaml", "r") as f:
            cfg = yaml.safe_load(f)
        
        # Get posting configuration
        start_time_str = cfg["posting"]["start_time"]
        time_increment = cfg["posting"]["time_increment"]
        timezone_str = cfg["posting"]["timezone"]
        
        # Default end window to 2 hours if not specified
        time_window_end = cfg["posting"].get("time_window_end", 120)
        
        # Get the timezone
        timezone = pytz.timezone(timezone_str)
        
        # Get current time in the configured timezone
        now = dt.datetime.now(timezone)
        
        # Check if we have a state file with the next post time
        state_file = "agent/state.json"
        if os.path.exists(state_file):
            with open(state_file, "r") as f:
                state = json.load(f)
                next_post_time_str = state.get("next_post_time")
                if next_post_time_str:
                    next_post_time = dt.datetime.fromisoformat(next_post_time_str)
                    # Convert to timezone-aware if it's not
                    if next_post_time.tzinfo is None:
                        next_post_time = timezone.localize(next_post_time)
                else:
                    # If no next post time, use the start time from config
                    next_post_time = parse_time_with_timezone(start_time_str, timezone)
        else:
            # If no state file exists, use the start time from config
            next_post_time = parse_time_with_timezone(start_time_str, timezone)
        
        # Calculate the end of the posting window
        window_end = next_post_time + dt.timedelta(minutes=time_window_end)
        
        # Check if current time is within the posting window
        should_post = next_post_time <= now <= window_end
        
        return should_post
    
    except Exception as e:
        print(f"Error in should_post_now: {str(e)}")
        # Default to False on error to prevent unintended posts
        return False

def parse_time_with_timezone(time_str, timezone):
    """
    Parse a time string (HH:MM) and return a timezone-aware datetime for today.
    """
    hours, minutes = map(int, time_str.split(":"))
    now = dt.datetime.now(timezone)
    return timezone.localize(dt.datetime(now.year, now.month, now.day, hours, minutes))

def update_next_post_time():
    """
    Updates the next post time in the state file based on the current configuration.
    Returns the new next_post_time as an ISO 8601 string.
    """
    try:
        # Load configuration
        with open("agent/config.yaml", "r") as f:
            cfg = yaml.safe_load(f)
        
        # Get posting configuration
        start_time_str = cfg["posting"]["start_time"]
        time_increment = cfg["posting"]["time_increment"]
        timezone_str = cfg["posting"]["timezone"]
        
        # Get the timezone
        timezone = pytz.timezone(timezone_str)
        
        # Get current time in the configured timezone
        now = dt.datetime.now(timezone)
        
        # Check if we have a state file with the next post time
        state_file = "agent/state.json"
        if os.path.exists(state_file):
            with open(state_file, "r") as f:
                state = json.load(f)
                next_post_time_str = state.get("next_post_time")
                if next_post_time_str:
                    current_next_time = dt.datetime.fromisoformat(next_post_time_str)
                    # Convert to timezone-aware if it's not
                    if current_next_time.tzinfo is None:
                        current_next_time = timezone.localize(current_next_time)
                else:
                    # If no next post time, use the start time from config
                    current_next_time = parse_time_with_timezone(start_time_str, timezone)
        else:
            # If no state file exists, use the start time from config
            current_next_time = parse_time_with_timezone(start_time_str, timezone)
            state = {}
        
        # Calculate the new next post time by adding the increment
        new_next_time = current_next_time + dt.timedelta(minutes=time_increment)
        
        # If the new time is after 2 PM, reset to the start time for the next day
        if new_next_time.hour >= 14:  # 2 PM
            tomorrow = now + dt.timedelta(days=1)
            hours, minutes = map(int, start_time_str.split(":"))
            new_next_time = timezone.localize(dt.datetime(tomorrow.year, tomorrow.month, tomorrow.day, hours, minutes))
        
        # Update the state file
        state["next_post_time"] = new_next_time.isoformat()
        with open(state_file, "w") as f:
            json.dump(state, f, indent=2)
        
        return state["next_post_time"]
    
    except Exception as e:
        print(f"Error in update_next_post_time: {str(e)}")
        return None

if __name__ == "__main__":
    # For testing
    should_post = should_post_now()
    print(f"Should post now: {should_post}")
    if should_post:
        next_time = update_next_post_time()
        print(f"Next post time updated to: {next_time}")