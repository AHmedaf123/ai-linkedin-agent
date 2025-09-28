import json
import os
import time
import datetime
from typing import Dict, List, Any, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from agent.logging_setup import get_logger

# Initialize logger
logger = get_logger("engagement_tracker")

# Constants
METRICS_HISTORY_PATH = "agent/metrics_history.json"
LINKEDIN_LOGIN_URL = "https://www.linkedin.com/login"
LINKEDIN_PROFILE_URL = "https://www.linkedin.com/in/"
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds


class LinkedInEngagementTracker:
    """Class to track LinkedIn post engagement metrics"""
    
    def __init__(self, username: str, password: str, profile_url: str = None):
        """Initialize the LinkedIn engagement tracker
        
        Args:
            username: LinkedIn username/email
            password: LinkedIn password
            profile_url: Optional LinkedIn profile URL, if different from standard format
        """
        self.username = username
        self.password = password
        if profile_url:
            self.profile_url = profile_url
        else:
            self.profile_url = f"{LINKEDIN_PROFILE_URL}{username}"
        self.driver = None
        self.metrics_history = self._load_metrics_history()
    
    def _load_metrics_history(self) -> Dict:
        """Load metrics history from file"""
        try:
            if os.path.exists(METRICS_HISTORY_PATH):
                with open(METRICS_HISTORY_PATH, "r") as f:
                    return json.load(f)
            return {"posts": []}
        except Exception as e:
            logger.error(f"Error loading metrics history: {str(e)}")
            return {"posts": []}
    
    def _save_metrics_history(self):
        """Save metrics history to file"""
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(METRICS_HISTORY_PATH), exist_ok=True)
            
            with open(METRICS_HISTORY_PATH, "w") as f:
                json.dump(self.metrics_history, f, indent=2)
            
            logger.info(f"Saved metrics history to {METRICS_HISTORY_PATH}")
        except Exception as e:
            logger.error(f"Error saving metrics history: {str(e)}")
    
    def _initialize_driver(self):
        """Initialize the Selenium WebDriver"""
        try:
            # Set up Chrome options
            options = webdriver.ChromeOptions()
            options.add_argument("--headless")  # Run in headless mode
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            
            # Initialize the driver
            self.driver = webdriver.Chrome(options=options)
            logger.info("Initialized Chrome WebDriver")
        except Exception as e:
            logger.error(f"Error initializing WebDriver: {str(e)}")
            raise
    
    def _login_to_linkedin(self):
        """Log in to LinkedIn"""
        try:
            logger.info("Logging in to LinkedIn...")
            self.driver.get(LINKEDIN_LOGIN_URL)
            
            # Wait for the login page to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "username"))
            )
            
            # Enter username and password
            self.driver.find_element(By.ID, "username").send_keys(self.username)
            self.driver.find_element(By.ID, "password").send_keys(self.password)
            
            # Click the login button
            self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
            
            # Wait for login to complete
            WebDriverWait(self.driver, 10).until(
                EC.url_contains("linkedin.com/feed")
            )
            
            logger.info("Successfully logged in to LinkedIn")
            return True
        except Exception as e:
            logger.error(f"Error logging in to LinkedIn: {str(e)}")
            return False
    
    def _navigate_to_profile(self):
        """Navigate to the LinkedIn profile page"""
        try:
            logger.info(f"Navigating to profile: {self.profile_url}")
            self.driver.get(self.profile_url)
            
            # Wait for the profile page to load
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".pv-top-card"))
            )
            
            logger.info("Successfully navigated to profile page")
            return True
        except Exception as e:
            logger.error(f"Error navigating to profile: {str(e)}")
            return False
    
    def _extract_post_engagement(self, post_element):
        """Extract engagement metrics from a post element"""
        try:
            # Extract post content
            post_text_element = post_element.find_element(By.CSS_SELECTOR, ".feed-shared-update-v2__description")
            post_text = post_text_element.text if post_text_element else ""
            
            # Extract post date
            post_date_element = post_element.find_element(By.CSS_SELECTOR, ".feed-shared-actor__sub-description")
            post_date = post_date_element.text if post_date_element else ""
            
            # Extract engagement metrics
            likes = 0
            comments = 0
            shares = 0
            impressions = 0
            
            # Try to find the engagement counts
            try:
                engagement_section = post_element.find_element(By.CSS_SELECTOR, ".social-details-social-counts")
                
                # Extract likes
                likes_element = engagement_section.find_element(By.CSS_SELECTOR, "[data-control-name='likes_count']") 
                likes_text = likes_element.text if likes_element else "0"
                likes = int(likes_text.replace(",", "")) if likes_text.replace(",", "").isdigit() else 0
                
                # Extract comments
                comments_element = engagement_section.find_element(By.CSS_SELECTOR, "[data-control-name='comments_count']") 
                comments_text = comments_element.text if comments_element else "0"
                comments = int(comments_text.replace(",", "")) if comments_text.replace(",", "").isdigit() else 0
                
                # Extract shares
                shares_element = engagement_section.find_element(By.CSS_SELECTOR, "[data-control-name='share_count']") 
                shares_text = shares_element.text if shares_element else "0"
                shares = int(shares_text.replace(",", "")) if shares_text.replace(",", "").isdigit() else 0
            except NoSuchElementException:
                # Some posts might not have engagement metrics visible
                pass
            
            # Create post data
            post_data = {
                "content": post_text[:200],  # Store first 200 chars as identifier
                "date": post_date,
                "timestamp": datetime.datetime.now().isoformat(),
                "engagement": {
                    "likes": likes,
                    "comments": comments,
                    "shares": shares,
                    "impressions": impressions
                }
            }
            
            return post_data
        except Exception as e:
            logger.error(f"Error extracting post engagement: {str(e)}")
            return None
    
    def fetch_engagement_metrics(self, max_posts: int = 5) -> List[Dict]:
        """Fetch engagement metrics for recent posts
        
        Args:
            max_posts: Maximum number of posts to fetch metrics for
            
        Returns:
            List of post engagement metrics
        """
        posts_data = []
        
        try:
            # Initialize the driver if not already initialized
            if not self.driver:
                self._initialize_driver()
            
            # Login to LinkedIn
            if not self._login_to_linkedin():
                logger.error("Failed to log in to LinkedIn")
                return posts_data
            
            # Navigate to profile
            if not self._navigate_to_profile():
                logger.error("Failed to navigate to profile")
                return posts_data
            
            # Wait for posts to load
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".pv-recent-activity-detail__post-container"))
                )
            except TimeoutException:
                logger.warning("No posts found on profile")
                return posts_data
            
            # Find all posts
            posts = self.driver.find_elements(By.CSS_SELECTOR, ".pv-recent-activity-detail__post-container")
            logger.info(f"Found {len(posts)} posts on profile")
            
            # Extract engagement metrics for each post (up to max_posts)
            for i, post in enumerate(posts[:max_posts]):
                post_data = self._extract_post_engagement(post)
                if post_data:
                    posts_data.append(post_data)
                    logger.info(f"Extracted engagement metrics for post {i+1}")
            
            # Update metrics history
            self._update_metrics_history(posts_data)
            
            return posts_data
        except Exception as e:
            logger.error(f"Error fetching engagement metrics: {str(e)}")
            return posts_data
        finally:
            # Close the driver
            if self.driver:
                self.driver.quit()
                self.driver = None
    
    def _update_metrics_history(self, new_posts_data: List[Dict]):
        """Update metrics history with new post data"""
        try:
            # Get existing posts
            existing_posts = self.metrics_history.get("posts", [])
            
            # Add new posts or update existing ones
            for new_post in new_posts_data:
                # Check if post already exists (by content)
                post_exists = False
                for i, existing_post in enumerate(existing_posts):
                    if existing_post.get("content") == new_post.get("content"):
                        # Update existing post
                        existing_posts[i] = new_post
                        post_exists = True
                        break
                
                # Add new post if it doesn't exist
                if not post_exists:
                    existing_posts.append(new_post)
            
            # Update metrics history
            self.metrics_history["posts"] = existing_posts
            self.metrics_history["last_updated"] = datetime.datetime.now().isoformat()
            
            # Save metrics history
            self._save_metrics_history()
        except Exception as e:
            logger.error(f"Error updating metrics history: {str(e)}")
    
    def get_engagement_stats(self) -> Dict:
        """Get engagement statistics from metrics history"""
        try:
            posts = self.metrics_history.get("posts", [])
            
            if not posts:
                return {
                    "total_posts": 0,
                    "avg_likes": 0,
                    "avg_comments": 0,
                    "avg_shares": 0,
                    "top_performing_post": None
                }
            
            # Calculate statistics
            total_likes = sum(post.get("engagement", {}).get("likes", 0) for post in posts)
            total_comments = sum(post.get("engagement", {}).get("comments", 0) for post in posts)
            total_shares = sum(post.get("engagement", {}).get("shares", 0) for post in posts)
            
            # Find top performing post
            top_post = max(posts, key=lambda p: (
                p.get("engagement", {}).get("likes", 0) +
                p.get("engagement", {}).get("comments", 0) * 3 +
                p.get("engagement", {}).get("shares", 0) * 5
            ))
            
            return {
                "total_posts": len(posts),
                "avg_likes": total_likes / len(posts) if posts else 0,
                "avg_comments": total_comments / len(posts) if posts else 0,
                "avg_shares": total_shares / len(posts) if posts else 0,
                "top_performing_post": top_post
            }
        except Exception as e:
            logger.error(f"Error calculating engagement stats: {str(e)}")
            return {
                "total_posts": 0,
                "avg_likes": 0,
                "avg_comments": 0,
                "avg_shares": 0,
                "top_performing_post": None,
                "error": str(e)
            }


