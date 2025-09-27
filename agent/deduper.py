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

USED_POSTS_PATH = "content_backlog/used_posts.jsonl"
MAX_HISTORY_SIZE = 30
SIMILARITY_THRESHOLD = 0.8
MAX_REGENERATION_ATTEMPTS = 3

class Deduper:
    @staticmethod
    def _ensure_file() -> None:
        os.makedirs(os.path.dirname(USED_POSTS_PATH), exist_ok=True)
        if not os.path.exists(USED_POSTS_PATH):
            with open(USED_POSTS_PATH, "w", encoding="utf-8") as f:
                f.write("")

    @staticmethod
    def load_recent_posts() -> List[Dict[str, Any]]:
        Deduper._ensure_file()
        posts: List[Dict[str, Any]] = []
        try:
            with open(USED_POSTS_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        posts.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.warning("Invalid JSON in used posts file; skipping line")
        except Exception as e:
            logger.error(f"Error loading recent posts: {e}")
            return []
        return sorted(posts, key=lambda x: x.get("timestamp", ""), reverse=True)[:MAX_HISTORY_SIZE]

    @staticmethod
    def save_post(post: Dict[str, Any]) -> None:
        Deduper._ensure_file()
        record = {
            **post,
            "timestamp": datetime.now().isoformat(),
            "hash": hashlib.md5(post.get("body", "").encode()).hexdigest(),
        }
        try:
            with open(USED_POSTS_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
            recent = Deduper.load_recent_posts()
            if len(recent) > MAX_HISTORY_SIZE:
                with open(USED_POSTS_PATH, "w", encoding="utf-8") as f:
                    for p in recent[:MAX_HISTORY_SIZE]:
                        f.write(json.dumps(p) + "\n")
        except Exception as e:
            logger.error(f"Error saving post to history: {e}")

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
