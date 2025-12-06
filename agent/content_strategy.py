import json
import os
import random
import yaml
import datetime
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


def load_niches_list() -> List[str]:
    """Load niche topics from config."""
    cfg = load_config()
    niches = cfg.get("niches", [])
    return [n for n in niches if isinstance(n, str) and n.strip()]


def get_next_niche_round_robin() -> str:
    """Get next niche topic in round-robin order."""
    niches = load_niches_list()
    if not niches:
        return "Artificial Intelligence"
    
    idx = -1
    if os.path.exists(NICHE_INDEX_PATH):
        try:
            with open(NICHE_INDEX_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                idx = int(data.get("index", -1))
        except Exception as e:
            logger.warning(f"Failed to load niche index: {str(e)}")
            idx = -1
    
    idx = (idx + 1) % len(niches)
    
    try:
        with open(NICHE_INDEX_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "index": idx,
                "topic": niches[idx],
                "niches_count": len(niches),
                "updated_at": datetime.datetime.now().isoformat()
            }, f, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save niche index: {str(e)}")
    
    return niches[idx]


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
        url = "http://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.LG&sortBy=submittedDate&sortOrder=descending&max_results=5"
        response = requests.get(url, timeout=10)
        
        if response.status_code != 200:
            logger.error(f"ArXiv API returned {response.status_code}")
            return []
        
        content = response.text
        topics = []
        
        titles = re.findall(r"<title>(.*?)</title>", content)
        
        for title in titles[1:6]:
            clean_title = title.replace("\n", " ").strip()
            if clean_title and len(clean_title) > 20:
                topics.append({
                    "topic": clean_title,
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
        calendar = load_calendar()
        engagement_metrics = load_engagement_metrics()
        
        if repo_queue:
            logger.info("Content strategy: Using repository from queue")
            return {
                "source": "repo",
                "topic": repo_queue[0],
                "template": None,
                "priority_score": 10
            }
        
        niches = config.get("niches", [])
        if niches:
            try:
                next_niche = get_next_niche_round_robin()
                logger.info("Content strategy: Using niche topic (round-robin)")
                return {
                    "source": "niche",
                    "topic": next_niche,
                    "template": None,
                    "priority_score": 9
                }
            except Exception as e:
                logger.error(f"Error getting niche topic: {str(e)}")
        
        try:
            weekday = datetime.datetime.now().weekday()
            weekly_schedule = calendar.get("weekly_schedule", {})
            
            if str(weekday) in weekly_schedule or weekday in weekly_schedule:
                day_key = str(weekday) if str(weekday) in weekly_schedule else weekday
                day_schedule = weekly_schedule[day_key]
                primary_topic = day_schedule.get("primary_topic", "")
                subtopics = day_schedule.get("subtopics", [])
                
                if primary_topic and subtopics:
                    selected_topic = f"{primary_topic}: {random.choice(subtopics)}"
                    logger.info(f"Content strategy: Using calendar topic for day {weekday}")
                    return {
                        "source": "calendar",
                        "topic": selected_topic,
                        "template": None,
                        "priority_score": 8
                    }
        except Exception as e:
            logger.error(f"Error processing calendar topic: {str(e)}")
        
        try:
            trending_topics = fetch_trending_ai_topics()
            if trending_topics:
                selected_topic = trending_topics[0]["topic"]
                logger.info("Content strategy: Using trending AI topic from ArXiv")
                return {
                    "source": "trending",
                    "topic": selected_topic,
                    "template": None,
                    "priority_score": 4
                }
        except Exception as e:
            logger.error(f"Error fetching trending topics: {str(e)}")
        
    except Exception as e:
        logger.error(f"Critical error in content strategy: {str(e)}")
    
    logger.info("Content strategy: Using generic AI topic fallback")
    return {
        "source": "fallback",
        "topic": "Artificial Intelligence and Machine Learning",
        "template": None,
        "priority_score": 2
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