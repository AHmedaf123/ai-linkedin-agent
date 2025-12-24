import os
import sys
import unittest
import tempfile
import shutil
from datetime import datetime

# Add parent directory to path to import agent modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


class TestDeduper(unittest.TestCase):
    """Test the Deduper functionality with persistent storage."""

    def setUp(self):
        """Set up a temporary database for testing."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_agent_storage.db")
        os.environ["AGENT_DB_PATH"] = self.db_path
        
        # Import after setting the environment variable
        from agent import deduper
        from agent import storage
        
        # Reload modules to pick up new DB_PATH
        import importlib
        importlib.reload(storage)
        importlib.reload(deduper)
        
        self.deduper = deduper

    def tearDown(self):
        """Clean up the temporary database."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
        if "AGENT_DB_PATH" in os.environ:
            del os.environ["AGENT_DB_PATH"]

    def test_save_and_load_posts(self):
        """Test that posts are saved and loaded from persistent storage."""
        # Create a test post
        test_post = {
            "title": "Test Post",
            "body": "This is a test post about AI and machine learning.",
            "seo_score": 85,
            "seo_keywords": ["AI", "machine learning"],
            "hashtags": ["#AI", "#MachineLearning"]
        }
        
        # Save the post
        self.deduper.save_post(test_post)
        
        # Load recent posts
        recent_posts = self.deduper.load_recent_posts()
        
        # Verify the post was saved
        self.assertEqual(len(recent_posts), 1)
        self.assertEqual(recent_posts[0]["title"], "Test Post")
        self.assertEqual(recent_posts[0]["body"], test_post["body"])
        self.assertIn("hash", recent_posts[0])
        self.assertIn("timestamp", recent_posts[0])

    def test_duplicate_detection(self):
        """Test that duplicate posts are detected."""
        # Create a test post
        test_post = {
            "title": "Original Post",
            "body": "This is an original post about quantum computing and AI.",
            "seo_score": 80,
            "seo_keywords": ["quantum", "AI"],
            "hashtags": ["#QuantumComputing", "#AI"]
        }
        
        # Save the post
        self.deduper.save_post(test_post)
        
        # Try to check if the same post is a duplicate
        is_dup, similar_post = self.deduper.is_duplicate(test_post)
        
        # Should detect as duplicate
        self.assertTrue(is_dup)
        self.assertIsNotNone(similar_post)

    def test_similarity_calculation(self):
        """Test similarity calculation between posts."""
        # Create two similar posts
        post1 = {
            "title": "Post 1",
            "body": "Deep learning models are revolutionizing natural language processing.",
            "seo_score": 80,
            "seo_keywords": ["deep learning", "NLP"],
            "hashtags": ["#DeepLearning", "#NLP"]
        }
        
        post2 = {
            "title": "Post 2",
            "body": "Machine learning algorithms are transforming computer vision tasks.",
            "seo_score": 82,
            "seo_keywords": ["machine learning", "computer vision"],
            "hashtags": ["#MachineLearning", "#ComputerVision"]
        }
        
        # Save first post
        self.deduper.save_post(post1)
        
        # Calculate similarity with second post
        recent = self.deduper.load_recent_posts()
        similarity, similar_post = self.deduper.calculate_similarity(post2["body"], recent)
        
        # Should have some similarity but not too high
        self.assertGreaterEqual(similarity, 0.0)
        self.assertLessEqual(similarity, 1.0)

    def test_persistence_across_reloads(self):
        """Test that posts persist across module reloads."""
        # Create and save a test post
        test_post = {
            "title": "Persistent Post",
            "body": "This post should persist across reloads and restarts.",
            "seo_score": 90,
            "seo_keywords": ["persistence", "database"],
            "hashtags": ["#Database", "#Persistence"]
        }
        
        # Save the post
        self.deduper.save_post(test_post)
        
        # Reload the storage and deduper modules
        from agent import storage
        from agent import deduper
        import importlib
        importlib.reload(storage)
        importlib.reload(deduper)
        
        # Load recent posts again
        recent_posts = deduper.load_recent_posts()
        
        # Verify the post still exists
        self.assertEqual(len(recent_posts), 1)
        self.assertEqual(recent_posts[0]["title"], "Persistent Post")
        self.assertEqual(recent_posts[0]["body"], test_post["body"])

    def test_max_history_size(self):
        """Test that only MAX_HISTORY_SIZE posts are returned."""
        # Create and save multiple posts
        for i in range(35):  # More than MAX_HISTORY_SIZE (30)
            test_post = {
                "title": f"Post {i}",
                "body": f"This is test post number {i} with unique content about topic {i}.",
                "seo_score": 80,
                "seo_keywords": [f"keyword{i}"],
                "hashtags": [f"#Tag{i}"]
            }
            self.deduper.save_post(test_post)
        
        # Load recent posts
        recent_posts = self.deduper.load_recent_posts()
        
        # Should only return MAX_HISTORY_SIZE posts
        self.assertLessEqual(len(recent_posts), self.deduper.MAX_HISTORY_SIZE)


if __name__ == "__main__":
    unittest.main()
