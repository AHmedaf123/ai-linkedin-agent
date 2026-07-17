import json
import os
import random
import yaml
import datetime
import re
import requests
from typing import Dict, List, Any, Optional, Tuple
from agent import storage
from agent.logging_setup import get_logger

logger = get_logger("content_strategy")

REPO_QUEUE_PATH = "agent/repo_queue.json"
USED_REPOS_PATH = "agent/used_repos.json"
CONFIG_PATH = "agent/config.yaml"
CALENDAR_PATH = "agent/calendar.yaml"
METRICS_HISTORY_PATH = "agent/metrics_history.json"
NICHE_INDEX_PATH = "agent/niche_index.json"
TOPIC_HISTORY_PATH = "agent/topic_history.json"


def load_niches_list() -> List[str]:
    """Load niche topics from config."""
    cfg = load_config()
    niches = cfg.get("niches", [])
    return [n for n in niches if isinstance(n, str) and n.strip()]


def load_topic_history() -> List[Dict]:
    """Load history of used topics with timestamps."""
    if os.path.exists(TOPIC_HISTORY_PATH):
        try:
            with open(TOPIC_HISTORY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading topic history: {e}")
    return []


def save_topic_history(topic: str):
    """Save used topic to history."""
    history = load_topic_history()
    history.append({
        "topic": topic,
        "timestamp": datetime.datetime.now().isoformat()
    })
    # Keep last 50 topics
    if len(history) > 50:
        history = history[-50:]
        
    try:
        with open(TOPIC_HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving topic history: {e}")


def is_topic_cooldown(topic: str, days: int = 7) -> bool:
    """Check if topic is on cooldown (used recently)."""
    history = load_topic_history()
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    
    for entry in history:
        entry_time = datetime.datetime.fromisoformat(entry["timestamp"])
        if entry["topic"] == topic and entry_time > cutoff:
            return True
            
    return False


def get_next_category() -> str:
    """Plain round robin over the fixed content categories (config.yaml niches:
    AI Research & New Advancements / AI Engineering / AI Development).

    Repeating a category every 3rd day is expected and fine — a category is a
    broad bucket, not a topic. What must never repeat is the specific topic
    generated inside it (see get_next_fresh_topic), checked against full history.
    """
    categories = load_niches_list()
    if not categories:
        return "AI Engineering"

    idx = -1
    if os.path.exists(NICHE_INDEX_PATH):
        try:
            with open(NICHE_INDEX_PATH, "r", encoding="utf-8") as f:
                idx = int(json.load(f).get("index", -1))
        except Exception as e:
            logger.warning(f"Failed to load category index: {e}")
            idx = -1

    idx = (idx + 1) % len(categories)
    try:
        with open(NICHE_INDEX_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "index": idx,
                "category": categories[idx],
                "updated_at": datetime.datetime.now().isoformat()
            }, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save category index: {e}")

    return categories[idx]


def load_config() -> Dict:
    """Load configuration from config.yaml."""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Error loading config: {str(e)}")
        return {"niches": []}


def load_calendar() -> Dict:
    """Load calendar configuration."""
    try:
        with open(CALENDAR_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Error loading calendar: {str(e)}")
        return {"weekly_schedule": {}}


def load_repo_queue() -> List[str]:
    """Load pending repositories from queue."""
    try:
        if os.path.exists(REPO_QUEUE_PATH):
            with open(REPO_QUEUE_PATH, "r") as f:
                data = json.load(f)
                return data.get("pending_repos", [])
        return []
    except Exception as e:
        logger.error(f"Error loading repo queue: {str(e)}")
        return []


def load_used_repos() -> List[str]:
    """Load used repositories list."""
    try:
        if os.path.exists(USED_REPOS_PATH):
            with open(USED_REPOS_PATH, "r") as f:
                return json.load(f)
        return []
    except Exception as e:
        logger.error(f"Error loading used repos: {str(e)}")
        return []


def load_engagement_metrics() -> Dict:
    """Load engagement metrics from persistent storage."""
    try:
        return {"posts": storage.get_posts_with_engagement(100)}
    except Exception as e:
        logger.error(f"Error loading engagement metrics: {str(e)}")
        return {"posts": []}


def fetch_trending_ai_topics() -> List[Dict]:
    """Fetch trending AI topics from ArXiv API."""
    try:
        # Query for recent AI/ML papers
        url = "http://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.LG&sortBy=submittedDate&sortOrder=descending&max_results=10"
        response = requests.get(url, timeout=10)
        
        if response.status_code != 200:
            logger.error(f"ArXiv API returned {response.status_code}")
            return []
        
        content = response.text
        topics = []
        
        # Simple regex parsing (robust enough for our needs)
        entries = re.findall(r"<entry>.*?</entry>", content, re.DOTALL)
        
        for entry in entries[:5]:
            title_match = re.search(r"<title>(.*?)</title>", entry, re.DOTALL)
            summary_match = re.search(r"<summary>(.*?)</summary>", entry, re.DOTALL)
            
            if title_match and summary_match:
                title = title_match.group(1).replace("\n", " ").strip()
                summary = summary_match.group(1).replace("\n", " ").strip()
                
                # Check duplication against history using just the title (not the "New Research:" prefix)
                # This ensures the cooldown check matches what we'll save to history
                if not is_topic_cooldown(title, days=14):  # Stricter check for specific papers
                    topics.append({
                        "topic": title,  # Use plain title for consistency
                        "context": summary[:500],  # Pass summary for context
                        "source": "arxiv",
                        "timestamp": datetime.datetime.now().isoformat()
                    })
        
        return topics
    except Exception as e:
        logger.error(f"Error fetching trending topics: {str(e)}")
        return []


def get_best_performing_template(engagement_metrics: Dict = None) -> Optional[Dict]:
    """Best performing template_id based on measured engagement (from storage)."""
    try:
        template_perf = storage.get_template_performance()
        if not template_perf:
            return None
        best_id, best = max(template_perf.items(), key=lambda kv: kv[1]["avg_score"])
        return {"template_id": best_id, "avg_engagement": best["avg_score"], "post_count": best["count"]}
    except Exception as e:
        logger.warning(f"Error computing best template: {str(e)}")
        return None


TOPIC_SIMILARITY_GUARD = 0.45  # strict: catches a reword/narrower-slice, not just a near-duplicate
MAX_TOPIC_GEN_ATTEMPTS = 4


def _all_used_topics() -> List[str]:
    """Every topic ever posted (topic_history.json keeps the last 50)."""
    return [h["topic"] for h in load_topic_history()]


def _is_reword_of_past_topic(topic: str, used: List[str]) -> Tuple[bool, float]:
    if not used:
        return False, 0.0
    from agent.deduper import _tfidf_max_similarity
    sim, _ = _tfidf_max_similarity(topic, used)
    return sim > TOPIC_SIMILARITY_GUARD, sim


def _fresh_research_topic(used: List[str]) -> Optional[str]:
    """Real, currently-published AI research/news from ArXiv — a different paper
    each time, so it can't repeat or reword anything by construction."""
    for candidate in fetch_trending_ai_topics():
        topic = candidate["topic"]
        is_reword, sim = _is_reword_of_past_topic(topic, used)
        if not is_reword:
            save_topic_history(topic)
            logger.info(f"Content strategy: fresh research topic from ArXiv: {topic}")
            return topic
    return None


def _fresh_generated_topic(category: str, used: List[str]) -> Optional[str]:
    """Ask the LLM for one brand-new, narrow topic inside `category`, rejecting
    anything that repeats or reworks a topic already used (checked against the
    full topic history, not just recent entries)."""
    from agent.llm_generator import LLMGenerator

    for attempt in range(MAX_TOPIC_GEN_ATTEMPTS):
        avoid_block = "\n".join(f"- {t}" for t in used[-40:]) or "(none yet)"
        prompt = (
            "Generate ONE new, specific, narrow topic for a LinkedIn post about AI, "
            f"inside this category: {category}.\n\n"
            "It must be concrete and narrow enough that one practical post can cover it "
            "(not a broad area, not a rehash of something already covered).\n\n"
            "Topics already used — your topic must be about a genuinely different idea, "
            f"NOT a reworded, renamed, or narrower version of any of these:\n{avoid_block}\n\n"
            "Reply with just the topic line, under 12 words, no quotes, no trailing punctuation."
        )
        try:
            raw = LLMGenerator._call_openrouter(
                [{"role": "user", "content": prompt}], max_tokens=40, temperature=0.9
            )
        except Exception as e:
            logger.warning(f"Topic generation call failed (attempt {attempt + 1}): {e}")
            continue

        topic = raw.strip().splitlines()[0].strip().strip('"').strip()
        topic = re.sub(r"[.#]+$", "", topic).strip()
        if not (3 <= len(topic) <= 120):
            continue

        is_reword, sim = _is_reword_of_past_topic(topic, used)
        if is_reword:
            logger.info(f"Generated topic too close to a past topic (sim={sim:.2f}), retrying: {topic}")
            used = used + [topic]  # don't let the next attempt drift back to this one
            continue

        save_topic_history(topic)
        logger.info(f"Content strategy: fresh generated topic in '{category}': {topic}")
        return topic

    return None


def get_next_fresh_topic() -> Dict[str, str]:
    """Pick the next content category (round robin over the 3 fixed categories in
    config.yaml) and produce a specific topic inside it that has never been used
    before and is not a reword of a past topic.
    """
    category = get_next_category()
    used = _all_used_topics()

    topic = None
    if category.strip().lower().startswith("ai research"):
        topic = _fresh_research_topic(used)
    if not topic:
        topic = _fresh_generated_topic(category, used)
    if not topic:
        # Last resort: timestamp makes it impossible to literally collide.
        topic = f"{category} — {datetime.datetime.now().strftime('%Y-%m-%d')}"
        save_topic_history(topic)

    return {"category": category, "topic": topic}


def get_next_topic_strategy() -> Dict:
    """Determine next topic and template based on content strategy.

    Priority:
      1. Repo queue (if any)
      2. Fresh topic inside one of the 3 fixed content categories (AI Research &
         New Advancements / AI Engineering / AI Development), round robin over
         the category, always a brand-new specific topic that has never been
         used before and is not a reword of anything posted previously.
      3. Generic fallback
    """
    try:
        repo_queue = load_repo_queue()

        # 1. Repositories (Highest Priority)
        if repo_queue:
            logger.info("Content strategy: Using repository from queue")
            return {
                "source": "repo",
                "topic": repo_queue[0],
                "template": None,
                "template_id": "repo",
                "priority_score": 10
            }

        # 2. Fresh, never-repeated topic inside the current rotating category
        picked = get_next_fresh_topic()
        logger.info(f"Content strategy: category '{picked['category']}' -> topic '{picked['topic']}'")
        return {
            "source": "niche",
            "topic": picked["topic"],
            "template": None,
            "template_id": "niche",
            "priority_score": 8
        }

    except Exception as e:
        logger.error(f"Critical error in content strategy: {str(e)}")

    logger.info("Content strategy: Using generic AI topic fallback")
    fallback_topic = "Practical LLM Engineering"
    save_topic_history(fallback_topic)
    return {
        "source": "fallback",
        "topic": fallback_topic,
        "template": None,
        "template_id": "fallback",
        "priority_score": 1
    }


def get_next_content_strategy():
    """Main function to get the next content strategy."""
    try:
        strategy = get_next_topic_strategy()
        
        logger.info(
            f"Selected content strategy: {strategy['source']} - {strategy['topic']} "
            f"(priority: {strategy['priority_score']})"
        )
        
        return strategy
    except Exception as e:
        logger.error(f"Error in get_next_content_strategy: {str(e)}")
        return {
            "source": "fallback",
            "topic": "Practical LLM Engineering",
            "template": None,
            "template_id": "fallback",
            "priority_score": 1
        }