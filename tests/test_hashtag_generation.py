import os
import sys
import unittest

# Add parent directory to path to import agent modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agent.llm_generator import LLMGenerator
from agent import ensure_hashtags_in_content


class TestHashtagGeneration(unittest.TestCase):
    """Test the hashtag generation and fallback functionality."""

    def test_ensure_hashtags_in_content_appends_when_missing(self):
        """Test that ensure_hashtags_in_content appends hashtags when not present."""
        content = "This is a post about AI."
        hashtags = ["#AI", "#MachineLearning"]
        
        result = ensure_hashtags_in_content(content, hashtags)
        
        self.assertIn("#AI", result)
        self.assertIn("#MachineLearning", result)
        self.assertTrue(result.startswith("This is a post about AI."))

    def test_ensure_hashtags_in_content_does_not_duplicate(self):
        """Test that hashtags are not duplicated if already present."""
        content = "This is a post about AI.\n\n#AI #MachineLearning"
        hashtags = ["#AI", "#MachineLearning"]
        
        result = ensure_hashtags_in_content(content, hashtags)
        
        # Should not append again
        self.assertEqual(result, content)
        # Count occurrences - should only appear once
        self.assertEqual(result.count("#AI"), 1)
        self.assertEqual(result.count("#MachineLearning"), 1)

    def test_ensure_hashtags_in_content_with_empty_list(self):
        """Test that content is unchanged when hashtags list is empty."""
        content = "This is a post."
        hashtags = []
        
        result = ensure_hashtags_in_content(content, hashtags)
        
        self.assertEqual(result, content)

    def test_generate_fallback_hashtags_with_ai_content(self):
        """Test fallback hashtag generation for AI content."""
        text = "This is a post about deep learning and neural networks in artificial intelligence."
        topic = "Deep Learning"
        
        hashtags = LLMGenerator._generate_fallback_hashtags(text, topic)
        
        # Should have 3-5 hashtags
        self.assertGreaterEqual(len(hashtags), 3)
        self.assertLessEqual(len(hashtags), 5)
        
        # Should contain relevant AI hashtags
        hashtag_strings = [h.lower() for h in hashtags]
        self.assertTrue(any("deep" in h for h in hashtag_strings) or 
                       any("neural" in h for h in hashtag_strings) or
                       any("ai" in h for h in hashtag_strings))

    def test_generate_fallback_hashtags_with_medical_content(self):
        """Test fallback hashtag generation for medical/drug discovery content."""
        text = "Researchers are using AI for drug discovery and protein folding."
        topic = "AI in Medicine"
        
        hashtags = LLMGenerator._generate_fallback_hashtags(text, topic)
        
        # Should have 3-5 hashtags
        self.assertGreaterEqual(len(hashtags), 3)
        self.assertLessEqual(len(hashtags), 5)
        
        # Should contain relevant medical/drug hashtags
        hashtag_strings = [h.lower() for h in hashtags]
        self.assertTrue(any("drug" in h or "protein" in h or "medicine" in h 
                           for h in hashtag_strings))

    def test_generate_fallback_hashtags_minimal_content(self):
        """Test fallback hashtag generation with minimal content."""
        text = "AI is amazing."
        topic = ""
        
        hashtags = LLMGenerator._generate_fallback_hashtags(text, topic)
        
        # Should still generate at least 3 hashtags
        self.assertGreaterEqual(len(hashtags), 3)
        
        # Should contain base AI hashtags
        hashtag_strings = [h.lower() for h in hashtags]
        self.assertTrue(any("ai" in h or "machinelearning" in h 
                           for h in hashtag_strings))

    def test_postprocess_content_extracts_hashtags(self):
        """Test that _postprocess_content extracts hashtags from text."""
        text = """This is a great post about AI and machine learning.

It covers important topics in the field.

#AI #MachineLearning #DeepLearning"""
        
        title, body, hashtags = LLMGenerator._postprocess_content(text, "AI")
        
        # Should extract hashtags
        self.assertEqual(len(hashtags), 3)
        self.assertIn("#AI", hashtags)
        self.assertIn("#MachineLearning", hashtags)
        self.assertIn("#DeepLearning", hashtags)
        
        # Body should not contain hashtags
        self.assertNotIn("#AI", body)
        self.assertNotIn("#MachineLearning", body)

    def test_postprocess_content_generates_fallback_hashtags(self):
        """Test that _postprocess_content generates fallback hashtags when none are present."""
        text = """This is a post about artificial intelligence and neural networks.

It discusses recent breakthroughs in deep learning."""
        
        title, body, hashtags = LLMGenerator._postprocess_content(text, "AI")
        
        # Should generate at least 3 fallback hashtags
        self.assertGreaterEqual(len(hashtags), 3)
        
        # Body should remain unchanged (no hashtags to remove)
        self.assertIn("artificial intelligence", body)
        self.assertIn("neural networks", body)

    def test_postprocess_content_with_partial_hashtags(self):
        """Test that fallback hashtags are added when only 1-2 hashtags are present."""
        text = """This is a post about machine learning.

#MachineLearning"""
        
        title, body, hashtags = LLMGenerator._postprocess_content(text, "AI")
        
        # Should have at least 3 hashtags (1 original + 2+ fallback)
        self.assertGreaterEqual(len(hashtags), 3)
        self.assertIn("#MachineLearning", hashtags)


if __name__ == "__main__":
    unittest.main()