def fetch_linkedin_engagement(linkedin_email: str, linkedin_password: str, max_posts: int = 5) -> List[Dict]:
    """Fetch LinkedIn engagement metrics
    
    Args:
        linkedin_email: LinkedIn email or username
        linkedin_password: LinkedIn password
        max_posts: Maximum number of posts to fetch metrics for
        
    Returns:
        List of engagement metrics for recent posts
    """
    try:
        tracker = LinkedInEngagementTracker(linkedin_email, linkedin_password)
        return tracker.fetch_engagement_metrics(max_posts)
    except Exception as e:
        logger.error(f"Error fetching LinkedIn engagement: {str(e)}")
        return []


logger = get_logger("engagement_tracker")

def get_engagement_stats() -> Dict:
    try:
        # Load metrics history
        if os.path.exists(METRICS_HISTORY_PATH):
            with open(METRICS_HISTORY_PATH, "r") as f:
                metrics_history = json.load(f)
        else:
            return {
                "total_posts": 0,
                "avg_likes": 0,
                "avg_comments": 0,
                "avg_shares": 0,
                "top_performing_post": None
            }
        
        # Create tracker and get stats
        tracker = LinkedInEngagementTracker("", "")
        tracker.metrics_history = metrics_history
        return tracker.get_engagement_stats()
    except Exception as e:
        logger.error(f"Error getting engagement stats: {str(e)}")
        return {
            "total_posts": 0,
            "avg_likes": 0,
            "avg_comments": 0,
            "avg_shares": 0,
            "top_performing_post": None,
            "error": str(e)
        }