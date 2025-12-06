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
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "qwen/qwen3-coder:free")
FALLBACK_MODELS = [
    "google/gemma-3n-e4b-it:free",
    "qwen/qwen3-235b-a22b:free"
]

ENHANCED_PROMPT_CONSTRAINTS = """
Write a LinkedIn post that sounds completely natural and human - like you're sharing an insight with a colleague over coffee.

CRITICAL RULES:
- Length: 150-220 words total, under 1,300 characters
- Tone: Warm, conversational, genuinely curious and insightful
- Voice: First-person, natural speech patterns
- NO formatting symbols (* - # > etc.) in the body
- NO section labels (Hook, Context, CTA, etc.)
- NO bullet points or numbered lists in the body
- NO bold, italic, or any markdown formatting
- Start with a compelling thought or question that hooks attention
- Share a brief story, insight, or observation naturally
- End with an authentic question that invites discussion
- Add 3-5 hashtags ONLY at the very end, separated by a blank line

Think of it as: You discovered something interesting and want to share it authentically.
Let your personality shine through. Use natural transitions. Ask real questions.
"""

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
    def _aggressive_format_cleanup(text: str) -> str:
        """Remove ALL formatting artifacts to ensure natural text output."""
        text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
        text = re.sub(r'\*([^*]+)\*', r'\1', text)
        text = re.sub(r'__([^_]+)__', r'\1', text)
        text = re.sub(r'_([^_]+)_', r'\1', text)
        text = re.sub(r'~~([^~]+)~~', r'\1', text)
        text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*[-•–—]\s*', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\s*\d+\.\s*', '', text, flags=re.MULTILINE)
        
        labels = r'\b(Hook|Context|Story|Insights?|Value|CTA|Call to Action|Conclusion|Takeaway|Summary)\s*[:–—-]\s*'
        text = re.sub(labels, '', text, flags=re.IGNORECASE)
        
        text = re.sub(r'^(Hook|Context|Story|Insights?|Value|CTA|Call to Action):?\s*$', '', text, flags=re.MULTILINE | re.IGNORECASE)
        
        text = re.sub(r'[*_~`]', '', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        return text.strip()

    @staticmethod
    def _postprocess_content(text: str) -> Tuple[str, str, List[str]]:
        """Extract clean content, title, and hashtags from LLM output."""
        text = LLMGenerator._aggressive_format_cleanup(text)
        
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        title = lines[0] if lines else "Professional Update"
        if len(title) > 100:
            title = title[:97] + "..."
        
        hashtag_pattern = r'(?<!\w)#\w+'
        tags = re.findall(hashtag_pattern, text)
        seen, hashtags = set(), []
        for t in tags:
            norm = t if t.startswith("#") else f"#{t}"
            low = norm.lower()
            if low not in seen and len(norm) > 2:
                hashtags.append(norm)
                seen.add(low)
            if len(hashtags) >= 6:
                break
        
        body_text = re.sub(hashtag_pattern, '', text).strip()
        body_lines = [line for line in body_text.splitlines() if line.strip()]
        body = "\n\n".join(body_lines).strip()
        
        return title, body, hashtags[:6]

    @staticmethod
    def _build_repo_prompt(repo_info: Dict[str, Any]) -> List[Dict[str, str]]:
        """Build enhanced prompt for repository-based posts."""
        name = repo_info.get("name", "Repository")
        desc = repo_info.get("desc") or "an AI-based project"
        readme = repo_info.get("readme") or ""
        url = repo_info.get("url", "")
        topics = repo_info.get("topics") or []
        language = repo_info.get("language", "Python")
        
        context_snippet = ""
        if readme:
            context_snippet = f"\n\nKey details from README:\n{readme[:300]}..."
        
        user_prompt = f"""I just finished working on an exciting project called {name} and want to share it on LinkedIn.

Project Overview:
- Name: {name}
- Focus: {desc}
- Tech Stack: {language}
- Areas: {', '.join(topics) if topics else 'AI and Machine Learning'}
- Link: {url}
{context_snippet}

Write a LinkedIn post where I share:
1. What problem this project solves (why it matters)
2. My approach or a key technical insight I gained
3. What makes this interesting or valuable to others
4. An invitation for others to check it out or share their thoughts

{ENHANCED_PROMPT_CONSTRAINTS}

Remember: This should read like I'm genuinely excited to share something I built, not like a promotional announcement. Be authentic and conversational.
"""
        
        return [
            {
                "role": "system",
                "content": "You are an AI/ML professional passionate about drug discovery and computational biology. You build tools, conduct research, and share insights authentically. Write naturally as if speaking to peers."
            },
            {"role": "user", "content": user_prompt}
        ]

    @staticmethod
    def _build_niche_prompt(niche_topic: str) -> List[Dict[str, str]]:
        """Build enhanced prompt for niche topic posts."""
        user_prompt = f"""I want to write a LinkedIn post about {niche_topic} that provides genuine value and sparks conversation.

Topic: {niche_topic}

Write a LinkedIn post where I:
1. Start with a compelling observation, question, or mini-story about {niche_topic}
2. Share context on why this matters now or what's changing
3. Provide 2-3 concrete insights, examples, or lessons learned
4. End with a thoughtful question that invites real discussion

{ENHANCED_PROMPT_CONSTRAINTS}

Important: Don't just state facts. Share a perspective. Tell a micro-story. Make it feel like I'm having a genuine conversation with my network about something I find fascinating.
"""
        
        return [
            {
                "role": "system",
                "content": "You are an AI/ML professional passionate about drug discovery and computational biology. You stay current on trends, share authentic insights, and engage thoughtfully. Write as you would speak to a colleague."
            },
            {"role": "user", "content": user_prompt}
        ]

    @staticmethod
    def _call_openrouter(messages: List[Dict[str, str]], model: Optional[str] = None, 
                        max_tokens: int = 800, temperature: float = 0.8) -> str:
        """Call OpenRouter API with fallback models."""
        key = LLMGenerator._load_api_key()
        if not key:
            raise RuntimeError("OPENROUTER_API_KEY not set")
        
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }
        
        models_to_try = [model or DEFAULT_MODEL] + FALLBACK_MODELS
        
        for model_name in models_to_try:
            if not model_name.strip():
                continue
                
            payload = {
                "model": model_name,
                "messages": messages,
                "temperature": temperature,
                "top_p": 0.95,
                "max_tokens": max_tokens,
                "response_format": {"type": "text"}
            }
            
            for attempt in range(2):
                try:
                    resp = requests.post(
                        OPENROUTER_API_URL,
                        headers=headers,
                        json=payload,
                        timeout=120
                    )
                    
                    if resp.status_code < 400:
                        content = resp.json()["choices"][0]["message"]["content"].strip()
                        if model_name != (model or DEFAULT_MODEL):
                            logger.info(f"Used fallback model: {model_name}")
                        return content
                    
                    logger.warning(f"Model {model_name} returned {resp.status_code}: {resp.text[:200]}")
                    break
                    
                except requests.exceptions.RequestException as e:
                    logger.warning(f"Request to {model_name} failed (attempt {attempt+1}): {e}")
                    if attempt == 0:
                        import time
                        time.sleep(1.5)
        
        raise RuntimeError("All OpenRouter models failed")

    @staticmethod
    def _validate_post_quality(body: str) -> bool:
        """Validate post meets minimum quality standards."""
        if not body or len(body) < 100:
            return False
        
        words = len(body.split())
        if words < 50 or words > 300:
            return False
        
        formatting_artifacts = ['**', '__', '##', '- ', '* ', '1.', '2.']
        if any(artifact in body for artifact in formatting_artifacts):
            return False
        
        labels = ['Hook:', 'Context:', 'CTA:', 'Insight:', 'Value:']
        if any(label.lower() in body.lower() for label in labels):
            return False
        
        return True

    @staticmethod
    def generate_post(repo: Optional[Union[str, Dict[str, Any]]] = None, 
                     niche: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Generate a high-quality LinkedIn post via LLM."""
        if not repo and not niche:
            raise ValueError("Either 'repo' or 'niche' is required")
        
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
            logger.error("No response from OpenRouter API")
            return None
        
        title, body, hashtags = LLMGenerator._postprocess_content(raw_text)
        
        if not LLMGenerator._validate_post_quality(body):
            logger.warning("Generated post failed quality validation")
            return None
        
        optimized = optimize_post_full(body)
        
        final_body = optimized.get("optimized_post", body).strip()
        final_hashtags = optimized.get("hashtags", hashtags)
        
        return {
            "title": title or "Professional Update",
            "body": final_body,
            "seo_score": optimized.get("seo_score", 0),
            "seo_keywords": optimized.get("keywords", []),
            "hashtags": final_hashtags[:6]
        }


def generate_post(repo: Optional[Union[str, Dict[str, Any]]] = None, 
                 niche: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Public API for generating LinkedIn posts."""
    try:
        return LLMGenerator.generate_post(repo=repo, niche=niche)
    except Exception as e:
        logger.error(f"Post generation error: {e}", exc_info=True)
        return None