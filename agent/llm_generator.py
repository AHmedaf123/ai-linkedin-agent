import os
import re
import json
import requests
from typing import Optional, Dict, Any, Tuple, List, Union
from datetime import datetime

# Assuming these modules exist and are functional
from .seo_optimizer import optimize_post_full  # ✅ Use new SEO optimizer
from .backlog_generator import fetch_repo_details

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-r1:free")

PROMPT_CONSTRAINTS = (
    "Follow these constraints for the LinkedIn post:\n"
    "- Length: 120–200 words, under 1,300 characters.\n"
    "- Tone: Authoritative, conversational, and deeply insightful.\n"
    "- Voice: Use first-person perspective ('I'm exploring...', 'We've seen...').\n"
    "- Structure: Start with an attention-grabbing hook, provide context/insights on a problem, share your unique perspective or solution, and end with a clear CTA.\n"
    "- Formatting: Use short, punchy paragraphs (1-2 sentences max). Use clean text with line breaks for readability. Do not use heavy markdown like bolding or italics for entire paragraphs.\n"
    "- Hashtags: 3–5 unique hashtags at the very end. Include a mix of broad, industry-specific, and niche tags.\n"
    "- Keywords: Naturally embed relevant domain keywords.\n"
)

def _load_api_key() -> Optional[str]:
    """Loads the API key from environment variables."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if api_key:
        return api_key
    try:
        from dotenv import load_dotenv
        load_dotenv()
        return os.getenv("OPENROUTER_API_KEY")
    except ImportError:
        return None

def _postprocess_content(text: str) -> Tuple[str, str, List[str]]:
    """Extracts a title, cleans the body, and gets up to 5 unique hashtags."""
    lines = [l.strip() for l in text.splitlines()]
    title = re.sub(r"^[#*\s]+", "", next((l for l in lines if l), "LinkedIn Update")).strip()
    tags = re.findall(r"(?i)#\w+", text)
    seen, hashtags = set(), []
    for t in tags:
        norm = t if t.startswith("#") else f"#{t}"
        if norm.lower() not in seen:
            hashtags.append(norm)
            seen.add(norm.lower())
        if len(hashtags) >= 5:
            break
    
    # Remove hashtags from the main body of the text
    body_lines = [line for line in lines if not re.match(r'^\s*#', line)]
    body = "\n".join(body_lines).strip()
    return title, body, hashtags

def _build_repo_prompt(repo_info: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Builds a detailed prompt for generating a LinkedIn post about a GitHub repository.
    The prompt is designed to elicit a more human-like, professional tone.
    """
    name, desc = repo_info.get("name", "Repository"), repo_info.get("desc") or "an AI-based project."
    readme_content, url, topics = repo_info.get("readme") or "", repo_info.get("url", ""), repo_info.get("topics") or []
    
    user_prompt = (
        "You are a professional software engineer and AI researcher. You've just completed a significant project "
        "and want to share your journey and insights on LinkedIn. "
        "Craft a compelling LinkedIn post that details the project, the problem it solves, and its key innovations.\n\n"
        f"**Project Details:**\n"
        f"Repo Name: {name}\n"
        f"Description: {desc}\n"
        f"Topics: {', '.join(topics)}\n"
        f"URL: {url}\n\n"
        f"**Project Context:**\n"
        f"{readme_content}\n\n"
        "**Instructions:**\n"
        f"Explain the problem you tackled and why it's important. Describe your unique approach or a core technical insight you gained. "
        f"End with a call to action that encourages engagement or a check-out of the repo. Do not sound like a generic press release. "
        f"Make it personal and relatable. Use a genuine, professional tone.\n\n"
        + PROMPT_CONSTRAINTS
    )
    return [
        {"role": "system", "content": "You are an expert in crafting concise, credible, and genuinely engaging LinkedIn content for professionals."},
        {"role": "user", "content": user_prompt}
    ]

