#!/usr/bin/env python3
"""
Test LinkedIn connection and posting capabilities.
Use this script to verify your LinkedIn credentials work before deploying to CI.
"""

import os
import sys
import logging
from pathlib import Path

# Add the agent directory to the path
sys.path.insert(0, str(Path(__file__).parent / "agent"))

from linkedin_poster import LinkedInPoster, LinkedInAuthError, LinkedInPostError

def test_linkedin_connection():
    """Test LinkedIn connection without posting."""
    
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)
    
    # Get credentials
    email = os.getenv("LINKEDIN_EMAIL") or os.getenv("LINKEDIN_USER")
    password = os.getenv("LINKEDIN_PASSWORD") or os.getenv("LINKEDIN_PASS")
    
    if not (email and password):
        logger.error("LinkedIn credentials not found. Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD environment variables.")
        return False
    
    logger.info(f"Testing LinkedIn connection for: {email}")
    
    try:
        # Create poster instance
        poster = LinkedInPoster(email=email, password=password)
        
        # Test setup and login
        logger.info("Setting up browser...")
        poster._setup()
        
        logger.info("Attempting login...")
        poster._login()
        
        logger.info("✅ LinkedIn connection successful!")
        logger.info("✅ Login completed - session saved for future use")
        
        return True
        
    except LinkedInAuthError as e:
        logger.error(f"❌ LinkedIn authentication failed: {e}")
        logger.info("💡 This might be due to:")
        logger.info("   - Incorrect credentials")
        logger.info("   - LinkedIn security challenge (CAPTCHA)")
        logger.info("   - Account locked or restricted")
        return False
        
    except LinkedInPostError as e:
        logger.error(f"❌ LinkedIn posting error: {e}")
        return False
        
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        logger.info("💡 This might be due to:")
        logger.info("   - Network connectivity issues")
        logger.info("   - LinkedIn blocking automated access")
        logger.info("   - Browser/Playwright setup issues")
        return False
        
    finally:
        try:
            if poster:
                poster._teardown()
        except:
            pass

def main():
    """Main function."""
    print("🔍 LinkedIn Connection Test")
    print("=" * 40)
    
    # Check environment
    is_ci = os.getenv("CI", "false").lower() == "true"
    if is_ci:
        print("⚠️  Running in CI environment - LinkedIn may block automated access")
        print("💡 Consider running this test locally first")
        print()
    
    # Test connection
    success = test_linkedin_connection()
    
    print()
    print("=" * 40)
    if success:
        print("✅ Test completed successfully!")
        print("💡 Your LinkedIn credentials are working")
        print("💡 You can now run the main agent with confidence")
    else:
        print("❌ Test failed!")
        print("💡 Fix the issues above before running the main agent")
        print("💡 In CI environments, consider setting ENABLE_POST=false")
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())