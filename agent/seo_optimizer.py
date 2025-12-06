import os
import re
import json
import requests
from typing import List, Tuple, Dict, Any
from collections import Counter

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "qwen/qwen3-coder:free")

SEO_SYSTEM_PROMPT = """You are an expert LinkedIn SEO and engagement optimizer. 
Analyze posts for discoverability, engagement potential, and clarity.
Return only valid JSON with no additional text."""

SEO_USER_TEMPLATE = """Analyze and optimize this LinkedIn post for maximum engagement and discoverability.

Original post:
{post}

Requirements:
- Keep it 150-220 words, under 1,300 characters
- Write naturally like humans speak - NO formatting symbols, NO labels, NO structure markers
- Ensure 3-6 highly relevant hashtags (mix trending + niche) at the very end only
- Weave 8-12 natural domain keywords into the conversation
- Maintain authentic voice and conversational tone
- Preserve any @mentions and links

Return JSON with:
{{
  "optimized_post": "the enhanced post text",
  "llm_seo_score": 85,
  "keywords": ["keyword1", "keyword2", ...],
  "hashtags": ["#Hashtag1", "#Hashtag2", ...]
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
    """Enhanced hashtag scoring with diversity, uniqueness, and relevance."""
    if not tags:
        return 0
    
    tags_lower = [t.lower() for t in tags]
    count = len(tags_lower)
    
    count_score = 100 if 3 <= count <= 5 else max(0, 100 - abs(count - 4) * 15)
    
    broad_count = sum(1 for t in tags_lower if t in BROAD_HASHTAGS)
    niche_count = sum(1 for t in tags_lower if t in NICHE_HASHTAGS)
    
    if broad_count > 0 and niche_count > 0:
        diversity_score = 100
    elif broad_count > 0 or niche_count > 0:
        diversity_score = 70
    else:
        diversity_score = 40
    
    unique_count = len(set(tags_lower))
    uniqueness_score = int((unique_count / count) * 100) if count > 0 else 0
    
    relevance_score = int(((niche_count / count) * 100)) if count > 0 else 50
    
    final_score = int(
        0.30 * count_score +
        0.35 * diversity_score +
        0.20 * uniqueness_score +
        0.15 * relevance_score
    )
    
    return min(100, final_score)


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
    
    emoji_count = len(EMOJI_REGEX.findall(text))
    emoji_score = min(100, emoji_count * 25)
    
    question_count = text.count('?')
    question_score = min(100, question_count * 40)
    
    lines = [ln for ln in text.splitlines() if ln.strip()]
    max_line_length = max((len(ln) for ln in lines), default=0)
    
    if max_line_length <= 100:
        scan_score = 100
    else:
        scan_score = max(0, int(100 - (max_line_length - 100) * 0.5))
    
    paragraphs = text.split('\n\n')
    para_score = 100 if 2 <= len(paragraphs) <= 5 else max(0, 100 - abs(len(paragraphs) - 3) * 15)
    
    final_score = int(
        0.30 * readability +
        0.15 * emoji_score +
        0.25 * question_score +
        0.20 * scan_score +
        0.10 * para_score
    )
    
    return min(100, final_score)


def _content_quality_score(text: str, keywords: List[str]) -> int:
    """Calculate overall content quality for LinkedIn."""
    word_count = len(WORD_REGEX.findall(text))
    
    if 150 <= word_count <= 220:
        length_score = 100
    elif 120 <= word_count <= 250:
        length_score = 85
    else:
        length_score = max(0, 100 - abs(word_count - 185) * 2)
    
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