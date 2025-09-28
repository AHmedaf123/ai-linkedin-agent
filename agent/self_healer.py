import json
import os
import time
import datetime
import traceback
from typing import Dict, List, Any, Optional, Callable
from agent.logging_setup import get_logger
from agent.email_reporter import send_email_report

# Initialize logger
logger = get_logger("self_healer")

# Constants
ERRORS_PATH = "agent/errors.json"
RETRY_QUEUE_PATH = "agent/retry_queue.json"
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds


class RetryQueue:
    """Class to manage retry queue for failed operations"""
    
    def __init__(self):
        """Initialize the retry queue"""
        self.queue = self._load_queue()
    
    def _load_queue(self) -> Dict:
        """Load retry queue from file"""
        try:
            if os.path.exists(RETRY_QUEUE_PATH):
                with open(RETRY_QUEUE_PATH, "r") as f:
                    return json.load(f)
            return {"items": []}
        except Exception as e:
            logger.error(f"Error loading retry queue: {str(e)}")
            return {"items": []}
    
    def _save_queue(self):
        """Save retry queue to file"""
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(RETRY_QUEUE_PATH), exist_ok=True)
            
            with open(RETRY_QUEUE_PATH, "w") as f:
                json.dump(self.queue, f, indent=2)
            
            logger.info(f"Saved retry queue to {RETRY_QUEUE_PATH}")
        except Exception as e:
            logger.error(f"Error saving retry queue: {str(e)}")
    
    def add_item(self, item_type: str, item_data: Dict, max_retries: int = MAX_RETRIES):
        """Add an item to the retry queue
        
        Args:
            item_type: Type of item (e.g., "post", "email")
            item_data: Data associated with the item
            max_retries: Maximum number of retry attempts
        """
        try:
            # Create a new queue item
            queue_item = {
                "id": f"{item_type}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
                "type": item_type,
                "data": item_data,
                "created_at": datetime.datetime.now().isoformat(),
                "retry_count": 0,
                "max_retries": max_retries,
                "next_retry": datetime.datetime.now().isoformat(),
                "status": "pending"
            }
            
            # Add to queue
            self.queue["items"].append(queue_item)
            self._save_queue()
            
            logger.info(f"Added {item_type} to retry queue with ID {queue_item['id']}")
        except Exception as e:
            logger.error(f"Error adding item to retry queue: {str(e)}")
    
    def get_pending_items(self) -> List[Dict]:
        """Get all pending items that are due for retry"""
        try:
            now = datetime.datetime.now()
            pending_items = []
            
            for item in self.queue["items"]:
                if item["status"] == "pending":
                    next_retry = datetime.datetime.fromisoformat(item["next_retry"])
                    if next_retry <= now:
                        pending_items.append(item)
            
            return pending_items
        except Exception as e:
            logger.error(f"Error getting pending items: {str(e)}")
            return []
    
    def update_item_status(self, item_id: str, status: str, error: str = None):
        """Update the status of an item in the retry queue
        
        Args:
            item_id: ID of the item to update
            status: New status ("success", "failed", "pending")
            error: Optional error message
        """
        # Validate inputs
        if not item_id or not isinstance(item_id, str):
            logger.error("Invalid item_id provided")
            return False
        if status not in ["success", "failed", "pending", "max_retries_reached"]:
            logger.error(f"Invalid status: {status}")
            return False
            
        try:
            for i, item in enumerate(self.queue["items"]):
                if item["id"] == item_id:
                    # Update status
                    self.queue["items"][i]["status"] = status
                    self.queue["items"][i]["last_updated"] = datetime.datetime.now().isoformat()
                    
                    if status == "failed":
                        # Increment retry count
                        self.queue["items"][i]["retry_count"] += 1
                        
                        # Set next retry time (exponential backoff)
                        retry_delay = RETRY_DELAY * (2 ** self.queue["items"][i]["retry_count"])
                        next_retry = datetime.datetime.now() + datetime.timedelta(seconds=retry_delay)
                        self.queue["items"][i]["next_retry"] = next_retry.isoformat()
                        
                        # Add error message
                        if error:
                            self.queue["items"][i]["last_error"] = error
                        
                        # Check if max retries reached
                        if self.queue["items"][i]["retry_count"] >= self.queue["items"][i]["max_retries"]:
                            self.queue["items"][i]["status"] = "max_retries_reached"
                            logger.warning(f"Max retries reached for item {item_id}")
                    
                    self._save_queue()
                    logger.info(f"Updated item {item_id} status to {status}")
                    return True
            
            logger.warning(f"Item {item_id} not found in retry queue")
            return False
        except Exception as e:
            logger.error(f"Error updating item status: {str(e)}")
            return False
    
    def clean_queue(self, max_age_days: int = 7):
        """Clean up old items from the retry queue
        
        Args:
            max_age_days: Maximum age of items to keep (in days)
        """
        # Validate input
        if not isinstance(max_age_days, int) or max_age_days < 1:
            logger.error(f"Invalid max_age_days: {max_age_days}")
            return
            
        try:
            now = datetime.datetime.now()
            max_age = datetime.timedelta(days=max_age_days)
            
            # Filter out old items
            new_items = []
            for item in self.queue["items"]:
                created_at = datetime.datetime.fromisoformat(item["created_at"])
                if now - created_at <= max_age or item["status"] == "pending":
                    new_items.append(item)
            
            # Update queue
            removed_count = len(self.queue["items"]) - len(new_items)
            self.queue["items"] = new_items
            self._save_queue()
            
            logger.info(f"Cleaned retry queue, removed {removed_count} old items")
        except Exception as e:
            logger.error(f"Error cleaning retry queue: {str(e)}")


