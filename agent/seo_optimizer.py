import os
import re
import json
import requests
from typing import List, Tuple, Dict, Any
from collections import Counter

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-3-12b-it:free")

SEO_SYSTEM_PROMPT = """You are a light-touch editor for a human engineer's LinkedIn post.
Your job is to keep it sounding like a real person wrote it, fix only obvious problems, and
suggest a couple of relevant keywords/hashtags. You must NOT corporate-ify or over-polish it.
Return only valid JSON with no additional text."""

SEO_USER_TEMPLATE = """Lightly clean up this LinkedIn post. It is meant to sound like a real
AI/ML engineer telling a small story from their own work, in simple non-native English.

Original post:
{post}

Rules:
- Preserve the author's voice, story, and simple wording. Do NOT rewrite it into polished
  corporate English. Small grammar fixes only.
- Keep it 90-180 words, under 1,300 characters.
- No emojis, no bullet points, no numbered lists, no bold, no section labels.
- Do NOT stuff keywords. Do NOT add hype words (game-changer, seamless, leverage, unlock, etc).
- Hashtags: 0 to 2 only, plain and relevant (e.g. #AIEngineering #LLM), at the very end.
- Preserve any @mentions and links.

Return JSON with:
{{
  "optimized_post": "the lightly cleaned post text",
  "llm_seo_score": 85,
  "keywords": ["keyword1", "keyword2", ...],
  "hashtags": ["#Hashtag1", "#Hashtag2"]
}}
"""

BROAD_HASHTAGS = {
    "#ai", "#machinelearning", "#datascience", "#deeplearning", "#artificialintelligence",
    "#ml", "#tech", "#innovation", "#technology", "#digitalTransformation"
}

NICHE_HASHTAGS = {
    "#drugdiscovery", "#computationalbiology", "#bioinformatics", "#molecularmodeling",
    "#airesearch", "#generativeai", "#mlops", "#scientificml", "#proteindesign",
    "#aiinscience", "#computationalchemistry", "#molecularml", "#biotech"
}

EMOJI_REGEX = re.compile(r"[\U0001F300-\U0001FAFF]")
WORD_REGEX = re.compile(r"\b[A-Za-z][A-Za-z0-9\-_]*\b")
HASHTAG_REGEX = re.compile(r"#\w+")


def _load_api_key() -> str:
    key = os.getenv("OPENROUTER_API_KEY")
    if key:
        return key
    try:
        from dotenv import load_dotenv
        load_dotenv()
        key = os.getenv("OPENROUTER_API_KEY")
    except Exception:
        pass
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    return key


def _call_openrouter(prompt: str, max_tokens: int = 700, temperature: float = 0.5) -> Dict[str, Any]:
    """Call OpenRouter API for SEO optimization."""
    headers = {
        "Authorization": f"Bearer {_load_api_key()}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": SEO_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": temperature,
        "top_p": 0.9,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"}
    }
    
    for attempt in range(2):
        try:
            resp = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=120)
            if resp.status_code < 400:
                return resp.json()
            break
        except Exception:
            if attempt == 0:
                import time
                time.sleep(1.0)
    
    raise RuntimeError("OpenRouter SEO optimization failed")


def _strip_formatting(text: str) -> str:
    """Aggressively remove all formatting artifacts."""
    if not text:
        return ""
    
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)
    text = re.sub(r'_([^_]+)_', r'\1', text)
    text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*[-•–—]\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'[*_~`]', '', text)
    
    labels = [
        r'\b(Hook|Context|Story|Insights?|Value|CTA|Call to Action|Conclusion|Takeaway)\s*[:–—-]\s*',
        r'^(Hook|Context|Story|Insights?|Value|CTA|Call to Action):?\s*$'
    ]
    for pattern in labels:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.MULTILINE)
    
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _keyword_density_score(text: str, keywords: List[str]) -> int:
    """Calculate keyword density score with optimal range 2-5%."""
    words = WORD_REGEX.findall(text.lower())
    total_words = len(words)
    
    if total_words == 0:
        return 0
    
    kw_set = {k.lower() for k in keywords}
    keyword_count = sum(1 for w in words if w in kw_set)
    density = (keyword_count / total_words) * 100
    
    if 2.5 <= density <= 4.5:
        return 100
    elif 2.0 <= density <= 5.0:
        return 90
    elif density < 2.0:
        return int(min(density / 2.0, 1.0) * 100)
    else:
        return max(0, int(100 - (density - 5.0) * 15))


def _hashtag_quality_score(tags: List[str]) -> int:
    """Hashtag scoring for the humanized style: 0-2 plain tags is ideal.

    Real engineers rarely stack 5 hashtags, so we reward restraint (0-2), give a
    small penalty for 3, and penalize hashtag-stuffing.
    """
    count = len(tags)
    if count <= 2:
        count_score = 100
    elif count == 3:
        count_score = 80
    else:
        count_score = max(0, 100 - (count - 3) * 30)

    if count == 0:
        # No hashtags is acceptable in this style; neutral-good.
        return 85

    tags_lower = [t.lower() for t in tags]
    unique_count = len(set(tags_lower))
    uniqueness_score = int((unique_count / count) * 100)

    return min(100, int(0.7 * count_score + 0.3 * uniqueness_score))


