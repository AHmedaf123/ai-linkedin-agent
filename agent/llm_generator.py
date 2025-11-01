import os
import re
import json
import logging
from typing import Optional, Dict, Any, Tuple, List, Union

import requests

from .seo_optimizer import optimize_post_full
from .backlog_generator import fetch_repo_details

logger = logging.getLogger("linkedin-agent")

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-3n-e2b-it:free")

PROMPT_CONSTRAINTS = (
    "Follow these constraints for the LinkedIn post:\n"
    "- Length: 120–200 words, under 1,300 characters.\n"
    "- Tone: Authoritative, conversational, and deeply insightful.\n"
    "- Voice: Use first-person perspective.\n"
    "- Structure: Hook → Context/insights → Unique perspective → CTA.\n"
    "- Formatting: Short paragraphs (1–2 sentences) with line breaks; NO markdown, NO bold (**), NO section headers, NO asterisks.\n"
    "- Write in plain text only - LinkedIn will handle formatting.\n"
    "- Hashtags: 3–5 unique hashtags at the very end.\n"
    "- Keywords: Naturally embed relevant domain keywords for SEO.\n"
)

class LLMGenerator:
    @staticmethod
    def _load_api_key() -> Optional[str]:
        key = os.getenv("OPENROUTER_API_KEY")
        if key:
            return key
        try:
            from dotenv import load_dotenv
            load_dotenv()
            return os.getenv("OPENROUTER_API_KEY")
        except Exception:
            return None

    @staticmethod
    def _postprocess_content(text: str) -> Tuple[str, str, List[str]]:
        # Remove markdown formatting
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # Remove bold
        text = re.sub(r'\*([^*]+)\*', r'\1', text)  # Remove italic
        text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)  # Remove headers
        
        lines = [l.strip() for l in text.splitlines()]
        title = re.sub(r"^[#*\s]+", "", next((l for l in lines if l), "LinkedIn Update")).strip()
        tags = re.findall(r"(?i)#\w+", text)
        seen, hashtags = set(), []
        for t in tags:
            norm = t if t.startswith("#") else f"#{t}"
            low = norm.lower()
            if low not in seen:
                hashtags.append(norm)
                seen.add(low)
            if len(hashtags) >= 5:
                break
        body_lines = [line for line in lines if not re.match(r'^\s*#', line)]
        body = "\n".join(body_lines).strip()
        return title, body, hashtags

    @staticmethod
    def _build_repo_prompt(repo_info: Dict[str, Any]) -> List[Dict[str, str]]:
        name = repo_info.get("name", "Repository")
        desc = repo_info.get("desc") or "an AI-based project."
        readme = repo_info.get("readme") or ""
        url = repo_info.get("url", "")
        topics = repo_info.get("topics") or []
        user_prompt = (
            "You are a professional software engineer and AI researcher. "
            "You've just completed a significant project and want to share your journey and insights on LinkedIn.\n\n"
            f"Repo Name: {name}\nDescription: {desc}\nTopics: {', '.join(topics)}\nURL: {url}\n\n"
            "Instructions: Explain the problem you tackled, your unique approach, and a core technical insight. "
            "End with a CTA encouraging engagement or visiting the repo. Keep it genuine and professional.\n\n"
            + PROMPT_CONSTRAINTS
        )
        return [
            {"role": "system", "content": "You craft concise, credible LinkedIn content for professionals."},
            {"role": "user", "content": user_prompt},
        ]

    @staticmethod
    def _build_niche_prompt(niche_topic: str) -> List[Dict[str, str]]:
        user_prompt = (
            "You are a recognized thought leader. Write a professional LinkedIn post about "
            f"{niche_topic}. Focus on an emerging trend, a new use case, or a recent breakthrough.\n\n"
            "Start with a strong hook, provide context, share a forward-looking insight or challenge, and end with a CTA inviting discussion.\n\n"
            + PROMPT_CONSTRAINTS
        )
        return [
            {"role": "system", "content": "You craft concise, credible LinkedIn content for professionals."},
            {"role": "user", "content": user_prompt},
        ]

    @staticmethod
    def _call_openrouter(messages: List[Dict[str, str]], model: Optional[str] = None, max_tokens: int = 700, temperature: float = 0.7) -> str:
        key = LLMGenerator._load_api_key()
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {
            "model": model or DEFAULT_MODEL,
            "messages": messages,
            "temperature": temperature,
            "top_p": 0.9,
            "max_tokens": max_tokens,
            "include_reasoning": False,
            "response_format": {"type": "text"},
        }
        for attempt in range(3):
            try:
                resp = requests.post(OPENROUTER_API_URL, headers=headers, data=json.dumps(payload), timeout=120)
                if resp.status_code < 400:
                    return resp.json()["choices"][0]["message"]["content"].strip()
                logger.warning(f"OpenRouter HTTP {resp.status_code}: {resp.text[:200]}")
            except requests.exceptions.RequestException as e:
                logger.warning(f"OpenRouter request failed (attempt {attempt+1}): {e}")
            import time as _t
            _t.sleep(1.5 * (attempt + 1))
        raise RuntimeError("OpenRouter request failed after multiple attempts")

    @staticmethod
    def generate_post(repo: Optional[Union[str, Dict[str, Any]]] = None, niche: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not repo and not niche:
            raise ValueError("Either 'repo' or 'niche' is required.")
        if niche:
            messages = LLMGenerator._build_niche_prompt(niche)
        else:
            repo_info = fetch_repo_details(repo) if isinstance(repo, str) else repo
            if not isinstance(repo_info, dict):
                return None
            messages = LLMGenerator._build_repo_prompt(repo_info)
        try:
            raw_text = LLMGenerator._call_openrouter(messages)
        except Exception as e:
            logger.error(f"OpenRouter API call failed: {e}", exc_info=True)
            return None
        if not raw_text:
            logger.error("No response received from OpenRouter API.")
            return None
        title, body, hashtags = LLMGenerator._postprocess_content(raw_text or "")
        optimized = optimize_post_full(body)
        return {
            "title": title or "Professional Update",
            "body": optimized.get("optimized_post", body).strip(),
            "seo_score": optimized.get("seo_score", 0),
            "seo_keywords": optimized.get("keywords", []),
            "hashtags": optimized.get("hashtags", hashtags),
        }

# Public API facade (kept for backward compatibility)

def generate_post(repo: Optional[Union[str, Dict[str, Any]]] = None, niche: Optional[str] = None) -> Optional[Dict[str, Any]]:
    try:
        return LLMGenerator.generate_post(repo=repo, niche=niche)
    except Exception as e:
        logger.error(f"LLM generation error: {e}", exc_info=True)
        return None