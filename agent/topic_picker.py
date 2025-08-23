import random, yaml
import datetime
import os
import logging
from typing import Dict, List, Any, Optional
from agent.seo_optimizer import optimize_post

# Local logger
logger = logging.getLogger("linkedin-agent")

# Template variations for different post styles
POST_TEMPLATES = [
    # Template 1: Full structured (safe fallback)
    {
        "title_template": "Deep Dive: {topic}",
        "body_template": """Hook: A quick, clear reason {topic} matters right now.  

Context/Story: What it is, why it’s relevant, and where it’s making an impact. Add 2–3 lines to ground the reader.  

Insights/Value: Share 2–3 concrete takeaways, lessons, or data points. Keep it actionable.  

CTA: What’s your experience with {topic}? Which use case are you exploring?  

{hashtags}""",
    },
    # Template 2: Question-based
    {
        "title_template": "How is {topic} reshaping our future?",
        "body_template": """Hook: 🤔 How is {topic} reshaping our future?  

Context/Story: A quick snapshot of changes you’re seeing in the field.  

Insights/Value: 1) A real use case  2) A pitfall to avoid  3) A quick win.  

CTA: What changes have you noticed due to {topic}?  

{hashtags}""",
    },
    # Template 3: List-based
    {
        "title_template": "5 Game-Changing Trends in {topic}",
        "body_template": """Hook: 📊 {topic} is moving fast—here are 5 trends to watch.  

Context/Story: Why these trends matter now.  

Insights/Value: 1) Trend 1  2) Trend 2  3) Trend 3  4) Trend 4  5) Trend 5  

CTA: Which trend resonates most with your work?  

{hashtags}""",
    },
]

# Last used template index (for rotation)
_last_template_index = -1

# Track series continuity
_current_series = {}

def get_weekday_topic() -> Dict[str, Any]:
    """Get topic based on current weekday from calendar.yaml
    
    Returns:
        Dict containing topic, subtopic, post type, and series information
    """
    global _current_series
    
    # Load calendar configuration
    calendar_path = "agent/calendar.yaml"
    if not os.path.exists(calendar_path):
        # Fallback if calendar.yaml doesn't exist
        weekday = datetime.datetime.now().weekday()
        weekday_topics = {
            0: "GenAI for Drug Discovery",  # Monday
            1: "AI Case Studies",          # Tuesday
            2: "MLOps Tips",               # Wednesday
            3: "AI Explainability",        # Thursday
            4: "AI Tooling and Stacks",    # Friday
            5: "Personal AI Learning",     # Saturday
            6: "Weekly AI Recap"           # Sunday
        }
        return {
            "primary_topic": weekday_topics.get(weekday, "Artificial Intelligence"),
            "subtopic": None,
            "post_type": "general",
            "part": 1,
            "total": 1
        }
    
    # Load calendar configuration
    with open(calendar_path, "r") as f:
        calendar = yaml.safe_load(f)
    
    # Get current weekday
    weekday = datetime.datetime.now().weekday()
    
    # Get day configuration
    day_config = calendar["weekly_schedule"].get(str(weekday))
    if not day_config:
        return {
            "primary_topic": "Artificial Intelligence",
            "subtopic": None,
            "post_type": "general",
            "part": 1,
            "total": 1
        }
    
    # Get primary topic
    primary_topic = day_config["primary_topic"]
    
    # Get post type
    post_type = day_config.get("post_type", "general")
    
    # Get series length
    series_length = day_config.get("series_length", 1)
    
    # Initialize series tracking for this weekday if not exists
    if str(weekday) not in _current_series:
        _current_series[str(weekday)] = {
            "current_subtopic_index": 0,
            "current_part": 1
        }
    
    # Get subtopics
    subtopics = day_config.get("subtopics", [])
    if not subtopics:
        subtopic = primary_topic
    else:
        # Get current subtopic index
        subtopic_index = _current_series[str(weekday)]["current_subtopic_index"]
        subtopic = subtopics[subtopic_index % len(subtopics)]
    
    # Get current part in series
    part = _current_series[str(weekday)]["current_part"]
    
    # Update series tracking for next time
    _current_series[str(weekday)]["current_part"] += 1
    if _current_series[str(weekday)]["current_part"] > series_length:
        # Move to next subtopic and reset part
        _current_series[str(weekday)]["current_subtopic_index"] += 1
        _current_series[str(weekday)]["current_part"] = 1
    
    return {
        "primary_topic": primary_topic,
        "subtopic": subtopic,
        "post_type": post_type,
        "part": part,
        "total": series_length
    }

def get_template(force_rotation: bool = False) -> Dict[str, str]:
    """Get a post template, with optional forced rotation"""
    global _last_template_index
    
    if force_rotation or _last_template_index == -1:
        # Force a different template than the last one used
        available_indices = list(range(len(POST_TEMPLATES)))
        if _last_template_index != -1:
            available_indices.remove(_last_template_index)
        
        _last_template_index = random.choice(available_indices)
    else:
        # Random template selection
        _last_template_index = random.randint(0, len(POST_TEMPLATES) - 1)
    
    return POST_TEMPLATES[_last_template_index]

