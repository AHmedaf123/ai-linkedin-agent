import logging
import hashlib
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

logger = logging.getLogger("linkedin-agent")

# In-memory recent posts only (no on-disk storage)
_RECENT_POSTS: List[Dict[str, Any]] = []
MAX_HISTORY_SIZE = 30
SIMILARITY_THRESHOLD = 0.8
MAX_REGENERATION_ATTEMPTS = 3


class Deduper:
    @staticmethod
    def load_recent_posts() -> List[Dict[str, Any]]:
        return list(_RECENT_POSTS[:MAX_HISTORY_SIZE])

    @staticmethod
    def save_post(post: Dict[str, Any]) -> None:
        record = {
            **post,
            "timestamp": datetime.utcnow().isoformat(),
            "hash": hashlib.md5(post.get("body", "").encode()).hexdigest(),
        }
        # Prepend to keep recent first
        _RECENT_POSTS.insert(0, record)
        # Trim
        del _RECENT_POSTS[MAX_HISTORY_SIZE:]

    @staticmethod
    def calculate_similarity(candidate_text: str, recent_posts: List[Dict[str, Any]]) -> Tuple[float, Optional[Dict[str, Any]]]:
        if not recent_posts:
            return 0.0, None
        recent_texts = [p.get("body", "") for p in recent_posts]
        vectorizer = TfidfVectorizer(stop_words="english")
        try:
            all_texts = recent_texts + [candidate_text]
            tfidf = vectorizer.fit_transform(all_texts)
            cand = tfidf[-1:]
            prev = tfidf[:-1]
            sims = cosine_similarity(cand, prev).flatten()
            idx = int(np.argmax(sims)) if sims.size else 0
            max_sim = float(np.max(sims)) if sims.size else 0.0
            sim_post = recent_posts[idx] if sims.size and max_sim > 0 else None
            return max_sim, sim_post
        except Exception as e:
            logger.error(f"Error calculating similarity: {e}")
            return 0.0, None

    @staticmethod
    def is_duplicate(post: Dict[str, Any]) -> Tuple[bool, Optional[Dict[str, Any]]]:
        recent = Deduper.load_recent_posts()
        similarity, similar_post = Deduper.calculate_similarity(post.get("body", ""), recent)
        logger.info(f"Post similarity score: {similarity:.2f}")
        if similarity > SIMILARITY_THRESHOLD:
            logger.warning(f"Post is too similar to a recent post (score: {similarity:.2f})")
            return True, similar_post
        return False, None

    @staticmethod
    def check_and_save_post(post: Dict[str, Any], regenerate_func=None) -> Tuple[Dict[str, Any], bool]:
        is_dup, similar_post = Deduper.is_duplicate(post)
        if not is_dup or regenerate_func is None:
            if not is_dup:
                Deduper.save_post(post)
                return post, True
            logger.warning("Post is a duplicate but no regeneration function provided")
            return post, False
        attempts = 0
        current_post = post
        while is_dup and attempts < MAX_REGENERATION_ATTEMPTS:
            attempts += 1
            logger.info(f"Regenerating post (attempt {attempts}/{MAX_REGENERATION_ATTEMPTS})")
            try:
                new_post = regenerate_func(current_post, similar_post)
                is_dup, similar_post = Deduper.is_duplicate(new_post)
                current_post = new_post
                if not is_dup:
                    Deduper.save_post(current_post)
                    return current_post, True
            except Exception as e:
                logger.error(f"Error regenerating post: {e}")
                break
        if is_dup:
            logger.warning(f"Failed to generate a unique post after {attempts} attempts")
            # Do not save duplicate post to persistent history; return failure
            return current_post, False
        # Fallback
        Deduper.save_post(current_post)
        return current_post, not is_dup


# Public API facades for backward compatibility


def load_recent_posts() -> List[Dict[str, Any]]:
    return Deduper.load_recent_posts()


def save_post(post: Dict[str, Any]) -> None:
    Deduper.save_post(post)


def calculate_similarity(candidate_text: str, recent_posts: List[Dict[str, Any]]) -> Tuple[float, Optional[Dict[str, Any]]]:
    return Deduper.calculate_similarity(candidate_text, recent_posts)


def is_duplicate(post: Dict[str, Any]) -> Tuple[bool, Optional[Dict[str, Any]]]:
    return Deduper.is_duplicate(post)


def check_and_save_post(post: Dict[str, Any], regenerate_func=None) -> Tuple[Dict[str, Any], bool]:
    return Deduper.check_and_save_post(post, regenerate_func)
