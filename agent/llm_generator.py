import os
import re
import json
import requests
from typing import Optional, Dict, Any, Tuple, List, Union
from datetime import datetime

from .seo_optimizer import optimize_post_full  # ✅ Use new SEO optimizer
from .backlog_generator import fetch_repo_details

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "deepseek/deepseek-r1:free")

PROMPT_CONSTRAINTS = (
    "Follow these exact constraints for the LinkedIn post:\n"
    "- Length: 120–200 words, under 1,300 chars.\n"
    "- Short, scannable lines, 1–2 lines per paragraph.\n"
    "- Conversational, authoritative, value-driven tone.\n"
    "- Structure: Hook → Context → Insights → CTA.\n"
    "- 3–5 hashtags at the end, mix broad + niche.\n"
    "- @Mentions only when relevant.\n"
    "- Include domain keywords naturally.\n"
    "- Avoid heavy Markdown; prefer clean text with breaks."
)

def _load_api_key() -> Optional[str]:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if api_key:
        return api_key
    try:
        from dotenv import load_dotenv
        load_dotenv()
        return os.getenv("OPENROUTER_API_KEY")
    except:
        return None

def _postprocess_content(text: str) -> Tuple[str, str, List[str]]:
    """Extract title, cleaned body, and up to 5 unique hashtags"""
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
    return title, text.strip(), hashtags

def _build_repo_prompt(repo_info: Dict[str, Any]) -> List[Dict[str, str]]:
    name, desc = repo_info.get("name", "Repository"), repo_info.get("desc") or "AI-based project."
    readme, url, topics = repo_info.get("readme") or "", repo_info.get("url", ""), repo_info.get("topics") or []
    user_prompt = (
        "You are a professional AI content creator.\n"
        "Write a highly engaging, SEO-optimized LinkedIn post for this GitHub repo.\n\n"
        f"Repo: {name}\nDescription: {desc}\nREADME: {readme}\nTopics: {', '.join(topics)}\nURL: {url}\n\n"
        "Cover problem solved, features, approach, and direct repo link.\n"
        "Use 1–2 @mentions if relevant.\n\n" + PROMPT_CONSTRAINTS
    )
    return [{"role": "system", "content": "You craft concise, credible, engaging LinkedIn posts."},
            {"role": "user", "content": user_prompt}]

def _build_niche_prompt(niche_topic: str) -> List[Dict[str, str]]:
    user_prompt = (
        "You are a thought leader in AI and Drug Discovery.\n"
        f"Write a professional LinkedIn post about {niche_topic}.\n\n"
        "Focus on trends, use cases, breakthroughs, and end with a CTA.\n"
        "Hashtags: 3–5 only, at the very end.\n\n" + PROMPT_CONSTRAINTS
    )
    return [{"role": "system", "content": "You craft concise, credible, engaging LinkedIn posts."},
            {"role": "user", "content": user_prompt}]

def _call_openrouter(messages: List[Dict[str, str]], model: Optional[str] = None, max_tokens: int = 700, temperature: float = 0.7) -> str:
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
        except:
            pass
        import time
        time.sleep(1.5 * (attempt + 1))

    raise RuntimeError("OpenRouter request failed")

def _clean_generated_text(text: str) -> str:
    """Remove labels, visuals, and metadata from LinkedIn posts"""
    if not text:
        return ""
    label_prefix = re.compile(r'^\s*(\*\*)?(\d+\)\s*)?(Hook|Context/Story|Context|Insights/Value|Insights|CTA)\s*(\*\*)?[:\-–—]\s*', re.IGNORECASE)
    label_only = re.compile(r'^\s*(\*\*)?(\d+\)\s*)?(Hook|Context/Story|Context|Insights/Value|Insights|CTA)\s*(\*\*)?[:\-–—]?\s*$', re.IGNORECASE)
    cleaned = []
    for raw in text.splitlines():
        line = raw.strip()
        if re.search(r'(?i)Suggested\s+visual', line) or re.search(r'(?i)Character\s*count', line):
            continue
        if label_only.match(line):
            continue
        line = label_prefix.sub('', line)
        cleaned.append(line)
    return "\n".join([l for l in cleaned if l.strip()]).strip()

def generate_post(repo: Optional[Union[str, Dict[str, Any]]] = None, niche: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not repo and not niche:
        raise ValueError("Either repo or niche required")

    # Build prompt
    if niche:
        messages, topic_hint = _build_niche_prompt(niche), niche
    else:
        repo_info = fetch_repo_details(repo) if isinstance(repo, str) else repo
        if not isinstance(repo_info, dict):
            return None
        messages, topic_hint = _build_repo_prompt(repo_info), repo_info.get("name")

    # Generate content
    text = _call_openrouter(messages)
    cleaned_text = _clean_generated_text(text or "")
    title, body, hashtags = _postprocess_content(cleaned_text)

    # Fallback content if LLM fails
    if not body.strip():
        hashtags = ["#AI", "#MachineLearning"]
        body = (f"Why {niche} matters now.\n\nOverview: {niche} benefits.\n\nKey insights and quick wins.\n\n"
                f"What use case are you exploring?\n\n" + " ".join(hashtags))
        title = f"Deep Dive: {niche}"

    # ✅ Run SEO optimizer with LLM + heuristics
    optimized = optimize_post_full(body)
    optimized_post = optimized["optimized_post"]
    seo_score = optimized["seo_score"]
    seo_keywords = optimized["keywords"]
    seo_hashtags = optimized["hashtags"] or hashtags

    return {
        "title": title or "LinkedIn Update",
        "body": optimized_post.strip(),
        "seo_score": seo_score,
        "seo_keywords": seo_keywords,
        "hashtags": seo_hashtags
    }