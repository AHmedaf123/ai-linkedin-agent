import os
import sys
import unittest
import json
import tempfile
from datetime import datetime

# Add parent directory to path to import agent modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent.metrics import MetricsTracker, get_metrics_tracker


class TestMetricsTracker(unittest.TestCase):
    """Test the MetricsTracker functionality."""

    def setUp(self):
        """Set up a temporary metrics file for testing."""
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        self.temp_file.close()
        self.metrics = MetricsTracker(self.temp_file.name)

    def tearDown(self):
        """Clean up the temporary metrics file."""
        if os.path.exists(self.temp_file.name):
            os.unlink(self.temp_file.name)

    def test_record_event(self):
        """Test recording events."""
        self.metrics.record_event("test_event")
        self.metrics.record_event("test_event_with_data", {"key": "value"})
        self.metrics.save()

        # Load the metrics file and check the events
        with open(self.temp_file.name, "r") as f:
            data = json.load(f)

        self.assertEqual(len(data["events"]), 2)
        self.assertEqual(data["events"][0]["event"], "test_event")
        self.assertEqual(data["events"][1]["event"], "test_event_with_data")
        self.assertEqual(data["events"][1]["data"]["key"], "value")

    def test_start_stop_timer(self):
        """Test timer functionality."""
        self.metrics.start_timer("test_timer")
        duration = self.metrics.stop_timer("test_timer")
        self.assertGreater(duration, 0)

        self.metrics.save()

        # Load the metrics file and check the timer
        with open(self.temp_file.name, "r") as f:
            data = json.load(f)

        self.assertEqual(len(data["timers"]["test_timer"]), 1)
        self.assertGreater(data["timers"]["test_timer"][0], 0)

    def test_increment_counter(self):
        """Test counter functionality."""
        self.metrics.increment_counter("test_counter")
        self.metrics.increment_counter("test_counter")
        self.metrics.increment_counter("test_counter")
        self.metrics.save()

        # Load the metrics file and check the counter
        with open(self.temp_file.name, "r") as f:
            data = json.load(f)

        self.assertEqual(data["counters"]["test_counter"], 3)

    def test_set_gauge(self):
        """Test gauge functionality."""
        self.metrics.set_gauge("test_gauge", 42)
        self.metrics.set_gauge("test_gauge", 84)
        self.metrics.save()

        # Load the metrics file and check the gauge
        with open(self.temp_file.name, "r") as f:
            data = json.load(f)

        self.assertEqual(data["gauges"]["test_gauge"], 84)

    def test_get_statistics(self):
        """Test getting statistics from metrics."""
        # Record some test data
        self.metrics.record_event("test_event")
        self.metrics.start_timer("test_timer")
        self.metrics.stop_timer("test_timer")
        self.metrics.increment_counter("test_counter")
        self.metrics.set_gauge("test_gauge", 42)

        # Get statistics
        stats = self.metrics.get_statistics()

        # Check the statistics
        self.assertEqual(stats["event_count"], 1)
        self.assertEqual(stats["timer_count"], 1)
        self.assertEqual(stats["counter_count"], 1)
        self.assertEqual(stats["gauge_count"], 1)
        self.assertEqual(stats["counters"]["test_counter"], 1)
        self.assertEqual(stats["gauges"]["test_gauge"], 42)

    def test_get_metrics_tracker(self):
        """Test the get_metrics_tracker function."""
        # Get a metrics tracker with the singleton pattern
        metrics1 = get_metrics_tracker(self.temp_file.name)
        metrics2 = get_metrics_tracker(self.temp_file.name)

        # Both should be the same instance
        self.assertIs(metrics1, metrics2)

        # Record an event and check that it's in both instances
        metrics1.record_event("singleton_test")
        metrics1.save()

        # Load the metrics file and check the event
        with open(self.temp_file.name, "r") as f:
            data = json.load(f)

        self.assertEqual(data["events"][0]["event"], "singleton_test")


if __name__ == "__main__":
    unittest.main()