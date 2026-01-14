import json
import os
import random
import yaml
import datetime
import re
import requests
from typing import Dict, List, Any, Optional
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
        # Do NOT save to history here - will be saved after successful post
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
            # Found a valid topic - update index but DON'T save to history yet
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
            
            # Do NOT save to history here - will be saved after successful post
            return topic
            
    # If all on cooldown, just return the next one anyway to avoid breaking
    idx = (start_idx + 1) % len(niches)
    selected_topic = niches[idx]
    # Do NOT save to history here - will be saved after successful post
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
    """Load engagement metrics from history."""
    try:
        if os.path.exists(METRICS_HISTORY_PATH):
            with open(METRICS_HISTORY_PATH, "r") as f:
                return json.load(f)
        return {"posts": []}
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


def get_best_performing_template(engagement_metrics: Dict) -> Optional[Dict]:
    """Determine best performing template based on engagement metrics."""
    if not engagement_metrics or "posts" not in engagement_metrics or not engagement_metrics["posts"]:
        return None
    
    template_performance = {}
    
    for post in engagement_metrics["posts"]:
        template_id = post.get("template_id", 0)
        engagement = post.get("engagement", {})
        
        total_engagement = (
            engagement.get("likes", 0) * 1 +
            engagement.get("comments", 0) * 3 +
            engagement.get("shares", 0) * 5
        )
        
        if template_id not in template_performance:
            template_performance[template_id] = {
                "total_engagement": 0,
                "count": 0
            }
        
        template_performance[template_id]["total_engagement"] += total_engagement
        template_performance[template_id]["count"] += 1
    
    best_template_id = 0
    best_avg_engagement = -1
    
    for template_id, performance in template_performance.items():
        try:
            avg_engagement = performance["total_engagement"] / performance["count"] if performance["count"] > 0 else 0
        except Exception as e:
            logger.warning(f"Error calculating average engagement: {str(e)}")
            avg_engagement = 0
        
        if avg_engagement > best_avg_engagement:
            best_avg_engagement = avg_engagement
            best_template_id = template_id
    
    return {"template_id": best_template_id, "avg_engagement": best_avg_engagement}


def get_next_topic_strategy() -> Dict:
    """Determine next topic and template based on content strategy."""
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
                "priority_score": 10
            }
            
        # 2. Trending Topics (30% chance OR if no niches)
        # We increase chance to get more "news" style content
        use_trending = random.random() < 0.3
        
        if use_trending:
            try:
                trending_topics = fetch_trending_ai_topics()
                if trending_topics:
                    selection = random.choice(trending_topics)
                    topic = selection["topic"]
                    # Do NOT save to history here - will be saved after successful post
                    logger.info(f"Content strategy: Using trending AI topic: {topic}")
                    return {
                        "source": "trending",
                        "topic": topic,
                        "context": selection.get("context", ""),
                        "template": None,
                        "priority_score": 9
                    }
            except Exception as e:
                logger.error(f"Error checking trending topics: {e}")

        # 3. Niche Topics (Standard Rotation)
        # Note: get_next_niche_round_robin now saves to history internally
        niches = config.get("niches", [])
        if niches:
            try:
                next_niche = get_next_niche_round_robin()
                logger.info("Content strategy: Using niche topic (round-robin)")
                return {
                    "source": "niche",
                    "topic": next_niche,
                    "template": None,
                    "priority_score": 8
                }
            except Exception as e:
                logger.error(f"Error getting niche topic: {str(e)}")
        
        # 4. Fallback: Trending (if we skipped it earlier but have no niches)
        if not use_trending:
             try:
                trending_topics = fetch_trending_ai_topics()
                if trending_topics:
                    selection = random.choice(trending_topics)
                    topic = selection["topic"]
                    # Do NOT save to history here - will be saved after successful post
                    return {
                        "source": "trending",
                        "topic": topic,
                        "context": selection.get("context", ""),
                        "priority_score": 7
                    }
             except Exception:
                 pass
        
    except Exception as e:
        logger.error(f"Critical error in content strategy: {str(e)}")
    
    logger.info("Content strategy: Using generic AI topic fallback")
    fallback_topic = "Artificial Intelligence and Machine Learning"
    # Do NOT save to history here - will be saved after successful post
    return {
        "source": "fallback",
        "topic": fallback_topic,
        "template": None,
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
            "topic": "Artificial Intelligence and Machine Learning",
            "template": None,
            "priority_score": 1
        }