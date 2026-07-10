import json
import os
import random
import yaml
import datetime
import re
import requests
from typing import Dict, List, Any, Optional
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


def get_next_niche_round_robin() -> str:
    """Get next niche topic in round-robin order, skipping cooldown topics."""
    niches = load_niches_list()
    if not niches:
        fallback_topic = "Artificial Intelligence"
        save_topic_history(fallback_topic)
        return fallback_topic
    
    start_idx = -1
    if os.path.exists(NICHE_INDEX_PATH):
        try:
            with open(NICHE_INDEX_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                start_idx = int(data.get("index", -1))
        except Exception as e:
            logger.warning(f"Failed to load niche index: {e}")
            start_idx = -1
    
    # Try to find a valid topic (max loops = len(niches))
    for i in range(1, len(niches) + 1):
        idx = (start_idx + i) % len(niches)
        topic = niches[idx]
        
        if not is_topic_cooldown(topic):
            # Found a valid topic - save to history immediately
            try:
                with open(NICHE_INDEX_PATH, "w", encoding="utf-8") as f:
                    json.dump({
                        "index": idx,
                        "topic": topic,
                        "niches_count": len(niches),
                        "updated_at": datetime.datetime.now().isoformat()
                    }, f, indent=2)
            except Exception as e:
                logger.warning(f"Failed to save niche index: {e}")
            
            # Save to topic history BEFORE returning to prevent re-selection
            save_topic_history(topic)
            return topic
            
    # If all on cooldown, just return the next one anyway to avoid breaking
    idx = (start_idx + 1) % len(niches)
    selected_topic = niches[idx]
    save_topic_history(selected_topic)
    return selected_topic


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


def pick_niche_epsilon_greedy(epsilon: float = None) -> str:
    """Epsilon-greedy bandit over niches.

    Exploit (1-epsilon): the niche with the best average measured engagement
    that is not on cooldown. Explore (epsilon, or when no engagement data
    exists yet): fall back to the round-robin rotation.
    """
    if epsilon is None:
        epsilon = float(os.getenv("NICHE_BANDIT_EPSILON", "0.2"))

    niches = load_niches_list()
    if not niches:
        return get_next_niche_round_robin()

    try:
        perf = storage.get_topic_performance()
    except Exception as e:
        logger.warning(f"Could not load topic performance: {e}")
        perf = {}
    measured = {t: v for t, v in perf.items() if t in set(niches)}

    if measured and random.random() >= epsilon:
        ranked = sorted(measured.items(), key=lambda kv: kv[1]["avg_score"], reverse=True)
        for topic, stats in ranked:
            if not is_topic_cooldown(topic):
                logger.info(
                    f"Niche bandit (exploit): {topic} "
                    f"(avg engagement {stats['avg_score']:.1f} over {stats['count']} posts)"
                )
                save_topic_history(topic)
                return topic
        # every measured winner is on cooldown → explore instead

    logger.info("Niche bandit (explore): round-robin rotation")
    return get_next_niche_round_robin()


def generate_performance_driven_topic() -> Optional[str]:
    """Craft the next topic from what actually performed well — not a static pick.

    Uses the bounded topic-generation context (top/bottom angles + best topics)
    and the niche list as *seeds*, and asks the LLM to produce one specific,
    narrow sub-topic biased toward what worked. Returns None when there is no
    performance data yet or the LLM is unavailable (caller then falls back to the
    bandit over the seed list).
    """
    try:
        from agent.performance_digest import build_topic_generation_context
        ctx = build_topic_generation_context()
        if not ctx:
            return None  # no measured performance yet — let the bandit seed instead

        seeds = load_niches_list()
        available = [n for n in seeds if not is_topic_cooldown(n)] or seeds
        seed_block = "\n".join(f"- {s}" for s in available)

        from agent.llm_generator import LLMGenerator
        messages = [{
            "role": "user",
            "content": (
                "You choose the next LinkedIn post topic for a hands-on AI/ML engineer.\n\n"
                f"Broad seed areas you may draw from:\n{seed_block}\n\n"
                f"{ctx}\n\n"
                "Using ONLY what performed well above, choose or craft ONE specific, narrow "
                "sub-topic for the next post. Lean toward the angles/topics that worked and "
                "avoid the ones that flopped. It must be a concrete thing an engineer can tell "
                "a real story about (not a broad area). Reply with just the topic line, under "
                "12 words, no quotes, no trailing punctuation."
            ),
        }]
        raw = LLMGenerator._call_openrouter(messages, max_tokens=40, temperature=0.7)
        topic = raw.strip().splitlines()[0].strip().strip('"').strip()
        topic = re.sub(r"[.#]+$", "", topic).strip()
        if 3 <= len(topic) <= 120:
            logger.info(f"Content strategy: performance-driven generated topic: {topic}")
            save_topic_history(topic)
            return topic
    except Exception as e:
        logger.warning(f"Performance-driven topic generation failed: {e}")
    return None


def get_next_topic_strategy() -> Dict:
    """Determine next topic and template based on content strategy.

    Priority:
      1. Repo queue (if any)
      2. Performance-driven generated topic (once there is engagement data)
      3. Niche bandit over the seed list (exploit best niche, explore sometimes)
      4. Trending ArXiv (opt-in only — off by default for the practical-eng niche)
      5. Generic fallback
    """
    try:
        repo_queue = load_repo_queue()
        config = load_config()

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

        # 2. Performance-driven generated topic (derived from past reach/reactions)
        if os.getenv("ENABLE_DYNAMIC_TOPIC", "true").lower() == "true":
            generated = generate_performance_driven_topic()
            if generated:
                return {
                    "source": "niche",
                    "topic": generated,
                    "template": None,
                    "template_id": "generated",
                    "priority_score": 9
                }

        # 3. Niche Topics (epsilon-greedy bandit over measured engagement,
        #    falling back to round-robin while there is no data)
        niches = config.get("niches", [])
        if niches:
            try:
                next_niche = pick_niche_epsilon_greedy()
                logger.info("Content strategy: Using niche topic (bandit)")
                return {
                    "source": "niche",
                    "topic": next_niche,
                    "template": None,
                    "template_id": "niche",
                    "priority_score": 8
                }
            except Exception as e:
                logger.error(f"Error getting niche topic: {str(e)}")

        # 4. Trending ArXiv (opt-in: research-paper content clashes with the
        #    practical-engineering niche, so it is disabled by default)
        if os.getenv("ENABLE_TRENDING", "false").lower() == "true":
            try:
                trending_topics = fetch_trending_ai_topics()
                if trending_topics:
                    selection = random.choice(trending_topics)
                    topic = selection["topic"]
                    save_topic_history(topic)
                    logger.info(f"Content strategy: Using trending AI topic: {topic}")
                    return {
                        "source": "trending",
                        "topic": topic,
                        "context": selection.get("context", ""),
                        "template": None,
                        "template_id": "trending",
                        "priority_score": 7
                    }
            except Exception as e:
                logger.error(f"Error checking trending topics: {e}")

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