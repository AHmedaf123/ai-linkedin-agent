#!/usr/bin/env python3
"""
Test script for AI LinkedIn Agent
Validates core functionality without posting to LinkedIn
"""

import os
import sys
import json
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Test that all modules can be imported"""
    print("Testing imports...")
    try:
        from agent.content_strategy import get_next_content_strategy
        from agent.topic_picker import get_niche_post
        from agent.seo_optimizer import optimize_post
        from agent.logging_setup import setup_logging
        from agent.metrics import get_metrics_tracker
        print("All imports successful")
        return True
    except ImportError as e:
        print(f"Import failed: {e}")
        return False

def test_content_generation():
    """Test content generation functionality"""
    print("Testing content generation...")
    try:
        from agent.topic_picker import get_niche_post
        
        # Test niche post generation
        post = get_niche_post(topic="Artificial Intelligence")
        
        if not post:
            print("Content generation returned None")
            return False
        
        required_fields = ['title', 'body', 'seo_score', 'hashtags']
        for field in required_fields:
            if field not in post:
                print(f"Missing required field: {field}")
                return False
        
        if len(post['body']) < 50:
            print("Generated content too short")
            return False
        
        print(f"Content generated successfully ({len(post['body'])} chars)")
        print(f"   Title: {post['title'][:50]}...")
        print(f"   SEO Score: {post['seo_score']}")
        print(f"   Hashtags: {len(post['hashtags'])}")
        return True
        
    except Exception as e:
        print(f"Content generation failed: {e}")
        return False

def test_config_loading():
    """Test configuration loading"""
    print("Testing configuration loading...")
    try:
        from agent.content_strategy import load_config, load_calendar
        
        config = load_config()
        if not isinstance(config, dict):
            print("Config loading failed")
            return False
        
        calendar = load_calendar()
        if not isinstance(calendar, dict):
            print("Calendar loading failed")
            return False
        
        print("Configuration loading successful")
        return True
        
    except Exception as e:
        print(f"Configuration loading failed: {e}")
        return False

def test_metrics():
    """Test metrics functionality"""
    print("Testing metrics...")
    try:
        from agent.metrics import get_metrics_tracker
        
        metrics = get_metrics_tracker("test_metrics.json")
        
        # Test basic operations
        metrics.record_event("test_event", {"test": "data"})
        metrics.start_timer("test_timer")
        metrics.increment_counter("test_counter")
        metrics.set_gauge("test_gauge", 42)
        
        # Stop timer
        import time
        time.sleep(0.1)
        duration = metrics.stop_timer("test_timer")
        
        if duration <= 0:
            print("Timer functionality failed")
            return False
        
        # Get stats
        stats = metrics.get_stats()
        if not isinstance(stats, dict):
            print("Stats retrieval failed")
            return False
        
        # Save metrics
        metrics.save()
        
        # Clean up test file
        if Path("test_metrics.json").exists():
            Path("test_metrics.json").unlink()
        
        print("Metrics functionality working")
        return True
        
    except Exception as e:
        print(f"Metrics test failed: {e}")
        return False

def test_seo_optimizer():
    """Test SEO optimization"""
    print("Testing SEO optimizer...")
    try:
        from agent.seo_optimizer import optimize_post
        
        test_content = "This is a test post about artificial intelligence and machine learning."
        score, keywords = optimize_post(test_content)
        
        if not isinstance(score, (int, float)) or score < 0:
            print("SEO score invalid")
            return False
        
        if not isinstance(keywords, list):
            print("SEO keywords invalid")
            return False
        
        print(f"SEO optimization working (score: {score}, keywords: {len(keywords)})")
        return True
        
    except Exception as e:
        print(f"SEO optimizer test failed: {e}")
        return False

def main():
    """Run all tests"""
    print("AI LinkedIn Agent Test Suite")
    print("=" * 40)
    
    tests = [
        ("Module Imports", test_imports),
        ("Configuration Loading", test_config_loading),
        ("Content Generation", test_content_generation),
        ("Metrics System", test_metrics),
        ("SEO Optimizer", test_seo_optimizer),
    ]
    
    passed = 0
    total = len(tests)
    
    for name, test_func in tests:
        print(f"\n{name}")
        print("-" * 30)
        try:
            if test_func():
                passed += 1
            else:
                print(f"{name} failed")
        except Exception as e:
            print(f"{name} error: {str(e)}")
    
    print("\n" + "=" * 40)
    print(f"Test Results: {passed}/{total} passed")
    
    if passed == total:
        print("All tests passed! Agent is ready to use.")
        return 0
    else:
        print("Some tests failed. Please check the issues above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
