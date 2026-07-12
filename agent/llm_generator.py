import os
import re
import json
import logging
from typing import Optional, Dict, Any, Tuple, List, Union

import requests

from .seo_optimizer import optimize_post_full
from .backlog_generator import fetch_repo_details
from .deduper import load_recent_posts
import hashlib

logger = logging.getLogger("linkedin-agent")

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-3-12b-it:free")
FALLBACK_MODELS = [
    "meta-llama/llama-3-8b-instruct:free",
    "microsoft/phi-3-mini-128k-instruct:free",
    "google/gemma-3n-e4b-it:free",
    "qwen/qwen3-235b-a22b:free"
]

ENHANCED_PROMPT_CONSTRAINTS = """
You are a working AI/ML engineer who builds real LLM-powered products and agents.
You are writing a short LinkedIn post that teaches ONE practical thing.

WHO YOU ARE WRITING FOR AND ABOUT:
- Teach one specific thing that a junior engineer usually does NOT know, but that an
  associate/mid-level engineer knows well from real work. Examples of the *kind* of thing:
  a gotcha with LLM rate limits and retries, a cheaper way to use an API, a prompt pattern
  that actually changes behavior, a RAG mistake that only shows up at scale, how you keep
  the context window small in production, a tool-use detail, an error you had to debug.
- Make it feel earned from real building, not read from a tutorial.

HOW TO WRITE IT (this is the most important part — write like a real human, not an AI):
- Write it as a small personal story or observation. Something like: here is a situation I
  hit, here is what confused me or what a junior on my team got wrong, here is what I
  understood after. Keep it grounded in a real moment.
- First person. Simple, direct English. It is completely fine to sound like a non-native
  English speaker from Pakistan — short and plain sentences, not fancy vocabulary. Do NOT
  over-polish it into perfect native "corporate LinkedIn" English.
- Length: 90-180 words. Under 1,300 characters.

HARD BANS (these are the tells that make writing look AI-generated — never do them):
- No emojis. No bullet points, no numbered lists, no markdown, no bold, no section labels.
- No "rule of three" lists inside sentences (do not stack three adjectives or three items
  for rhythm).
- No hype words: game-changer, revolutionary, cutting-edge, unlock, supercharge, seamless,
  robust, leverage, delve, realm, landscape, tapestry, powerful, elevate, harness.
- No filler openers: "In today's world", "In the world of", "In the fast-paced world of",
  "ever-evolving", "Here's the thing", "Here's how", "Let's dive in", "Picture this".
- No dramatic one-line hook and no attention-grabbing question as the first line. Start like
  a person already in the middle of a thought.
- No forced "not just X, it's Y" contrast. No fake statistics. Do not invent numbers.

WHAT GOOD LOOKS LIKE:
- Anchor it with one concrete detail: a real tool or API, an actual error message, a real
  number ONLY if it is natural and true. One concrete detail is enough — do not stuff facts.
- End plainly. A small honest reflection, or a simple real question. Not a corporate
  call-to-action, not "What do you think? Comment below".

VARIATION:
- If a regeneration hint is present in the CONTEXT, change the angle and the opening, and do
  not repeat earlier wording or earlier openings.

Remember: the goal is that a real engineer reading this thinks "yeah, a person who actually
builds things wrote this", not "an AI wrote this".
"""
SEO_TARGET = int(os.getenv("SEO_TARGET", "62"))

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

    # AI-tell phrases and hype words that make writing look machine-generated.
    # These are enforced at generation time (in the prompt) and re-checked here.
    AI_TELL_PHRASES = [
        "in today's world", "in the world of", "in the fast-paced world",
        "ever-evolving", "rapidly evolving", "evolving rapidly",
        "here's the thing", "let's dive in", "let's dive into", "dive deep",
        "picture this", "buckle up", "game-changer", "game changer",
        "revolutionary", "cutting-edge", "cutting edge", "supercharge",
        "unlock the power", "seamless", "seamlessly", "leverage",
        "delve", "realm", "tapestry", "landscape of", "elevate your",
        "harness the power", "at the end of the day", "needle in a haystack",
        "when it comes to", "the beauty of", "look what ai can do",
        "start small, measure impact, iterate", "comment below",
        "what do you think? let me know",
    ]

    @staticmethod
    def _validate_content_specificity(body: str) -> Tuple[bool, List[str]]:
        """Validate the post reads like a human engineer, not an AI.

        Story-style posts are allowed to have no hard metrics, so we do NOT block
        on missing numbers. We block on AI tells, hype words, and formatting that
        the humanized prompt explicitly forbids.
        """
        issues = []
        low = body.lower()

        found_tells = [p for p in LLMGenerator.AI_TELL_PHRASES if p in low]
        if found_tells:
            issues.append(f"Contains AI-tell / hype phrases: {', '.join(found_tells[:6])}")

        # Emojis are banned in the new style.
        if re.search(r"[\U0001F300-\U0001FAFF☀-➿]", body):
            issues.append("Contains emojis (banned in humanized style)")

        # "Rule of three" comma triads like "fast, cheap, and reliable" are a strong AI tell.
        triad = re.search(r"\b\w+,\s+\w+,\s+and\s+\w+\b", low)
        if triad:
            issues.append(f"Contains a rule-of-three list: '{triad.group(0)}'")

        # Grounding: at least one concrete anchor (a tool/API name, code-ish token, or a
        # natural number). This is a soft signal — a single concrete token is enough.
        has_number = bool(re.search(r"\d", body))
        has_techy_token = bool(re.search(
            r"\b(api|llm|claude|gpt|token|prompt|rag|retry|rate limit|cache|context window|"
            r"json|schema|endpoint|latency|embedding|vector|agent|tool call|timeout)\b", low))
        if not (has_number or has_techy_token):
            issues.append("No concrete technical anchor (tool/API/number) found")

        return len(issues) == 0, issues

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
        
        user_prompt = f"""I was looking at a project called {name} while building something similar.

Project notes:
- Name: {name}
- Purpose: {desc}
- Technology: {language}
- Focus Areas: {', '.join(topics) if topics else 'AI and LLM engineering'}
- Project Link: {url}
{context_snippet}

Write the post as a short personal observation from actually working with or studying this
project: one practical engineering lesson you took from it that a junior would miss. Ground it
in a real moment, not a feature list.

{ENHANCED_PROMPT_CONSTRAINTS}
"""

        return [
            {
                "role": "user",
                "content": f"""SYSTEM INSTRUCTION: You are a hands-on AI/ML engineer who ships LLM-powered products. You write in simple, direct, first-person English (non-native is fine). You share real engineering lessons, never corporate hype.

USER REQUEST:
{user_prompt}"""
            }
        ]

    @staticmethod
    def _build_niche_prompt(niche_topic: str, context: str = "") -> List[Dict[str, str]]:
        """Build enhanced prompt for niche topic posts, optionally using provided context."""
        
        context_instruction = ""
        if context:
            context_instruction = (
                f"\n\nCONTEXT (your own past-post performance and/or source material — "
                f"use it to pick the angle and to avoid repeating openings that already flopped):\n{context}"
            )

        user_prompt = f"""Write a short LinkedIn post about this area of AI/LLM engineering: {niche_topic}.{context_instruction}

Do not "cover the topic". Instead, pick ONE small, specific, practical thing inside {niche_topic}
that you learned the hard way while building — the kind of detail a junior engineer gets wrong and
an associate-level engineer just knows. Tell it as a short real story or observation from your own
work.

{ENHANCED_PROMPT_CONSTRAINTS}
"""

        return [
            {
                "role": "user",
                "content": f"""SYSTEM INSTRUCTION: You are a hands-on AI/ML engineer who ships LLM-powered products (agents, RAG systems, API integrations). You write in simple, direct, first-person English (non-native speaker is fine and preferred over polished corporate English). You share real engineering lessons, never hype. If a regeneration hint is present in the CONTEXT, change the angle and the opening line.

USER REQUEST:
{user_prompt}"""
            }
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
                "max_tokens": max_tokens
            }
            
            for attempt in range(2):
                try:
                    resp = requests.post(
                        OPENROUTER_API_URL,
                        headers=headers,
                        json=payload,
                        timeout=180
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
            logger.warning("Post too short or empty")
            return False
        
        words = len(body.split())
        if words < 50 or words > 300:
            logger.warning(f"Post word count out of range: {words}")
            return False
        
        formatting_artifacts = ['**', '__', '##']
        if any(artifact in body for artifact in formatting_artifacts):
            logger.warning("Post contains formatting artifacts")
            return False
        
        labels = ['Hook:', 'Context:', 'CTA:', 'Insight:', 'Value:']
        if any(label.lower() in body.lower() for label in labels):
            logger.warning("Post contains structural labels")
            return False
        
        # NEW: Check content specificity and educational value
        is_specific, specificity_issues = LLMGenerator._validate_content_specificity(body)
        if not is_specific:
            logger.warning(f"Post failed specificity check: {'; '.join(specificity_issues)}")
            return False
        
        return True

    @staticmethod
    def generate_post(repo: Optional[Union[str, Dict[str, Any]]] = None, 
                     niche: Optional[str] = None, context: str = "") -> Optional[Dict[str, Any]]:
        """Generate a high-quality LinkedIn post via LLM."""
        if not repo and not niche:
            raise ValueError("Either 'repo' or 'niche' is required")
        
        if niche:
            messages = LLMGenerator._build_niche_prompt(niche, context=context)
        else:
            repo_info = fetch_repo_details(repo) if isinstance(repo, str) else repo
            if not isinstance(repo_info, dict):
                return None
            messages = LLMGenerator._build_repo_prompt(repo_info)
        
        # Try generation and retry on in-session duplicates up to 3 attempts
        attempts = 0
        max_attempts = 3
        temp = 0.8
        import re
        m = re.search(r"TEMP\s*=\s*([0-9]\.?[0-9]*)", context)
        if m:
            try:
                temp = float(m.group(1))
            except Exception:
                temp = 0.8

        raw_text = None
        last_error = None
        while attempts < max_attempts:
            attempts += 1
            try:
                # On retries, increase randomness slightly to encourage variation
                use_temp = min(0.95, temp + 0.1 * (attempts - 1))
                regen_hint = ""
                if attempts > 1:
                    regen_hint = "\n\nREGENERATE_HINT: Change the angle, use different examples/datasets/methods, avoid repeating prior wording."
                    # Append hint to messages as a system message
                    messages = messages + [{"role": "system", "content": regen_hint}]

                raw_text = LLMGenerator._call_openrouter(messages, temperature=use_temp)
            except Exception as e:
                last_error = e
                raw_text = None

            if not raw_text:
                continue

            title, body, hashtags = LLMGenerator._postprocess_content(raw_text)

            # Check in-session recent posts for duplicate content (by hash)
            try:
                recent = load_recent_posts()
                h = hashlib.md5(body.encode()).hexdigest()
                duplicate = any(p.get("hash") == h or hashlib.md5(p.get("body","").encode()).hexdigest() == h for p in recent)
            except Exception:
                duplicate = False

            if duplicate:
                # try again with a stronger regeneration hint
                last_error = RuntimeError("Generated post duplicated an in-session post; retrying")
                raw_text = None
                continue

            # Validate content quality; if invalid, try to regenerate with explicit metric requirement
            valid = LLMGenerator._validate_post_quality(body)
            if not valid:
                if attempts < max_attempts:
                    last_error = RuntimeError("Generated post failed quality validation; retrying humanized")
                    # Regeneration hint aligned with the humanized style: drop AI tells and hype,
                    # ground it in one real detail, change the opening line.
                    regen_hint = ("\n\nREGENERATE_HINT: Rewrite as a plain first-person story from real work. "
                                  "Remove any hype words, emojis, bullet points, and rule-of-three lists. "
                                  "Ground it in one concrete detail (a real tool, an actual error, or a natural number). "
                                  "Start with a different, non-hooky opening line and keep the English simple.")
                    messages = messages + [{"role": "system", "content": regen_hint}]
                    raw_text = None
                    continue
                else:
                    logger.warning("Generated post failed validation after retries; accepting last result to avoid blocking workflow")
                    # accept last generated text even if validation failed
                    break

            # otherwise break to continue processing
            break

        if raw_text is None:
            logger.error(f"OpenRouter API failed or produced duplicates after {attempts} attempts: {last_error}")
            return None
        
        if not raw_text:
            logger.error("No response from OpenRouter API")
            return None
        
        title, body, hashtags = LLMGenerator._postprocess_content(raw_text)
        
        if not LLMGenerator._validate_post_quality(body):
            logger.warning("Generated post failed quality validation")
            return None
        
        # Initial SEO optimization
        optimized = optimize_post_full(body)

        final_body = optimized.get("optimized_post", body).strip()
        final_hashtags = optimized.get("hashtags", hashtags)
        best_score = int(optimized.get("seo_score", 0))
        best_result = optimized

        # If below target, retry optimization with stronger instruction up to 2 times
        if best_score < SEO_TARGET:
            for retry in range(2):
                try:
                    hint = (
                        "\n\nIMPROVE_SEO: TargetScore={} -- "
                        "Increase keyword usage, add/adjust 3-6 highly-relevant hashtags, "
                        "preserve voice and length, avoid new factual claims."
                    ).format(SEO_TARGET)
                    retry_input = final_body + "\n\n" + hint
                    new_opt = optimize_post_full(retry_input)
                    new_score = int(new_opt.get("seo_score", 0))
                    if new_score > best_score:
                        best_score = new_score
                        best_result = new_opt
                        final_body = best_result.get("optimized_post", final_body).strip()
                        final_hashtags = best_result.get("hashtags", final_hashtags)
                    # Stop early if target reached
                    if best_score >= SEO_TARGET:
                        break
                except Exception:
                    # Non-fatal: continue to next retry
                    continue

        return {
            "title": title or "Professional Update",
            "body": final_body,
            "seo_score": best_score,
            "seo_keywords": best_result.get("keywords", []),
            "hashtags": final_hashtags[:6]
        }


def generate_post(repo: Optional[Union[str, Dict[str, Any]]] = None, 
                 niche: Optional[str] = None, context: str = "") -> Optional[Dict[str, Any]]:
    """Public API for generating LinkedIn posts."""
    try:
        return LLMGenerator.generate_post(repo=repo, niche=niche, context=context)
    except Exception as e:
        logger.error(f"Post generation error: {e}", exc_info=True)
        return None