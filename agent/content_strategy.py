import json
import os
import random
import yaml
import datetime
import requests
from typing import Dict, List, Any, Optional
from agent.logging_setup import get_logger

# Initialize logger
logger = get_logger("content_strategy")

# Constants
REPO_QUEUE_PATH = "agent/repo_queue.json"
USED_REPOS_PATH = "agent/used_repos.json"
CONFIG_PATH = "agent/config.yaml"
CALENDAR_PATH = "agent/calendar.yaml"
METRICS_HISTORY_PATH = "agent/metrics_history.json"
NICHE_INDEX_PATH = "agent/niche_index.json"

# --- Round-robin niche helpers ---
def load_niches_list() -> List[str]:
    cfg = load_config()
    niches = cfg.get("niches", [])
    return [n for n in niches if isinstance(n, str) and n.strip()]

def get_next_niche_round_robin() -> str:
    niches = load_niches_list()
    if not niches:
        return "Artificial Intelligence"
    # Read current index
    idx = -1
    if os.path.exists(NICHE_INDEX_PATH):
        try:
            with open(NICHE_INDEX_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                idx = int(data.get("index", -1))
        except (OSError, IOError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to load niche index: {str(e)}")
            idx = -1
    # Advance and wrap
    idx = (idx + 1) % len(niches)
    # Persist new index
    try:
        with open(NICHE_INDEX_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "index": idx,
                "topic": niches[idx],
                "niches_count": len(niches),
                "updated_at": datetime.datetime.now().isoformat()
            }, f, indent=2)
    except (OSError, IOError, json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning(f"Failed to save niche index: {str(e)}")
    return niches[idx]

# Post template variations
POST_TEMPLATES = [
    # Template 1: Full structured (safe fallback)
    {
        "title_template": "Deep Dive: {topic}",
        "body_template": """Hook: A quick, clear reason {topic} matters right now.  

Context/Story: What it is, why it’s relevant, and where it’s making an impact. Add 2–3 lines to ground the reader.  

Insights/Value: Share 2–3 concrete takeaways, lessons, or data points. Keep it actionable.  

CTA: What’s your experience with {topic}? Which use case are you exploring?  

#AI #MachineLearning {hashtags}""",
    },
    # Template 2: Question-based
    {
        "title_template": "Question: How is {topic} changing our world?",
        "body_template": """Hook: 🤔 Have you considered how {topic} is transforming industries?  

Context/Story: I've been researching this area and found practical patterns worth sharing.  

Insights/Value: 1) A real use case. 2) A pitfall to avoid. 3) A quick win to try this week.  

CTA: What’s one challenge you’ve faced with {topic}?  

{hashtags}""",
    },
    # Template 3: List-based
    {
        "title_template": "Top 3 Trends in {topic} for {year}",
        "body_template": """Hook: 📊 {topic} is evolving fast—here are 3 trends to watch.  

Context/Story: Why these trends matter and who benefits.  

Insights/Value: 1) Trend A  2) Trend B  3) Trend C  

CTA: Which trend resonates most with your work?  

{hashtags}""",
    },
    # Template 4: Personal insight
    {
        "title_template": "My Thoughts on {topic}",
        "body_template": """Hook: 🧠 A surprising lesson I learned working with {topic}.  

Context/Story: Brief scenario and what changed my approach.  

Insights/Value: 3 practical tips or principles others can reuse.  

CTA: What would you add from your experience?  

{hashtags}""",
    },
    # Template 5: News-based
    {
        "title_template": "Latest Developments in {topic}",
        "body_template": """Hook: 📰 A notable update in {topic} you should know.  

Context/Story: What changed and why it matters right now.  

Insights/Value: Who’s doing it well + one actionable takeaway.  

CTA: Are you experimenting with this yet?  

{hashtags}""",
    },
]


def load_config() -> Dict:
    """Load configuration from config.yaml"""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except (OSError, IOError, yaml.YAMLError) as e:
        logger.error(f"Error loading config: {str(e)}")
        return {"niches": []}


def load_calendar() -> Dict:
    """Load calendar configuration from calendar.yaml"""
    try:
        with open(CALENDAR_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except (OSError, IOError, yaml.YAMLError) as e:
        logger.error(f"Error loading calendar: {str(e)}")
        return {"weekly_schedule": {}}


def load_repo_queue() -> List[str]:
    """Load pending repositories from repo_queue.json"""
    try:
        if os.path.exists(REPO_QUEUE_PATH):
            with open(REPO_QUEUE_PATH, "r") as f:
                data = json.load(f)
                return data.get("pending_repos", [])
        return []
    except (OSError, IOError, json.JSONDecodeError) as e:
        logger.error(f"Error loading repo queue: {str(e)}")
        return []


def load_used_repos() -> List[str]:
    """Load used repositories from used_repos.json"""
    try:
        if os.path.exists(USED_REPOS_PATH):
            with open(USED_REPOS_PATH, "r") as f:
                return json.load(f)
        return []
    except (OSError, IOError, json.JSONDecodeError) as e:
        logger.error(f"Error loading used repos: {str(e)}")
        return []


def load_engagement_metrics() -> Dict:
    """Load engagement metrics from metrics_history.json"""
    try:
        if os.path.exists(METRICS_HISTORY_PATH):
            with open(METRICS_HISTORY_PATH, "r") as f:
                return json.load(f)
        return {"posts": []}
    except (OSError, IOError, json.JSONDecodeError) as e:
        logger.error(f"Error loading engagement metrics: {str(e)}")
        return {"posts": []}


def fetch_trending_ai_topics() -> List[Dict]:
    """Fetch trending AI topics from ArXiv API"""
    try:
        # ArXiv API query for recent AI papers
        url = "http://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.LG&sortBy=submittedDate&sortOrder=descending&max_results=5"
        response = requests.get(url, timeout=10)
        
        if response.status_code != 200:
            logger.error(f"Error fetching ArXiv data: {response.status_code}")
            return []
        
        # Simple XML parsing (in production, use a proper XML parser)
        content = response.text
        topics = []
        
        # Extract titles from the response
        import re
        titles = re.findall(r"<title>(.*?)</title>", content)
        # Skip the first title as it's the feed title
        for title in titles[1:6]:  # Get up to 5 paper titles
            # Clean up the title
            clean_title = title.replace("\n", " ").strip()
            topics.append({
                "topic": clean_title,
                "source": "arxiv",
                "timestamp": datetime.datetime.now().isoformat()
            })
        
        return topics
    except (requests.RequestException, OSError, IOError) as e:
        logger.error(f"Error fetching trending AI topics: {str(e)}")
        return []


def get_best_performing_template(engagement_metrics: Dict) -> Dict:
    """Determine the best performing template based on engagement metrics"""
    if not engagement_metrics or "posts" not in engagement_metrics or not engagement_metrics["posts"]:
        # If no metrics available, return a random template
        return random.choice(POST_TEMPLATES)
    
    # Calculate average engagement per template
    template_performance = {}
    
    for post in engagement_metrics["posts"]:
        template_id = post.get("template_id", 0)
        engagement = post.get("engagement", {})
        
        # Calculate total engagement (weighted sum)
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
    
    # Find the best performing template
    best_template_id = 0
    best_avg_engagement = -1
    
    for template_id, performance in template_performance.items():
        try:
            avg_engagement = performance["total_engagement"] / performance["count"] if performance["count"] > 0 else 0
        except (KeyError, ZeroDivisionError, TypeError) as e:
            logger.warning(f"Error calculating average engagement for template {template_id}: {str(e)}")
            avg_engagement = 0
        if avg_engagement > best_avg_engagement:
            best_avg_engagement = avg_engagement
            best_template_id = template_id
    
    # Return the best template, or a random one if the best is not found
    if 0 <= best_template_id < len(POST_TEMPLATES):
        return POST_TEMPLATES[best_template_id]
    else:
        return random.choice(POST_TEMPLATES)


def get_next_topic_strategy() -> Dict:
    """Determine the next topic and template based on the content strategy"""
    try:
        # Load necessary data
        repo_queue = load_repo_queue()
        used_repos = load_used_repos()
        config = load_config()
        calendar = load_calendar()
        engagement_metrics = load_engagement_metrics()
        
        # Strategy 1: If pending repos exist, choose next repo
        if repo_queue:
            logger.info("Content strategy: Using next repository from queue")
            return {
                "source": "repo",
                "topic": repo_queue[0],
                "template": get_best_performing_template(engagement_metrics),
                "priority_score": 10  # Highest priority
            }
        
        # Strategy 2: Use niche topics from config (round-robin order) — enforced
        niches = config.get("niches", [])
        if niches:
            try:
                next_niche = get_next_niche_round_robin()
                logger.info("Content strategy: Using niche topic from config (round-robin)")
                return {
                    "source": "niche",
                    "topic": next_niche,
                    "template": get_best_performing_template(engagement_metrics),
                    "priority_score": 9  # Prefer niches over calendar
                }
            except Exception as e:
                logger.error(f"Error getting niche topic: {str(e)}")

        # Strategy 3: If niches absent, try calendar topic
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
                        "template": get_best_performing_template(engagement_metrics),
                        "priority_score": 8
                    }
        except Exception as e:
            logger.error(f"Error processing calendar topic: {str(e)}")

        # Strategy 4: Fetch trending AI topics as fallback
        try:
            trending_topics = fetch_trending_ai_topics()
            if trending_topics:
                selected_topic = trending_topics[0]["topic"]
                logger.info("Content strategy: Using trending AI topic from ArXiv")
                return {
                    "source": "trending",
                    "topic": selected_topic,
                    "template": get_best_performing_template(engagement_metrics),
                    "priority_score": 4  # Lower priority
                }
        except Exception as e:
            logger.error(f"Error fetching trending topics: {str(e)}")
        
    except Exception as e:
        logger.error(f"Critical error in content strategy selection: {str(e)}")
    
    # Final fallback: Generic AI topic
    logger.info("Content strategy: Using generic AI topic as final fallback")
    return {
        "source": "fallback",
        "topic": "Artificial Intelligence and Machine Learning",
        "template": random.choice(POST_TEMPLATES),
        "priority_score": 2  # Lowest priority
    }


def get_next_content_strategy():
    """Main function to get the next content strategy"""
    try:
        strategy = get_next_topic_strategy()
        
        # Log the selected strategy
        logger.info(
            f"Selected content strategy: {strategy['source']} - {strategy['topic']} (priority: {strategy['priority_score']})"
        )
        
        return strategy
    except (KeyError, TypeError, ValueError) as e:
        logger.error(f"Data error in get_next_content_strategy: {str(e)}")
        return {
            "source": "fallback",
            "topic": "Artificial Intelligence and Machine Learning",
            "template": random.choice(POST_TEMPLATES),
            "priority_score": 1
        }
    except Exception as e:
        logger.error(f"Unexpected error in get_next_content_strategy: {str(e)}")
        return {
            "source": "fallback",
            "topic": "Artificial Intelligence and Machine Learning",
            "template": random.choice(POST_TEMPLATES),
            "priority_score": 1
        }