def _engagement_score(text: str) -> int:
    """Score engagement potential based on LinkedIn-specific factors."""
    sentences = [s.strip() for s in re.split(r'[.!?]\s+', text) if s.strip()]
    
    if not sentences:
        return 0
    
    word_counts = [len(WORD_REGEX.findall(s)) for s in sentences]
    avg_sentence_length = sum(word_counts) / len(sentences) if sentences else 0
    
    if 12 <= avg_sentence_length <= 20:
        readability = 100
    else:
        readability = max(0, int(100 - abs(avg_sentence_length - 16) * 5))
    
    # Emojis are banned in the humanized style, so their presence is a small penalty.
    emoji_count = len(EMOJI_REGEX.findall(text))
    emoji_score = 100 if emoji_count == 0 else max(0, 100 - emoji_count * 40)

    # One honest closing question is fine; more than two reads as engagement-baiting.
    question_count = text.count('?')
    if question_count <= 1:
        question_score = 100
    elif question_count == 2:
        question_score = 80
    else:
        question_score = max(0, 100 - (question_count - 2) * 30)

    lines = [ln for ln in text.splitlines() if ln.strip()]
    max_line_length = max((len(ln) for ln in lines), default=0)

    if max_line_length <= 120:
        scan_score = 100
    else:
        scan_score = max(0, int(100 - (max_line_length - 120) * 0.5))

    paragraphs = text.split('\n\n')
    para_score = 100 if 2 <= len(paragraphs) <= 6 else max(0, 100 - abs(len(paragraphs) - 3) * 15)

    final_score = int(
        0.35 * readability +
        0.15 * emoji_score +
        0.20 * question_score +
        0.20 * scan_score +
        0.10 * para_score
    )

    return min(100, final_score)


def _content_quality_score(text: str, keywords: List[str]) -> int:
    """Calculate overall content quality for LinkedIn."""
    word_count = len(WORD_REGEX.findall(text))

    if 90 <= word_count <= 180:
        length_score = 100
    elif 70 <= word_count <= 210:
        length_score = 85
    else:
        length_score = max(0, 100 - abs(word_count - 135) * 2)
    
    char_count = len(text)
    char_score = 100 if char_count <= 1300 else max(0, int(100 - (char_count - 1300) * 0.1))
    
    sentences = [s for s in re.split(r'[.!?]\s+', text) if s.strip()]
    variety_score = min(100, len(sentences) * 12)
    
    formatting_artifacts = ['**', '__', '##', '- ', '* ', 'Hook:', 'Context:', 'CTA:']
    has_artifacts = any(artifact in text for artifact in formatting_artifacts)
    clean_score = 0 if has_artifacts else 100
    
    final_score = int(
        0.25 * length_score +
        0.20 * char_score +
        0.20 * variety_score +
        0.35 * clean_score
    )
    
    return min(100, final_score)


def _heuristic_seo_score(text: str, keywords: List[str], hashtags: List[str]) -> int:
    """Calculate comprehensive heuristic SEO score."""
    kw_score = _keyword_density_score(text, keywords)
    hashtag_score = _hashtag_quality_score(hashtags)
    engagement = _engagement_score(text)
    quality = _content_quality_score(text, keywords)
    
    final_score = int(
        0.30 * kw_score +
        0.25 * hashtag_score +
        0.25 * engagement +
        0.20 * quality
    )
    
    return min(100, final_score)


def optimize_post_full(text: str) -> Dict[str, Any]:
    """Fully optimize a LinkedIn post for SEO and engagement."""
    cleaned_text = _strip_formatting(text)
    
    try:
        llm_response = _call_openrouter(SEO_USER_TEMPLATE.format(post=cleaned_text))
        content = llm_response["choices"][0]["message"]["content"]
        data = json.loads(content)
    except Exception:
        data = {
            "optimized_post": cleaned_text,
            "llm_seo_score": 65,
            "keywords": [],
            "hashtags": []
        }
    
    optimized_text = _strip_formatting(str(data.get("optimized_post", ""))) or cleaned_text
    
    hashtags_raw = data.get("hashtags", [])
    hashtags = []
    for tag in hashtags_raw:
        if isinstance(tag, str):
            normalized = tag if tag.startswith('#') else f'#{tag}'
            hashtags.append(normalized.strip())
    
    seen = set()
    unique_hashtags = []
    for tag in hashtags:
        if tag.lower() not in seen:
            unique_hashtags.append(tag)
            seen.add(tag.lower())
    
    keywords_raw = data.get("keywords", [])
    keywords = [k.strip() for k in keywords_raw if isinstance(k, str) and k.strip()][:12]
    
    llm_score = int(max(0, min(100, data.get("llm_seo_score", 65))))
    heuristic_score = _heuristic_seo_score(optimized_text, keywords, unique_hashtags)
    
    final_score = int(0.55 * llm_score + 0.45 * heuristic_score)
    
    body_without_tags = HASHTAG_REGEX.sub('', optimized_text).strip()
    
    if unique_hashtags[:6]:
        hashtag_line = " ".join(unique_hashtags[:6])
        final_text = f"{body_without_tags}\n\n{hashtag_line}"
    else:
        final_text = body_without_tags
    
    return {
        "optimized_post": final_text.strip(),
        "seo_score": final_score,
        "keywords": keywords,
        "hashtags": unique_hashtags[:6],
        "llm_score": llm_score,
        "heuristic_score": heuristic_score
    }


def optimize_post(text: str) -> Tuple[int, List[str]]:
    """Simplified API returning just score and keywords."""
    result = optimize_post_full(text)
    return result["seo_score"], result["keywords"]