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
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/sherlock-think-alpha")
FALLBACK_MODELS = os.getenv("OPENROUTER_FALLBACK_MODELS", "").split(",") if os.getenv("OPENROUTER_FALLBACK_MODELS") else []

PROMPT_CONSTRAINTS = (
    "Follow these constraints for the LinkedIn post:\n"
    "- Length: 120–200 words, under 1,300 characters.\n"
    "- Tone: Natural, conversational, and genuinely human - like talking to a colleague.\n"
    "- Voice: Use first-person perspective naturally.\n"
    "- Structure: Start with an engaging thought, share context and insights, end with a question or call for discussion.\n"
    "- Writing style: Write exactly like a human would speak - no formatting symbols, no dashes, no asterisks, no bold text, no section labels, no artificial structure markers.\n"
    "- Flow: Let thoughts flow naturally from one to the next without forced transitions or headers.\n"
    "- Hashtags: 3–5 relevant hashtags at the very end only.\n"
    "- Keywords: Weave in relevant terms naturally as part of normal conversation.\n"
    "- CRITICAL: The post must read like genuine human thoughts, not a formatted article or structured content.\n"
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
        # Remove all formatting artifacts
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # Remove bold
        text = re.sub(r'\*([^*]+)\*', r'\1', text)  # Remove italic
        text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)  # Remove headers
        text = re.sub(r'^\s*[-•–—]\s*', '', text, flags=re.MULTILINE)  # Remove bullet points and dashes
        text = re.sub(r'^\s*\d+\.\s*', '', text, flags=re.MULTILINE)  # Remove numbered lists
        text = re.sub(r'\b(Hook|Context|Insights?|CTA|Call to Action)\s*[:–—-]\s*', '', text, flags=re.IGNORECASE)  # Remove structure labels
        text = re.sub(r'^\s*(Hook|Context|Insights?|CTA|Call to Action)\s*$', '', text, flags=re.MULTILINE | re.IGNORECASE)  # Remove standalone labels
        text = re.sub(r'[*_~`]', '', text)  # Remove any remaining formatting symbols
        
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        title = next((l for l in lines if l and not l.startswith('#')), "LinkedIn Update")
        
        # Extract hashtags
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
        
        # Clean body text
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
            "You are an AI professional with deep expertise in artificial intelligence and machine learning, who has a genuine passion for drug discovery and computational biology. "
            "You've just completed a significant project and want to share your journey and insights on LinkedIn.\n\n"
            f"Repo Name: {name}\nDescription: {desc}\nTopics: {', '.join(topics)}\nURL: {url}\n\n"
            "Instructions: Explain the problem you tackled, your unique approach, and a core technical insight. "
            "End with a CTA encouraging engagement or visiting the repo. Keep it genuine and professional.\n\n"
            + PROMPT_CONSTRAINTS
        )
        return [
            {"role": "system", "content": "You are an AI professional with deep expertise in artificial intelligence and machine learning, who has a genuine passion for drug discovery and computational biology. Write as someone who bridges AI technology with pharmaceutical applications."},
            {"role": "user", "content": user_prompt},
        ]

    @staticmethod
    def _build_niche_prompt(niche_topic: str) -> List[Dict[str, str]]:
        user_prompt = (
            "You are an AI professional with deep expertise in artificial intelligence and machine learning, who has a genuine passion for drug discovery and computational biology. Write a professional LinkedIn post about "
            f"{niche_topic}. Focus on an emerging trend, a new use case, or a recent breakthrough.\n\n"
            "Start with a strong hook, provide context, share a forward-looking insight or challenge, and end with a CTA inviting discussion.\n\n"
            + PROMPT_CONSTRAINTS
        )
        return [
            {"role": "system", "content": "You are an AI professional with deep expertise in artificial intelligence and machine learning, who has a genuine passion for drug discovery and computational biology. Write as someone who bridges AI technology with pharmaceutical applications."},
            {"role": "user", "content": user_prompt},
        ]

    @staticmethod
    def _call_openrouter(messages: List[Dict[str, str]], model: Optional[str] = None, max_tokens: int = 700, temperature: float = 0.7) -> str:
        key = LLMGenerator._load_api_key()
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        
        models_to_try = [model or DEFAULT_MODEL] + [m.strip() for m in FALLBACK_MODELS if m.strip()]
        
        for model_name in models_to_try:
            payload = {
                "model": model_name,
                "messages": messages,
                "temperature": temperature,
                "top_p": 0.9,
                "max_tokens": max_tokens,
                "include_reasoning": False,
                "response_format": {"type": "text"},
            }
            
            for attempt in range(2):
                try:
                    resp = requests.post(OPENROUTER_API_URL, headers=headers, data=json.dumps(payload), timeout=120)
                    if resp.status_code < 400:
                        if model_name != (model or DEFAULT_MODEL):
                            logger.info(f"Successfully used fallback model: {model_name}")
                        return resp.json()["choices"][0]["message"]["content"].strip()
                    logger.warning(f"Model {model_name} failed with HTTP {resp.status_code}: {resp.text[:200]}")
                    break
                except requests.exceptions.RequestException as e:
                    logger.warning(f"Model {model_name} request failed (attempt {attempt+1}): {e}")
                import time as _t
                _t.sleep(1.0)
            
            logger.warning(f"Model {model_name} failed, trying next fallback...")
        
        raise RuntimeError("All OpenRouter models failed after multiple attempts")

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