class ErrorTracker:
    """Class to track and log errors"""
    
    def __init__(self):
        """Initialize the error tracker"""
        self.errors = self._load_errors()
    
    def _load_errors(self) -> Dict:
        """Load errors from file"""
        try:
            if os.path.exists(ERRORS_PATH):
                with open(ERRORS_PATH, "r") as f:
                    return json.load(f)
            return {"errors": []}
        except Exception as e:
            logger.error(f"Error loading errors: {str(e)}")
            return {"errors": []}
    
    def _save_errors(self):
        """Save errors to file"""
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(ERRORS_PATH), exist_ok=True)
            
            with open(ERRORS_PATH, "w") as f:
                json.dump(self.errors, f, indent=2)
            
            logger.info(f"Saved errors to {ERRORS_PATH}")
        except Exception as e:
            logger.error(f"Error saving errors: {str(e)}")
    
    def log_error(self, error: Exception, phase: str, context: Dict = None):
        """Log an error
        
        Args:
            error: The exception that occurred
            phase: The phase of execution where the error occurred
            context: Optional dictionary with additional context about the error
        """
        try:
            # Create error entry
            error_entry = {
                "id": f"error_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
                "timestamp": datetime.datetime.now().isoformat(),
                "phase": phase,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "traceback": traceback.format_exc(),
                "context": context or {}
            }
            
            # Add to errors list
            self.errors["errors"].append(error_entry)
            self._save_errors()
            
            logger.info(f"Logged error in phase {phase}: {str(error)}")
            return error_entry["id"]
        except Exception as e:
            logger.error(f"Error logging error: {str(e)}")
            return None
    
    def get_recent_errors(self, limit: int = 10) -> List[Dict]:
        """Get recent errors
        
        Args:
            limit: Maximum number of errors to return
            
        Returns:
            List of recent errors
        """
        try:
            # Sort errors by timestamp (newest first)
            sorted_errors = sorted(
                self.errors["errors"],
                key=lambda e: e["timestamp"],
                reverse=True
            )
            
            return sorted_errors[:limit]
        except Exception as e:
            logger.error(f"Error getting recent errors: {str(e)}")
            return []
    
    def get_error_stats(self) -> Dict:
        """Get error statistics
        
        Returns:
            Dictionary with error statistics
        """
        try:
            errors = self.errors["errors"]
            
            # Count errors by phase
            phase_counts = {}
            for error in errors:
                phase = error["phase"]
                if phase not in phase_counts:
                    phase_counts[phase] = 0
                phase_counts[phase] += 1
            
            # Count errors by type
            type_counts = {}
            for error in errors:
                error_type = error["error_type"]
                if error_type not in type_counts:
                    type_counts[error_type] = 0
                type_counts[error_type] += 1
            
            # Get error frequency over time
            now = datetime.datetime.now()
            last_24h = len([e for e in errors if 
                          datetime.datetime.fromisoformat(e["timestamp"]) > now - datetime.timedelta(hours=24)])
            last_7d = len([e for e in errors if 
                         datetime.datetime.fromisoformat(e["timestamp"]) > now - datetime.timedelta(days=7)])
            
            return {
                "total_errors": len(errors),
                "errors_by_phase": phase_counts,
                "errors_by_type": type_counts,
                "errors_last_24h": last_24h,
                "errors_last_7d": last_7d
            }
        except Exception as e:
            logger.error(f"Error getting error stats: {str(e)}")
            return {
                "total_errors": 0,
                "errors_by_phase": {},
                "errors_by_type": {},
                "errors_last_24h": 0,
                "errors_last_7d": 0,
                "error": str(e)
            }


def retry_with_backoff(func: Callable, *args, max_retries: int = MAX_RETRIES, **kwargs):
    """Retry a function with exponential backoff
    
    Args:
        func: Function to retry
        *args: Arguments to pass to the function
        max_retries: Maximum number of retry attempts
        **kwargs: Keyword arguments to pass to the function
        
    Returns:
        Result of the function call
    """
    retries = 0
    while retries <= max_retries:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            retries += 1
            if retries > max_retries:
                logger.error(f"Max retries ({max_retries}) reached for {func.__name__}")
                raise
            
            # Calculate delay with exponential backoff
            delay = RETRY_DELAY * (2 ** (retries - 1))
            logger.warning(f"Retry {retries}/{max_retries} for {func.__name__} after {delay}s: {str(e)}")
            time.sleep(delay)


