import os
import sys
import unittest
import tempfile
import shutil
from datetime import datetime

# Add parent directory to path to import agent modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent.deduper import Deduper, load_recent_posts, save_post, is_duplicate
from agent import storage


class TestDeduper(unittest.TestCase):
    """Test the Deduper functionality with persistent storage."""

    def setUp(self):
        """Set up a temporary database for testing."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_storage.db")
        
        # Save original env var if exists
        self.original_db_path = os.environ.get("AGENT_DB_PATH")
        os.environ["AGENT_DB_PATH"] = self.db_path
        
        # Force reload storage module to use new path
        import importlib
        importlib.reload(storage)
        
        # Reset the module-level variables
        import agent.deduper as deduper_module
        deduper_module._RECENT_POSTS = []
        deduper_module._LOADED_FROM_STORAGE = False
        
        # Initialize the database
        storage.init_db()

    def tearDown(self):
        """Clean up the temporary database."""
        # Restore original env var
        if self.original_db_path is not None:
            os.environ["AGENT_DB_PATH"] = self.original_db_path
        elif "AGENT_DB_PATH" in os.environ:
            del os.environ["AGENT_DB_PATH"]
        
        # Reset module variables
        import agent.deduper as deduper_module
        deduper_module._RECENT_POSTS = []
        deduper_module._LOADED_FROM_STORAGE = False
        
        # Clean up temp directory
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
        
        # Force reload storage to reset state
        import importlib
        importlib.reload(storage)

    def test_save_and_load_posts(self):
        """Test saving and loading posts from persistent storage."""
        post1 = {
            "title": "Test Post 1",
            "body": "This is a test post about AI.",
            "seo_score": 85,
            "seo_keywords": ["AI", "testing"],
            "hashtags": ["#AI", "#Testing"]
        }
        
        # Save the post
        save_post(post1)
        
        # Reset the in-memory cache to force reload from storage
        import agent.deduper as deduper_module
        deduper_module._RECENT_POSTS = []
        deduper_module._LOADED_FROM_STORAGE = False
        
        # Load posts - should load from storage
        loaded_posts = load_recent_posts()
        
        self.assertEqual(len(loaded_posts), 1)
        self.assertEqual(loaded_posts[0]["title"], "Test Post 1")
        self.assertEqual(loaded_posts[0]["body"], post1["body"])
        self.assertIn("timestamp", loaded_posts[0])
        self.assertIn("hash", loaded_posts[0])

    def test_duplicate_detection(self):
        """Test that duplicate posts are detected correctly."""
        post1 = {
            "title": "Original Post",
            "body": "This is an original post about machine learning and neural networks.",
            "seo_score": 80,
            "seo_keywords": ["ML", "neural networks"],
            "hashtags": ["#MachineLearning", "#AI"]
        }
        
        # Save first post
        save_post(post1)
        
        # Try to save very similar post
        post2 = {
            "title": "Similar Post",
            "body": "This is an original post about machine learning and neural networks.",
            "seo_score": 82,
            "seo_keywords": ["ML", "deep learning"],
            "hashtags": ["#DeepLearning", "#AI"]
        }
        
        is_dup, similar_post = is_duplicate(post2)
        self.assertTrue(is_dup)
        self.assertIsNotNone(similar_post)
        self.assertEqual(similar_post["title"], "Original Post")

    def test_non_duplicate_detection(self):
        """Test that different posts are not marked as duplicates."""
        post1 = {
            "title": "Post about AI",
            "body": "This is a post about artificial intelligence and machine learning.",
            "seo_score": 80,
            "seo_keywords": ["AI", "ML"],
            "hashtags": ["#AI"]
        }
        
        save_post(post1)
        
        post2 = {
            "title": "Post about Climate",
            "body": "This is a completely different post about climate change and renewable energy.",
            "seo_score": 85,
            "seo_keywords": ["climate", "energy"],
            "hashtags": ["#Climate"]
        }
        
        is_dup, similar_post = is_duplicate(post2)
        self.assertFalse(is_dup)

    def test_max_history_size(self):
        """Test that history is limited to MAX_HISTORY_SIZE."""
        # Create more posts than MAX_HISTORY_SIZE (30)
        for i in range(35):
            post = {
                "title": f"Test Post {i}",
                "body": f"This is test post number {i} with unique content about topic {i}.",
                "seo_score": 80 + i % 10,
                "seo_keywords": [f"keyword{i}"],
                "hashtags": [f"#Test{i}"]
            }
            save_post(post)
        
        # Load posts
        loaded_posts = load_recent_posts()
        
        # Should only keep the most recent 30
        self.assertEqual(len(loaded_posts), 30)
        
        # The most recent post should be "Test Post 34"
        self.assertEqual(loaded_posts[0]["title"], "Test Post 34")


if __name__ == "__main__":
    unittest.main()