def generate_hashtags(topic: str) -> str:
    """Generate hashtags based on topic"""
    # Base hashtags that should be included
    base_tags = ["#AI", "#MachineLearning"]
    
    # Topic-specific hashtags
    topic_words = topic.split()
    topic_tags = [f"#{word.replace(' ', '')}" for word in topic_words if len(word) > 3]
    
    # Additional relevant hashtags pool
    additional_tags_pool = [
        "#DeepLearning", "#DataScience", "#NLP", "#ComputerVision", 
        "#Innovation", "#Tech", "#GenerativeAI", "#AIEthics",
        "#BigData", "#Analytics", "#Python", "#TensorFlow", "#PyTorch"
    ]
    
    # Select a few random additional tags
    additional_tags = random.sample(additional_tags_pool, min(3, len(additional_tags_pool)))
    
    # Combine all hashtags, ensuring no duplicates
    all_tags = base_tags + topic_tags + additional_tags
    unique_tags = list(dict.fromkeys(all_tags))  # Remove duplicates while preserving order
    
    # Limit to a reasonable number of hashtags (5-7)
    if len(unique_tags) > 7:
        unique_tags = unique_tags[:7]
    
    return " ".join(unique_tags)

def get_calendar_template(post_type: str) -> Dict[str, str]:
    """Get template from calendar.yaml based on post type
    
    Args:
        post_type: Type of post (how-to, case-study, etc.)
        
    Returns:
        Dict containing title and body templates
    """
    calendar_path = "agent/calendar.yaml"
    if not os.path.exists(calendar_path):
        # Fallback to default templates
        return {
            "title_template": "Deep Dive: {topic}",
            "body_template": """💡 Let's talk about **{topic}** today.  
Exploring practical applications, challenges, and future opportunities in this exciting field.

{hashtags}"""
        }
    
    # Load calendar configuration
    with open(calendar_path, "r") as f:
        calendar = yaml.safe_load(f)
    
    # Get templates for post type
    templates = calendar.get("post_templates", {})
    template = templates.get(post_type, {})
    
    if not template:
        # Fallback to default template if post type not found
        return {
            "title_template": "Deep Dive: {topic}",
            "body_template": """💡 Let's talk about **{topic}** today.  
Exploring practical applications, challenges, and future opportunities in this exciting field.

{hashtags}"""
        }
    
    return template

from .llm_generator import generate_post as llm_generate_post

def get_niche_post(topic: Optional[str] = None, template: Optional[Dict[str, str]] = None, force_template_rotation: bool = False) -> Dict[str, Any]:
    """Generate a niche topic post via LLM with graceful fallback to templates.
    
    Args:
        topic: Optional specific topic to use (overrides calendar/random selection)
        template: Optional specific template to use (overrides calendar/random selection)
        force_template_rotation: If True, force a different template than the last one used
        
    Returns:
        Dict containing post details
    """
    # Get configuration
    cfg = yaml.safe_load(open("agent/config.yaml"))
    
    # If topic is provided, use it directly
    if topic:
        primary_topic = topic
        subtopic = topic
        part = 1
        total = 1
        # No template selection needed if LLM succeeds
    # Otherwise, get topic based on weekday calendar (70% chance) or random choice from config (30% chance)
    elif random.random() < 0.7:  # 70% chance to use weekday-based topic
        topic_info = get_weekday_topic()
        primary_topic = topic_info["primary_topic"]
        subtopic = topic_info["subtopic"] or primary_topic
        post_type = topic_info["post_type"]
        part = topic_info["part"]
        total = topic_info["total"]
    else:
        # Random topic from config
        primary_topic = random.choice(cfg["niches"])
        subtopic = primary_topic
        part = 1
        total = 1
    
    # Try LLM generation first
    try:
        llm_post = llm_generate_post(niche=primary_topic)
        if llm_post:
            # Ensure required fields
            return {
                **llm_post,
                "primary_topic": primary_topic,
                "subtopic": subtopic,
                "part": part,
                "total": total,
            }
    except Exception as e:
        # Fall back to templates below
        pass
    
    # Fallback: use templates with generated hashtags
    if template is None:
        # If we know post_type from calendar, use it; else rotate default
        try:
            template = get_calendar_template(post_type)  # type: ignore[name-defined]
        except Exception:
            template = get_template(force_template_rotation)
    
    # Generate hashtags
    hashtags = generate_hashtags(primary_topic)
    
    # Fill in template
    try:
        title = template["title_template"].format(topic=primary_topic, subtopic=subtopic, part=part, total=total)
        body = template["body_template"].format(topic=primary_topic, subtopic=subtopic, hashtags=hashtags, part=part, total=total)
    except KeyError as e:
        # Fallback if template formatting fails
        logger.warning(f"Template formatting error: {str(e)}. Using fallback template.")
        title = f"Deep Dive: {primary_topic}"
        body = f"""💡 Let's talk about **{primary_topic}** today.  
Exploring practical applications, challenges, and future opportunities in this exciting field.

{hashtags}"""
    
    # Optimize post for SEO
    seo_score, seo_keywords = optimize_post(body)
    
    return {
        "title": title,
        "body": body.strip(),
        "seo_score": seo_score,
        "seo_keywords": seo_keywords,
        "hashtags": hashtags.split(),
        "primary_topic": primary_topic,
        "subtopic": subtopic,
        "part": part,
        "total": total
    }