def handle_error(error: Exception, phase: str, context: Dict = None, retry_item: Dict = None, send_report: bool = True, retry: bool = False, critical: bool = False):
    """Handle an error with logging and optional retry
    
    Args:
        error: The exception that occurred
        phase: The phase of execution where the error occurred
        context: Optional dictionary with additional context about the error
        retry_item: Optional item to add to retry queue
        send_report: Whether to send an email report about the error
        retry: Whether to add the item to the retry queue
        critical: Whether this is a critical error that should trigger additional actions
    """
    try:
        # Log the error
        error_tracker = ErrorTracker()
        error_id = error_tracker.log_error(error, phase, context)
        
        # Add to retry queue if specified or retry flag is set
        if retry or retry_item:
            retry_queue = RetryQueue()
            if retry_item:
                retry_queue.add_item(retry_item["type"], retry_item["data"], retry_item.get("max_retries", MAX_RETRIES))
        
        # Send error report email if requested
        if send_report:
            error_message = f"Error during {phase} phase: {str(error)}\n\n{traceback.format_exc()}"
            
            # Create a simple post-like structure for the error report
            error_post = {
                "title": f"ERROR: LinkedIn Agent - {phase} failure",
                "body": error_message,
                "seo_score": 0,
                "seo_keywords": [],
                "hashtags": []
            }
            
            # Add context information to the error report if available
            if context:
                context_section = "\n\nAdditional Context:\n"
                for key, value in context.items():
                    context_section += f"- {key}: {value}\n"
                error_post["body"] += context_section
            
            # Add error ID for reference
            if error_id:
                error_post["body"] += f"\n\nError ID: {error_id}"
                
            # Add critical flag information if set
            if critical:
                error_post["body"] += "\n\nThis is a CRITICAL error that requires immediate attention."
            
            # Send the email report
            send_email_report(error_post, is_error=True)
            logger.info("Error report email sent")
    except Exception as e:
        logger.error(f"Error in handle_error: {str(e)}")


def process_retry_queue():
    """Process pending items in the retry queue"""
    try:
        retry_queue = RetryQueue()
        pending_items = retry_queue.get_pending_items()
        
        if not pending_items:
            logger.info("No pending items in retry queue")
            return
        
        logger.info(f"Processing {len(pending_items)} pending items in retry queue")
        
        for item in pending_items:
            try:
                item_id = item["id"]
                item_type = item["type"]
                item_data = item["data"]
                
                logger.info(f"Processing retry item {item_id} of type {item_type}")
                
                # Handle different item types
                if item_type == "post":
                    # Import here to avoid circular imports
                    from agent.linkedin_poster import post_to_linkedin
                    
                    # Retry posting to LinkedIn
                    post_to_linkedin(item_data["body"])
                    retry_queue.update_item_status(item_id, "success")
                    logger.info(f"Successfully retried LinkedIn post for item {item_id}")
                
                elif item_type == "email":
                    # Retry sending email
                    send_email_report(item_data, is_error=item_data.get("is_error", False))
                    retry_queue.update_item_status(item_id, "success")
                    logger.info(f"Successfully retried email for item {item_id}")
                
                else:
                    logger.warning(f"Unknown item type {item_type} for item {item_id}")
                    retry_queue.update_item_status(item_id, "failed", f"Unknown item type: {item_type}")
            
            except Exception as e:
                logger.error(f"Error processing retry item {item['id']}: {str(e)}")
                retry_queue.update_item_status(item["id"], "failed", str(e))
        
        # Clean up old items
        retry_queue.clean_queue()
    
    except Exception as e:
        logger.error(f"Error processing retry queue: {str(e)}")


def check_system_health() -> Dict:
    """Check the health of the system
    
    Returns:
        Dictionary with health status
    """
    try:
        health_status = {
            "status": "healthy",
            "components": {},
            "timestamp": datetime.datetime.now().isoformat()
        }
        
        # Check error statistics
        error_tracker = ErrorTracker()
        error_stats = error_tracker.get_error_stats()
        
        # Check recent errors
        recent_errors = error_tracker.get_recent_errors(5)
        recent_error_count = len(recent_errors)
        
        # Check retry queue
        retry_queue = RetryQueue()
        pending_items = retry_queue.get_pending_items()
        pending_count = len(pending_items)
        
        # Set component statuses
        health_status["components"]["errors"] = {
            "status": "warning" if error_stats["errors_last_24h"] > 5 else "healthy",
            "details": {
                "total_errors": error_stats["total_errors"],
                "recent_errors": recent_error_count,
                "errors_last_24h": error_stats["errors_last_24h"]
            }
        }
        
        health_status["components"]["retry_queue"] = {
            "status": "warning" if pending_count > 10 else "healthy",
            "details": {
                "pending_items": pending_count
            }
        }
        
        # Set overall status
        if any(c["status"] == "critical" for c in health_status["components"].values()):
            health_status["status"] = "critical"
        elif any(c["status"] == "warning" for c in health_status["components"].values()):
            health_status["status"] = "warning"
        
        return health_status
    
    except Exception as e:
        logger.error(f"Error checking system health: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.datetime.now().isoformat()
        }