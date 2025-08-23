import re
from collections import Counter

STOP = set("""a an the and or if but with on in to for of by from is are was were be been being this that it as at we you i""".split())

def tokenize(text):
    return [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9\-\+_]*", text)]

def extract_keywords(messages, top_k=8):
    tokens = []
    for m in messages:
        tokens += [t for t in tokenize(m) if t not in STOP and len(t) > 2]
    freq = Counter(tokens)
    return [w for w,_ in freq.most_common(top_k)]

def map_hashtags(keywords, bank_broad, bank_niche, cap=6):
    # naive: prefer niche if keyword overlaps or semantically similar (string contains)
    picked = []
    all_cands = bank_niche + bank_broad
    for kw in keywords:
        for tag in bank_niche:
            if kw.lower() in tag.lower() or tag.lower().replace('#', '') in kw.lower():
                if tag not in picked:
                    picked.append(tag)
                break
    
    # add broad hashtags if we haven't hit the cap
    if len(picked) < cap:
        for tag in bank_broad:
            if tag not in picked:
                picked.append(tag)
            if len(picked) >= cap:
                break
    
    return picked[:cap]