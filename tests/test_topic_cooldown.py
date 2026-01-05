import os
import sys
import unittest
from datetime import datetime, timedelta

# Add parent directory to path to import agent modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent.content_strategy import is_topic_cooldown, save_topic_history, load_topic_history
import json
import tempfile


class TestTopicCooldown(unittest.TestCase):
    """Test the topic cooldown functionality."""

    def setUp(self):
        """Set up a temporary topic history file."""
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".json")
        self.temp_file.close()
        
        # Patch the TOPIC_HISTORY_PATH
        import agent.content_strategy as cs
        self.original_path = cs.TOPIC_HISTORY_PATH
        cs.TOPIC_HISTORY_PATH = self.temp_file.name

    def tearDown(self):
        """Clean up the temporary file."""
        import agent.content_strategy as cs
        cs.TOPIC_HISTORY_PATH = self.original_path
        
        if os.path.exists(self.temp_file.name):
            os.unlink(self.temp_file.name)

    def test_topic_cooldown_default_period(self):
        """Test that topics are on cooldown for default 14 days."""
        # Save a topic
        topic = "AI for Drug Discovery"
        save_topic_history(topic)
        
        # Should be on cooldown now
        self.assertTrue(is_topic_cooldown(topic))
        
        # Load history and modify timestamp to be 10 days ago
        history = load_topic_history()
        old_time = (datetime.now() - timedelta(days=10)).isoformat()
        history[0]["timestamp"] = old_time
        with open(self.temp_file.name, 'w') as f:
            json.dump(history, f)
        
        # Should still be on cooldown (within 14 days)
        self.assertTrue(is_topic_cooldown(topic))
        
        # Modify to be 15 days ago
        old_time = (datetime.now() - timedelta(days=15)).isoformat()
        history[0]["timestamp"] = old_time
        with open(self.temp_file.name, 'w') as f:
            json.dump(history, f)
        
        # Should no longer be on cooldown
        self.assertFalse(is_topic_cooldown(topic))

    def test_topic_cooldown_custom_period(self):
        """Test topic cooldown with custom period."""
        topic = "Computer Vision"
        save_topic_history(topic)
        
        # Should be on cooldown for 5 days
        self.assertTrue(is_topic_cooldown(topic, days=5))
        
        # Modify to be 6 days ago
        history = load_topic_history()
        old_time = (datetime.now() - timedelta(days=6)).isoformat()
        history[0]["timestamp"] = old_time
        with open(self.temp_file.name, 'w') as f:
            json.dump(history, f)
        
        # Should no longer be on cooldown for 5 days
        self.assertFalse(is_topic_cooldown(topic, days=5))

    def test_multiple_topics_history(self):
        """Test tracking multiple topics in history."""
        topics = ["AI Ethics", "Neural Networks", "Reinforcement Learning"]
        
        for topic in topics:
            save_topic_history(topic)
        
        history = load_topic_history()
        self.assertEqual(len(history), 3)
        
        # All should be on cooldown
        for topic in topics:
            self.assertTrue(is_topic_cooldown(topic))

    def test_history_size_limit(self):
        """Test that history is limited to 100 topics."""
        # Save 105 topics
        for i in range(105):
            save_topic_history(f"Topic {i}")
        
        history = load_topic_history()
        
        # Should only keep the last 100
        self.assertEqual(len(history), 100)
        
        # The first topic should be "Topic 5" (last 100 of 105)
        self.assertEqual(history[0]["topic"], "Topic 5")
        
        # The last topic should be "Topic 104"
        self.assertEqual(history[-1]["topic"], "Topic 104")


if __name__ == "__main__":
    unittest.main()
