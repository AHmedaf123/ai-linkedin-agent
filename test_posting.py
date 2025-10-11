#!/usr/bin/env python3
"""
Test script to verify LinkedIn posting functionality
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_environment():
    """Test if all required environment variables are set"""
    required_vars = {
        'OPENROUTER_API_KEY': os.getenv('OPENROUTER_API_KEY'),
        'LINKEDIN_EMAIL': os.getenv('LINKEDIN_EMAIL'),
        'LINKEDIN_PASSWORD': os.getenv('LINKEDIN_PASSWORD'),
        'ENABLE_POST': os.getenv('ENABLE_POST', 'true')
    }
    
    print("Environment Variables Check:")
    print("-" * 40)
    for var, value in required_vars.items():
        status = "✓ SET" if value else "✗ MISSING"
        print(f"{var}: {status}")
    
    return all(required_vars.values())

def test_config_files():
    """Test if required config files exist"""
    required_files = [
        'agent/config.json',
        'agent/repo_queue.json',
        'agent/calendar.yaml'
    ]
    
    print("\nConfig Files Check:")
    print("-" * 40)
    for file_path in required_files:
        exists = os.path.exists(file_path)
        status = "✓ EXISTS" if exists else "✗ MISSING"
        print(f"{file_path}: {status}")
    
    return all(os.path.exists(f) for f in required_files)

def main():
    print("LinkedIn Agent Posting Test")
    print("=" * 50)
    
    env_ok = test_environment()
    files_ok = test_config_files()
    
    print(f"\nOverall Status:")
    print("-" * 40)
    print(f"Environment: {'✓ READY' if env_ok else '✗ ISSUES'}")
    print(f"Config Files: {'✓ READY' if files_ok else '✗ ISSUES'}")
    
    if env_ok and files_ok:
        print(f"\n✓ Ready to test posting!")
        print("Run: python run.py --dry-run --force")
        print("Then: python run.py --force")
    else:
        print(f"\n✗ Fix the issues above before testing")

if __name__ == "__main__":
    main()