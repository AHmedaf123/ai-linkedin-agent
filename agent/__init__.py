# Agent module initialization
# This file enables Python to recognize this directory as a package

# Explicitly import and expose the keywording module
from . import keywording


def ensure_hashtags_in_content(content: str, hashtags: list) -> str:
    """Ensure hashtags are appended to content if not already present.
    
    Args:
        content: The post content
        hashtags: List of hashtags to append
        
    Returns:
        Content with hashtags appended if they weren't already present
    """
    if not hashtags:
        return content
    
    # Check if any hashtags are already in the content
    has_hashtags = any(tag in content for tag in hashtags)
    
    if not has_hashtags:
        # Append hashtags to the end with a blank line
        hashtag_line = " ".join(hashtags)
        content = f"{content}\n\n{hashtag_line}"
    
    return content