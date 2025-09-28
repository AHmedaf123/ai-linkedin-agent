import json
import os
import time
from datetime import datetime
from typing import Dict, List, Any, Optional


class MetricsTracker:
    """Track and store performance and operational metrics for the LinkedIn agent"""
    
    def __init__(self, metrics_file: str = "metrics.json"):
        """Initialize the metrics tracker
        
        Args:
            metrics_file: Path to the metrics JSON file
        """
        import os.path
        # Sanitize metrics file path to prevent path traversal
        self.metrics_file = os.path.basename(metrics_file)
        self.current_run: Dict[str, Any] = {
            "run_id": datetime.now().strftime("%Y%m%d%H%M%S"),
            "timestamp": datetime.now().isoformat(),
            "events": [],
            "timers": {},
            "counters": {},
            "gauges": {}
        }
        self._active_timers: Dict[str, float] = {}
        
        # Load existing metrics if file exists
        self.history: List[Dict[str, Any]] = []
        if os.path.exists(self.metrics_file):
            try:
                with open(self.metrics_file, "r") as f:
                    self.history = json.load(f)
            except (json.JSONDecodeError, IOError):
                # Start with empty history if file is invalid
                self.history = []
    
    def record_event(self, event_type: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Record an event with optional metadata
        
        Args:
            event_type: Type of event (e.g., "post_generated", "linkedin_post_success")
            metadata: Optional dictionary with additional event data
        """
        event = {
            "type": event_type,
            "timestamp": datetime.now().isoformat()
        }
        
        if metadata:
            event["metadata"] = metadata
            
        self.current_run["events"].append(event)
    
    def start_timer(self, timer_name: str) -> None:
        """Start a timer for measuring operation duration
        
        Args:
            timer_name: Name of the timer
        """
        self._active_timers[timer_name] = time.time()
    
    def stop_timer(self, timer_name: str) -> float:
        """Stop a timer and record the duration
        
        Args:
            timer_name: Name of the timer to stop
            
        Returns:
            Duration in seconds
            
        Raises:
            KeyError: If timer_name is not an active timer
        """
        if timer_name not in self._active_timers:
            raise KeyError(f"Timer '{timer_name}' not started")
        
        duration = time.time() - self._active_timers[timer_name]
        self.current_run["timers"][timer_name] = duration
        del self._active_timers[timer_name]
        return duration
    
    def increment_counter(self, counter_name: str, increment: int = 1) -> int:
        """Increment a counter
        
        Args:
            counter_name: Name of the counter
            increment: Amount to increment by (default: 1)
            
        Returns:
            New counter value
        """
        current_value = self.current_run["counters"].get(counter_name, 0)
        new_value = current_value + increment
        self.current_run["counters"][counter_name] = new_value
        return new_value
    
    def set_gauge(self, gauge_name: str, value: Any) -> None:
        """Set a gauge value (point-in-time measurement)
        
        Args:
            gauge_name: Name of the gauge
            value: Value to set
        """
        self.current_run["gauges"][gauge_name] = value
    
    def save(self) -> None:
        """Save the current metrics to the metrics file"""
        # Add any still-running timers with a warning
        for timer_name, start_time in self._active_timers.items():
            duration = time.time() - start_time
            self.current_run["timers"][f"{timer_name}_incomplete"] = duration
        
        # Add current run to history
        self.history.append(self.current_run)
        
        # Save to file
        try:
            with open(self.metrics_file, "w") as f:
                json.dump(self.history, f, indent=2)
        except IOError as e:
            # Log error but don't crash
            print(f"Error saving metrics: {str(e)}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics from the current run
        
        Returns:
            Dictionary with statistics
        """
        return {
            "run_id": self.current_run["run_id"],
            "event_count": len(self.current_run["events"]),
            "timers": self.current_run["timers"].copy(),
            "counters": self.current_run["counters"].copy(),
            "gauges": self.current_run["gauges"].copy()
        }


# Singleton instance for global use
_metrics_tracker = None


def get_metrics_tracker(metrics_file: str = "metrics.json") -> MetricsTracker:
    """Get the global metrics tracker instance
    
    Args:
        metrics_file: Path to the metrics JSON file
        
    Returns:
        MetricsTracker instance
    """
    global _metrics_tracker
    if _metrics_tracker is None:
        _metrics_tracker = MetricsTracker(metrics_file)
    return _metrics_tracker