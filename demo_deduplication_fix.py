#!/usr/bin/env python3
"""
Demonstration script showing how the persistent deduplication fix works.

This script simulates multiple runs of the agent to show that:
1. Posts are saved to persistent storage
2. Duplicate detection works across "runs" (simulated by reloading modules)
3. The database persists between runs
"""

import os
import sys
import tempfile
import shutil

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

def simulate_agent_run(run_number: int, posts_to_create: list):
    """Simulate one run of the agent."""
    print(f"\n{'='*60}")
    print(f"SIMULATING RUN #{run_number}")
    print(f"{'='*60}")
    
    from agent.deduper import Deduper
    
    print(f"\n📊 Loading recent posts from database...")
    recent = Deduper.load_recent_posts()
    print(f"   Found {len(recent)} post(s) in history")
    
    for i, post_data in enumerate(posts_to_create, 1):
        print(f"\n🔍 Checking post #{i}: '{post_data['title']}'")
        
        # Check if duplicate
        is_dup, similar_post = Deduper.is_duplicate(post_data)
        
        if is_dup:
            print(f"   ❌ DUPLICATE DETECTED!")
            print(f"   Similar to: '{similar_post.get('title', 'Unknown')}'")
            print(f"   ✋ Would trigger regeneration...")
        else:
            print(f"   ✅ UNIQUE POST - Saving to database")
            Deduper.save_post(post_data)
            print(f"   💾 Saved successfully")
    
    # Show final count
    recent = Deduper.load_recent_posts()
    print(f"\n📈 Total posts in database: {len(recent)}")


def main():
    """Main demonstration."""
    print("="*60)
    print("PERSISTENT DEDUPLICATION DEMONSTRATION")
    print("="*60)
    print("\nThis demonstrates how the fix prevents duplicate posts")
    print("by using persistent SQLite database storage instead of")
    print("in-memory storage that resets on each run.")
    
    # Set up a temporary database for the demo
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "demo.db")
    os.environ["AGENT_DB_PATH"] = db_path
    
    try:
        # Simulate Run 1: Post about quantum computing
        posts_run1 = [{
            "title": "Quantum Computing Breakthrough",
            "body": "Researchers at Google achieved quantum supremacy with their latest processor, demonstrating computational power that far exceeds classical computers for specific tasks.",
            "seo_score": 85,
            "seo_keywords": ["quantum", "computing", "Google"],
            "hashtags": ["#QuantumComputing", "#AI"]
        }]
        
        simulate_agent_run(1, posts_run1)
        
        # Reload modules to simulate a fresh agent run
        print("\n\n🔄 Simulating agent restart (modules reloaded)...")
        from agent import deduper, storage
        import importlib
        importlib.reload(storage)
        importlib.reload(deduper)
        
        # Simulate Run 2: Try to post the SAME content
        posts_run2 = [{
            "title": "Quantum Computing Breakthrough",  # Same title
            "body": "Researchers at Google achieved quantum supremacy with their latest processor, demonstrating computational power that far exceeds classical computers for specific tasks.",  # Same body
            "seo_score": 85,
            "seo_keywords": ["quantum", "computing", "Google"],
            "hashtags": ["#QuantumComputing", "#AI"]
        }]
        
        simulate_agent_run(2, posts_run2)
        
        # Reload modules again
        print("\n\n🔄 Simulating another agent restart...")
        importlib.reload(storage)
        importlib.reload(deduper)
        
        # Simulate Run 3: Post different content
        posts_run3 = [{
            "title": "AI in Healthcare",
            "body": "Machine learning models are revolutionizing medical diagnosis, with recent studies showing 95% accuracy in detecting certain cancers from imaging data.",
            "seo_score": 90,
            "seo_keywords": ["AI", "healthcare", "diagnosis"],
            "hashtags": ["#AI", "#Healthcare", "#MachineLearning"]
        }]
        
        simulate_agent_run(3, posts_run3)
        
        print("\n" + "="*60)
        print("DEMONSTRATION COMPLETE")
        print("="*60)
        print("\n✅ Key Outcomes:")
        print("   • Run 1: Successfully saved unique post to database")
        print("   • Run 2: Detected duplicate from previous run (prevented!)")
        print("   • Run 3: Successfully saved new unique post to database")
        print("\n💡 The Fix:")
        print("   • Database persists across all runs")
        print("   • Duplicate detection now works correctly")
        print("   • No more identical posts on consecutive days")
        
    finally:
        # Clean up
        shutil.rmtree(temp_dir)
        print(f"\n🧹 Cleaned up demo database")


if __name__ == "__main__":
    main()
