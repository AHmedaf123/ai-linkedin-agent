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
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-3-12b-it:free")
FALLBACK_MODELS = [
    "meta-llama/llama-3-8b-instruct:free",
    "microsoft/phi-3-mini-128k-instruct:free",
    "google/gemma-3n-e4b-it:free",
    "qwen/qwen3-235b-a22b:free"
]

ENHANCED_PROMPT_CONSTRAINTS = """
Write a LinkedIn post that shares fascinating AI breakthroughs and capabilities - like you're an AI insights curator sharing what's happening in the field.

CRITICAL RULES:
- Length: 150-220 words total, under 1,300 characters
- Tone: Informative, insightful, educator sharing exciting developments
- Voice: Third-person or field perspective (NOT "I built/I did")
- NO formatting symbols (* - # > etc.) in the body
- NO section labels (Hook, Context, CTA, etc.)
- NO bullet points or numbered lists in the body
- NO bold, italic, or any markdown formatting

SPECIFIC CONTENT REQUIREMENTS (MUST INCLUDE):
- AT LEAST 2 specific numbers, percentages, metrics, or version numbers
- AT LEAST 1 concrete example: researcher name, company, institution, or paper
- AT LEAST 1 real achievement or breakthrough with results
- Focus on WHAT AI IS CAPABLE OF, not personal work

CONTENT FOCUS - Share insights about:
- Recent breakthroughs: "In 2024, researchers at [institution] achieved..."
- Capabilities: "AI is now capable of..."
- Real impact: "This technology helped reduce/increase [metric] by [percentage]"
- Trends: "The field is seeing [specific advancement]..."
- Comparisons: "This is X% better than previous methods..."

BANNED GENERIC PHRASES (do NOT use ANY of these):
- "evolving rapidly" / "rapidly evolving"
- "exciting advances" / "exciting developments"  
- "balance innovation with pragmatic implementation"
- "start small, measure impact, iterate"
- "new applications emerging across industries"
- "making theoretical concepts practical"
- "making once-theoretical concepts practical and accessible"

REQUIRED STRUCTURE:
- Start with a specific fact or recent breakthrough
- Share concrete details: who, what, when, results, metrics
- Explain the real-world impact or capability
- End with a thought-provoking question about implications
- Add 3-5 hashtags ONLY at the very end, separated by a blank line

Think: You're sharing a fascinating AI development you discovered - with real details about who did it, what they achieved, and why it matters.
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
    def _validate_content_specificity(body: str) -> Tuple[bool, List[str]]:
        """Validate post has specific, actionable content with real educational value."""
        issues = []
        
        # Check for numbers/metrics/data points
        import re
        numbers = re.findall(r'\d+\.?\d*%|\d+x|\d+\.\d+|\d{2,}', body)
        if len(numbers) < 1:
            issues.append(f"Only {len(numbers)} numbers/metrics found (need 1+ for specificity)")
        
        # Check for banned generic phrases
        banned_phrases = [
            "evolving rapidly", "rapidly evolving",
            "exciting advances", "exciting developments",
            "balance innovation with pragmatic implementation",
            "start small, measure impact, iterate",
            "new applications emerging",
            "making theoretical concepts practical",
            "making once-theoretical concepts practical",
            "practical and accessible"
        ]
        found_banned = []
        for phrase in banned_phrases:
            if phrase.lower() in body.lower():
                found_banned.append(phrase)
        if found_banned:
            issues.append(f"Contains banned generic phrases: {', '.join(found_banned)}")
        
        # Check for actionable/technical verbs (warning only, not blocking)
        actionable_verbs = [
            'built', 'implemented', 'tested', 'discovered', 'measured', 
            'achieved', 'reduced', 'increased', 'optimized', 'deployed',
            'trained', 'fine-tuned', 'benchmarked', 'analyzed', 'developed'
        ]
        has_action = any(verb in body.lower() for verb in actionable_verbs)
        if not has_action:
            logger.info("Post has no actionable verbs, but this is not blocking")
        
        # Check for vague words that indicate generic content
        vague_indicators = ['teams', 'space', 'field', 'key is', 'important']
        vague_count = sum(1 for word in vague_indicators if word in body.lower())
        if vague_count > 2:
            issues.append(f"Too many vague/generic terms ({vague_count} found)")
        
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
        
        user_prompt = f"""I came across an interesting project called {name} that showcases what AI can do in this space.

Project Overview:
- Name: {name}
- Purpose: {desc}
- Technology: {language}
- Focus Areas: {', '.join(topics) if topics else 'AI and Machine Learning'}
- Project Link: {url}
{context_snippet}

Write a LinkedIn post where you share:
1. What this project demonstrates about AI capabilities
2. The specific problem it solves and how (with metrics if available)
3. Why this is significant for the field
4. What this tells us about where AI is heading

{ENHANCED_PROMPT_CONSTRAINTS}

Remember: Frame this as "Look what AI can do" not "I built this". You're an observer sharing an impressive development in the field.
"""
        
        return [
            {
                "role": "user",
                "content": f"""SYSTEM INSTRUCTION: You are an AI insights curator who shares fascinating developments in AI/ML, drug discovery, and computational biology. You help people understand what AI is capable of by highlighting real breakthroughs, papers, and projects. Write as an informed observer sharing exciting developments.

USER REQUEST:
{user_prompt}"""
            }
        ]

    @staticmethod
    def _build_niche_prompt(niche_topic: str, context: str = "") -> List[Dict[str, str]]:
        """Build enhanced prompt for niche topic posts, optionally using provided context."""
        
        context_instruction = ""
        if context:
            context_instruction = f"\n\nCONTEXT / SOURCE MATERIAL:\n{context}\n\nUse the above context as the primary source for facts, results, and metrics."

        user_prompt = f"""I want to write a LinkedIn post about {niche_topic} that showcases what's happening in this field and what AI is capable of.

Topic: {niche_topic}{context_instruction}

Write a LinkedIn post that shares:
1. A specific recent breakthrough or capability in {niche_topic}
   - Example: "In 2024, researchers at [Institution] used [approach] and achieved..."
   - Or: "A new study in [Journal] showed that AI can now..."

2. Concrete results and impact
   - Include specific metrics, percentages, or improvements
   - Show real-world applications or significance

3. What this tells us about AI's capabilities
   - How is AI helping in this field?
   - What problems can it solve now that it couldn't before?
   - How much faster/better/more efficient is it?

4. Forward-looking insight
   - What does this mean for the field?
   - What possibilities does this open up?

{ENHANCED_PROMPT_CONSTRAINTS}

Important: Frame this as "Look what AI can do" not "what I'm working on". You're sharing fascinating developments to educate your network about AI's capabilities.
"""
        
        return [
            {
                "role": "user",
                "content": f"""SYSTEM INSTRUCTION: You are an AI insights curator focused on drug discovery and computational biology. You share breakthrough research, real-world AI applications, and help people understand what AI is achieving in these fields. Write as an informed observer highlighting exciting developments with specific examples and data.

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
                 niche: Optional[str] = None, context: str = "") -> Optional[Dict[str, Any]]:
    """Public API for generating LinkedIn posts."""
    try:
        return LLMGenerator.generate_post(repo=repo, niche=niche, context=context)
    except Exception as e:
        logger.error(f"Post generation error: {e}", exc_info=True)
        return None