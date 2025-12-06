import re
from collections import Counter
from typing import List

STOPWORDS = {
    "a", "an", "the", "and", "or", "if", "but", "with", "on", "in", "to", "for", 
    "of", "by", "from", "is", "are", "was", "were", "be", "been", "being", "this", 
    "that", "it", "as", "at", "we", "you", "i", "have", "has", "had", "will", "would",
    "can", "could", "should", "may", "might", "about", "into", "through", "during",
    "before", "after", "above", "below", "between", "under", "again", "further",
    "then", "once", "here", "there", "all", "both", "each", "few", "more", "most",
    "other", "some", "such", "only", "own", "same", "so", "than", "too", "very"
}

DOMAIN_KEYWORDS = {
    "ai", "ml", "machinelearning", "deeplearning", "neuralnetwork", "model",
    "algorithm", "data", "dataset", "training", "inference", "prediction",
    "classification", "regression", "clustering", "drugdiscovery", "molecule",
    "protein", "bioinformatics", "computational", "biology", "chemistry",
    "generative", "transformer", "attention", "gan", "vae", "diffusion",
    "optimization", "research", "paper", "arxiv", "github", "opensource"
}


def advanced_tokenize(text: str) -> List[str]:
    """Advanced tokenization preserving technical terms and compounds."""
    text = text.lower()
    
    pattern = r'\b[a-z][a-z0-9\-\+_]*\b'
    tokens = re.findall(pattern, text)
    
    preserved_tokens = []
    for token in tokens:
        if '-' in token or '_' in token or '+' in token:
            preserved_tokens.append(token)
        else:
            preserved_tokens.append(token)
    
    return preserved_tokens


def extract_keywords(messages: List[str], top_k: int = 12) -> List[str]:
    """Extract keywords with TF-IDF-like scoring and domain relevance."""
    if isinstance(messages, str):
        messages = [messages]
    
    all_tokens = []
    for msg in messages:
        tokens = advanced_tokenize(msg)
        filtered = [t for t in tokens if t not in STOPWORDS and len(t) > 2]
        all_tokens.extend(filtered)
    
    if not all_tokens:
        return []
    
    freq = Counter(all_tokens)
    
    scored_keywords = []
    for word, count in freq.items():
        base_score = count
        
        if word in DOMAIN_KEYWORDS:
            domain_bonus = 2.0
        elif any(domain_kw in word for domain_kw in DOMAIN_KEYWORDS):
            domain_bonus = 1.5
        else:
            domain_bonus = 1.0
        
        length_bonus = min(1.5, len(word) / 10.0)
        
        final_score = base_score * domain_bonus * length_bonus
        scored_keywords.append((word, final_score))
    
    scored_keywords.sort(key=lambda x: x[1], reverse=True)
    
    return [word for word, score in scored_keywords[:top_k]]


def map_hashtags(keywords: List[str], bank_broad: List[str], bank_niche: List[str], 
                cap: int = 6) -> List[str]:
    """Map keywords to relevant hashtags with semantic matching."""
    picked = []
    
    for kw in keywords:
        kw_lower = kw.lower()
        
        for tag in bank_niche:
            tag_clean = tag.lower().replace('#', '')
            
            if (kw_lower in tag_clean or 
                tag_clean in kw_lower or 
                any(kw_lower in part or part in kw_lower for part in tag_clean.split('-'))):
                if tag not in picked:
                    picked.append(tag)
                    break
        
        if len(picked) >= cap:
            break
    
    for tag in bank_niche:
        if tag not in picked:
            picked.append(tag)
        if len(picked) >= cap // 2:
            break
    
    for tag in bank_broad:
        if tag not in picked:
            picked.append(tag)
        if len(picked) >= cap:
            break
    
    return picked[:cap]