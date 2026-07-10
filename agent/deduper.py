"""Deduplication against *persistent* post history (agent/storage.py).

Two checks run before a draft is accepted:
  1. Full-body similarity vs the last 30 published posts (TF-IDF cosine).
  2. Hook similarity: the first sentence vs the last 10 hooks — repetitive
     openings ("The future of X…", "how do you keep up?") get rejected even
     when the rest of the body differs.

Posts generated in the current run are also tracked in-session so a single run
can't produce two near-identical drafts. Persistent saves happen at publish
time in run.py, so dry-runs never pollute history.
"""

import os
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

from agent import storage

logger = logging.getLogger("linkedin-agent")

# Drafts generated during this run (not yet published).
_SESSION_POSTS: List[Dict[str, Any]] = []

MAX_HISTORY_SIZE = 30
HOOK_HISTORY_SIZE = 10
SIMILARITY_THRESHOLD = float(os.getenv("DEDUP_SIMILARITY_THRESHOLD", "0.8"))
HOOK_SIMILARITY_THRESHOLD = float(os.getenv("DEDUP_HOOK_SIMILARITY_THRESHOLD", "0.6"))
MAX_REGENERATION_ATTEMPTS = 3


def _tfidf_max_similarity(candidate: str, texts: List[str]) -> Tuple[float, int]:
    """Max cosine similarity of candidate vs texts; returns (score, index)."""
    texts = [t for t in texts if t and t.strip()]
    if not texts or not candidate or not candidate.strip():
        return 0.0, -1
    try:
        vectorizer = TfidfVectorizer(stop_words="english")
        tfidf = vectorizer.fit_transform(texts + [candidate])
        sims = cosine_similarity(tfidf[-1:], tfidf[:-1]).flatten()
        if not sims.size:
            return 0.0, -1
        idx = int(np.argmax(sims))
        return float(sims[idx]), idx
    except Exception as e:
        logger.error(f"Error calculating similarity: {e}")
        return 0.0, -1


class Deduper:
    @staticmethod
    def load_recent_posts() -> List[Dict[str, Any]]:
        """Session drafts first (most recent), then persisted post history."""
        persisted = storage.get_recent_posts(MAX_HISTORY_SIZE)
        combined = list(_SESSION_POSTS) + persisted
        return combined[:MAX_HISTORY_SIZE]

    @staticmethod
    def save_post(post: Dict[str, Any]) -> None:
        """Track an accepted draft for the rest of this run.

        Persistent storage happens at publish time (run.py) via
        storage.save_used_post, so failed/dry runs don't burn history.
        """
        record = {
            **post,
            "timestamp": datetime.utcnow().isoformat(),
            "hash": storage.post_hash(post.get("body", "")),
            "hook": storage.extract_hook(post.get("body", "")),
        }
        _SESSION_POSTS.insert(0, record)
        del _SESSION_POSTS[MAX_HISTORY_SIZE:]

    @staticmethod
    def calculate_similarity(candidate_text: str, recent_posts: List[Dict[str, Any]]) -> Tuple[float, Optional[Dict[str, Any]]]:
        bodies = [p.get("body", "") for p in recent_posts]
        score, idx = _tfidf_max_similarity(candidate_text, bodies)
        similar = recent_posts[idx] if idx >= 0 and score > 0 else None
        return score, similar

    @staticmethod
    def calculate_hook_similarity(candidate_text: str, recent_posts: List[Dict[str, Any]]) -> Tuple[float, Optional[Dict[str, Any]]]:
        """Compare the draft's opening sentence against recent hooks."""
        candidate_hook = storage.extract_hook(candidate_text)
        recent = recent_posts[:HOOK_HISTORY_SIZE]
        hooks = [p.get("hook") or storage.extract_hook(p.get("body", "")) for p in recent]
        score, idx = _tfidf_max_similarity(candidate_hook, hooks)
        similar = recent[idx] if idx >= 0 and score > 0 else None
        return score, similar

    @staticmethod
    def is_duplicate(post: Dict[str, Any]) -> Tuple[bool, Optional[Dict[str, Any]]]:
        recent = Deduper.load_recent_posts()
        body = post.get("body", "")

        # Exact-body republish guard (cheap, catches cross-run repeats outright)
        if storage.is_hash_used(storage.post_hash(body)):
            logger.warning("Draft body hash already exists in published history")
            return True, None

        similarity, similar_post = Deduper.calculate_similarity(body, recent)
        logger.info(f"Post similarity score: {similarity:.2f}")
        if similarity > SIMILARITY_THRESHOLD:
            logger.warning(f"Post is too similar to a recent post (score: {similarity:.2f})")
            return True, similar_post

        hook_sim, hook_post = Deduper.calculate_hook_similarity(body, recent)
        logger.info(f"Hook similarity score: {hook_sim:.2f}")
        if hook_sim > HOOK_SIMILARITY_THRESHOLD:
            logger.warning(
                f"Draft opening repeats a recent hook (score: {hook_sim:.2f}): "
                f"{storage.extract_hook(body)!r}"
            )
            return True, hook_post

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
                if not new_post:
                    break
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
            return current_post, False
        Deduper.save_post(current_post)
        return current_post, not is_dup


# Public API facades for backward compatibility


def load_recent_posts() -> List[Dict[str, Any]]:
    return Deduper.load_recent_posts()


def save_post(post: Dict[str, Any]) -> None:
    Deduper.save_post(post)


def calculate_similarity(candidate_text: str, recent_posts: List[Dict[str, Any]]) -> Tuple[float, Optional[Dict[str, Any]]]:
    return Deduper.calculate_similarity(candidate_text, recent_posts)


def calculate_hook_similarity(candidate_text: str, recent_posts: List[Dict[str, Any]]) -> Tuple[float, Optional[Dict[str, Any]]]:
    return Deduper.calculate_hook_similarity(candidate_text, recent_posts)


def is_duplicate(post: Dict[str, Any]) -> Tuple[bool, Optional[Dict[str, Any]]]:
    return Deduper.is_duplicate(post)


def check_and_save_post(post: Dict[str, Any], regenerate_func=None) -> Tuple[Dict[str, Any], bool]:
    return Deduper.check_and_save_post(post, regenerate_func)
