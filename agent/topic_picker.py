import random
import yaml
import datetime
import os
import logging
import re
from typing import Dict, List, Any, Optional

from agent.seo_optimizer import optimize_post

logger = logging.getLogger("linkedin-agent")

_last_template_index = -1
_current_series = {}


def get_weekday_topic() -> Dict[str, Any]:
    """Get topic based on current weekday from calendar.yaml."""
    global _current_series
    
    calendar_path = "agent/calendar.yaml"
    if not os.path.exists(calendar_path):
        weekday = datetime.datetime.now().weekday()
        weekday_topics = {
            0: "GenAI for Drug Discovery",
            1: "AI Case Studies",
            2: "MLOps Tips",
            3: "AI Explainability",
            4: "AI Tooling and Stacks",
            5: "Personal AI Learning",
            6: "Weekly AI Recap"
        }
        return {
            "primary_topic": weekday_topics.get(weekday, "Artificial Intelligence"),
            "subtopic": None,
            "post_type": "general",
            "part": 1,
            "total": 1
        }
    
    try:
        with open(calendar_path, "r") as f:
            calendar = yaml.safe_load(f)
    except Exception as e:
        logger.warning(f"Failed to load calendar: {e}")
        return {
            "primary_topic": "Artificial Intelligence",
            "subtopic": None,
            "post_type": "general",
            "part": 1,
            "total": 1
        }
    
    weekday = datetime.datetime.now().weekday()
    day_config = calendar.get("weekly_schedule", {}).get(str(weekday))
    
    if not day_config:
        return {
            "primary_topic": "Artificial Intelligence",
            "subtopic": None,
            "post_type": "general",
            "part": 1,
            "total": 1
        }
    
    primary_topic = day_config["primary_topic"]
    post_type = day_config.get("post_type", "general")
    series_length = day_config.get("series_length", 1)
    
    if str(weekday) not in _current_series:
        _current_series[str(weekday)] = {
            "current_subtopic_index": 0,
            "current_part": 1
        }
    
    subtopics = day_config.get("subtopics", [])
    if not subtopics:
        subtopic = primary_topic
    else:
        subtopic_index = _current_series[str(weekday)]["current_subtopic_index"]
        subtopic = subtopics[subtopic_index % len(subtopics)]
    
    part = _current_series[str(weekday)]["current_part"]
    
    _current_series[str(weekday)]["current_part"] += 1
    if _current_series[str(weekday)]["current_part"] > series_length:
        _current_series[str(weekday)]["current_subtopic_index"] += 1
        _current_series[str(weekday)]["current_part"] = 1
    
    return {
        "primary_topic": primary_topic,
        "subtopic": subtopic,
        "post_type": post_type,
        "part": part,
        "total": series_length
    }


def generate_smart_hashtags(topic: str) -> List[str]:
    """Generate smart, diverse hashtags based on topic."""
    base_tags = ["#AI", "#MachineLearning"]
    
    topic_words = [word for word in topic.split() if len(word) > 3]
    topic_tags = [f"#{word.replace(' ', '')}" for word in topic_words[:2]]
    
    niche_tags = [
        "#DrugDiscovery", "#ComputationalBiology", "#Bioinformatics",
        "#GenerativeAI", "#MLOps", "#AIResearch", "#DeepLearning"
    ]
    
    broad_tags = [
        "#DataScience", "#Tech", "#Innovation", "#ArtificialIntelligence"
    ]
    
    selected_niche = random.sample(niche_tags, min(2, len(niche_tags)))
    selected_broad = random.sample(broad_tags, min(1, len(broad_tags)))
    
    all_tags = base_tags + topic_tags + selected_niche + selected_broad
    
    seen = set()
    unique_tags = []
    for tag in all_tags:
        tag_lower = tag.lower()
        if tag_lower not in seen:
            unique_tags.append(tag)
            seen.add(tag_lower)
    
    return unique_tags[:6]


from .llm_generator import generate_post as llm_generate_post


def get_niche_post(topic: Optional[str] = None, template: Optional[Dict[str, str]] = None, 
                   force_template_rotation: bool = False, context: str = "") -> Dict[str, Any]:
    """Generate a niche topic post via LLM with graceful fallback."""
    try:
        with open("agent/config.yaml", "r") as f:
            cfg = yaml.safe_load(f)
    except Exception as e:
        logger.warning(f"Failed to load config: {e}")
        cfg = {"niches": ["Artificial Intelligence"]}
    
    if topic:
        primary_topic = topic
        subtopic = topic
        post_type = "general"
        part = 1
        total = 1
    elif random.random() < 0.7:
        topic_info = get_weekday_topic()
        primary_topic = topic_info["primary_topic"]
        subtopic = topic_info["subtopic"] or primary_topic
        post_type = topic_info["post_type"]
        part = topic_info["part"]
        total = topic_info["total"]
    else:
        niches = cfg.get("niches", ["Artificial Intelligence"])
        if not niches:
            niches = ["Artificial Intelligence"]
        primary_topic = random.choice(niches)
        subtopic = primary_topic
        part = 1
        total = 1
        post_type = "general"
    
    try:
        llm_post = llm_generate_post(niche=primary_topic, context=context)
        if llm_post:
            return {
                **llm_post,
                "primary_topic": primary_topic,
                "subtopic": subtopic,
                "part": part,
                "total": total
            }
    except Exception as e:
        logger.error(f"LLM generation failed: {e}")
    
    hashtags = generate_smart_hashtags(primary_topic)
    hashtags_str = " ".join(hashtags)
    
    fallback_body = f"""I've been exploring {primary_topic} lately and wanted to share some thoughts.

The field is evolving rapidly, with new applications emerging across industries. What's particularly exciting is how these advances are making once-theoretical concepts practical and accessible.

For teams working in this space, the key is balancing innovation with pragmatic implementation. Start small, measure impact, and iterate based on real-world feedback.

What's your experience with {primary_topic}? I'd love to hear what challenges or breakthroughs you've encountered.

{hashtags_str}"""
    
    seo_score, seo_keywords = optimize_post(fallback_body)
    
    return {
        "title": f"Insights on {primary_topic}",
        "body": fallback_body.strip(),
        "seo_score": seo_score,
        "seo_keywords": seo_keywords,
        "hashtags": hashtags,
        "primary_topic": primary_topic,
        "subtopic": subtopic,
        "part": part,
        "total": total
    }