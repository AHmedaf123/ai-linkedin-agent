import os
import json
import logging
import hashlib
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

logger = logging.getLogger("linkedin-agent")

# Path to store used posts
USED_POSTS_PATH = "content_backlog/used_posts.jsonl"

# Maximum number of posts to keep in history
MAX_HISTORY_SIZE = 30

# Similarity threshold above which posts are considered too similar
SIMILARITY_THRESHOLD = 0.8

# Maximum number of regeneration attempts
MAX_REGENERATION_ATTEMPTS = 3

def ensure_used_posts_file():
    """Ensure the used posts file exists"""
    os.makedirs(os.path.dirname(USED_POSTS_PATH), exist_ok=True)
    if not os.path.exists(USED_POSTS_PATH):
        with open(USED_POSTS_PATH, "w") as f:
            pass  # Create empty file

def load_recent_posts() -> List[Dict[str, Any]]:
    """Load recent posts from the used posts file"""
    ensure_used_posts_file()
    posts = []
    
    try:
        with open(USED_POSTS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:  # Skip empty lines
                    try:
                        post = json.loads(line)
                        posts.append(post)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON in used posts file: {line}")
    except Exception as e:
        logger.error(f"Error loading recent posts: {str(e)}")
        # Return empty list if file can't be read
        return []
    
    # Return most recent posts first
    return sorted(posts, key=lambda x: x.get("timestamp", ""), reverse=True)[:MAX_HISTORY_SIZE]

def save_post(post: Dict[str, Any]):
    """Save a post to the used posts file"""
    ensure_used_posts_file()
    
    # Add timestamp and hash
    post_copy = post.copy()
    post_copy["timestamp"] = datetime.now().isoformat()
    post_copy["hash"] = hashlib.md5(post["body"].encode()).hexdigest()
    
    try:
        # Append to file
        with open(USED_POSTS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(post_copy) + "\n")
        
        # Trim file if needed
        recent_posts = load_recent_posts()
        if len(recent_posts) > MAX_HISTORY_SIZE:
            with open(USED_POSTS_PATH, "w", encoding="utf-8") as f:
                for post in recent_posts[:MAX_HISTORY_SIZE]:
                    f.write(json.dumps(post) + "\n")
    except Exception as e:
        logger.error(f"Error saving post to history: {str(e)}")

def calculate_similarity(candidate_text: str, recent_posts: List[Dict[str, Any]]) -> Tuple[float, Optional[Dict[str, Any]]]:
    """Calculate cosine similarity between candidate post and recent posts
    
    Args:
        candidate_text: Text of the candidate post
        recent_posts: List of recent posts
        
    Returns:
        Tuple of (highest similarity score, most similar post)
    """
    if not recent_posts:
        return 0.0, None
    
    # Extract text from recent posts
    recent_texts = [post.get("body", "") for post in recent_posts]
    
    # Create TF-IDF vectorizer
    vectorizer = TfidfVectorizer(stop_words="english")
    
    try:
        # Add candidate text to the corpus
        all_texts = recent_texts + [candidate_text]
        tfidf_matrix = vectorizer.fit_transform(all_texts)
        
        # Calculate similarity between candidate and each recent post
        candidate_vector = tfidf_matrix[-1:]
        recent_vectors = tfidf_matrix[:-1]
        
        # Calculate cosine similarity
        similarities = cosine_similarity(candidate_vector, recent_vectors).flatten()
        
        # Find highest similarity and corresponding post
        max_similarity = np.max(similarities)
        max_index = np.argmax(similarities)
        most_similar_post = recent_posts[max_index] if max_similarity > 0 else None
        
        return max_similarity, most_similar_post
    except Exception as e:
        logger.error(f"Error calculating similarity: {str(e)}")
        return 0.0, None

def is_duplicate(post: Dict[str, Any]) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Check if a post is too similar to recent posts
    
    Args:
        post: The post to check
        
    Returns:
        Tuple of (is_duplicate, most_similar_post)
    """
    recent_posts = load_recent_posts()
    similarity, similar_post = calculate_similarity(post["body"], recent_posts)
    
    logger.info(f"Post similarity score: {similarity:.2f}")
    if similarity > SIMILARITY_THRESHOLD:
        logger.warning(f"Post is too similar to a recent post (score: {similarity:.2f})")
        return True, similar_post
    
    return False, None

def check_and_save_post(post: Dict[str, Any], regenerate_func=None) -> Tuple[Dict[str, Any], bool]:
    """Check if a post is a duplicate and save it if not
    
    Args:
        post: The post to check and save
        regenerate_func: Function to regenerate a post if it's a duplicate
        
    Returns:
        Tuple of (final_post, is_original)
    """
    # Check if post is a duplicate
    is_dup, similar_post = is_duplicate(post)
    
    # If not a duplicate or no regeneration function, save and return
    if not is_dup or regenerate_func is None:
        if not is_dup:
            save_post(post)
            return post, True
        else:
            logger.warning("Post is a duplicate but no regeneration function provided")
            return post, False
    
    # Try to regenerate post up to MAX_REGENERATION_ATTEMPTS times
    attempts = 0
    current_post = post
    
    while is_dup and attempts < MAX_REGENERATION_ATTEMPTS:
        attempts += 1
        logger.info(f"Regenerating post (attempt {attempts}/{MAX_REGENERATION_ATTEMPTS})")
        
        try:
            # Regenerate post
            new_post = regenerate_func(current_post, similar_post)
            
            # Check if new post is a duplicate
            is_dup, similar_post = is_duplicate(new_post)
            current_post = new_post
            
            if not is_dup:
                logger.info(f"Successfully regenerated non-duplicate post after {attempts} attempts")
                save_post(current_post)
                return current_post, True
        except Exception as e:
            logger.error(f"Error regenerating post: {str(e)}")
            break
    
    # If we couldn't regenerate a non-duplicate post, log warning
    if is_dup:
        logger.warning(f"Failed to generate a unique post after {attempts} attempts")
    
    # Save the last post anyway
    save_post(current_post)
    return current_post, not is_dup