def _build_niche_prompt(niche_topic: str) -> List[Dict[str, str]]:
    """
    Builds a prompt for a thought-leadership post on a niche topic.
    The prompt is designed to generate content that sounds like it comes from a subject matter expert.
    """
    user_prompt = (
        "You are a recognized thought leader in the intersection of AI and Drug Discovery. "
        f"Write a professional LinkedIn post about **{niche_topic}**. "
        "Focus on an emerging trend, a new use case, or a recent breakthrough in this area. "
        "The goal is to provide genuine value and establish authority.\n\n"
        "**Instructions:**\n"
        "Start with a strong question or statement to hook the reader. Provide context on the current state of the topic. "
        "Share a specific, forward-looking insight or a potential challenge. Conclude with a clear CTA that invites discussion. "
        "Do not use generic buzzwords; provide specific examples or concepts that demonstrate deep understanding.\n\n"
        + PROMPT_CONSTRAINTS
    )
    return [
        {"role": "system", "content": "You are an expert in crafting concise, credible, and genuinely engaging LinkedIn content for professionals."},
        {"role": "user", "content": user_prompt}
    ]

def _call_openrouter(messages: List[Dict[str, str]], model: Optional[str] = None, max_tokens: int = 700, temperature: float = 0.7) -> str:
    """Handles the API call to OpenRouter with retries."""
    api_key = _load_api_key()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model or DEFAULT_MODEL,
        "messages": messages,
        "temperature": temperature,
        "top_p": 0.9,
        "max_tokens": max_tokens,
        "include_reasoning": False,
        "response_format": {"type": "text"}
    }

    for attempt in range(3):
        try:
            resp = requests.post(OPENROUTER_API_URL, headers=headers, data=json.dumps(payload), timeout=120)
            if resp.status_code < 400:
                return resp.json()["choices"][0]["message"]["content"].strip()
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {e}. Retrying...")
            pass
        import time
        time.sleep(1.5 * (attempt + 1))
    
    raise RuntimeError("OpenRouter request failed after multiple attempts")

def generate_post(repo: Optional[Union[str, Dict[str, Any]]] = None, niche: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Generates a LinkedIn post based on either a GitHub repository or a niche topic.
    The final output is optimized for SEO.
    """
    if not repo and not niche:
        raise ValueError("Either 'repo' or 'niche' is required to generate a post.")

    if niche:
        messages, topic_hint = _build_niche_prompt(niche), niche
    else:
        repo_info = fetch_repo_details(repo) if isinstance(repo, str) else repo
        if not isinstance(repo_info, dict):
            return None
        messages, topic_hint = _build_repo_prompt(repo_info), repo_info.get("name")

    try:
        raw_text = _call_openrouter(messages)
    except RuntimeError as e:
        print(f"Error generating content: {e}")
        return None

    cleaned_text = raw_text or ""
    title, body, hashtags = _postprocess_content(cleaned_text)

    # Use the SEO optimizer to refine the final post
    optimized = optimize_post_full(body)
    optimized_post = optimized.get("optimized_post", body)
    seo_score = optimized.get("seo_score", 0)
    seo_keywords = optimized.get("keywords", [])
    seo_hashtags = optimized.get("hashtags", hashtags)

    return {
        "title": title or "Professional Update",
        "body": optimized_post.strip(),
        "seo_score": seo_score,
        "seo_keywords": seo_keywords,
        "hashtags": seo_hashtags
    }

if __name__ == '__main__':
    # Example usage for a niche topic
    # Replace 'OPENROUTER_API_KEY' and 'OPENROUTER_MODEL' environment variables
    # with your actual values to run this.
    try:
        post_data = generate_post(niche="AI-driven protein-ligand interaction analysis")
        if post_data:
            print("--- Generated LinkedIn Post ---")
            print(post_data['body'])
            print(f"\nHashtags: {' '.join(post_data['hashtags'])}")
            print(f"SEO Score: {post_data['seo_score']}")
            print(f"Keywords: {', '.join(post_data['seo_keywords'])}")
    except Exception as e:
        print(f"An error occurred: {e}")