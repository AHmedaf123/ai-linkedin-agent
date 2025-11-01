import os,re,json,requests
from typing import List,Tuple,Dict,Any

OPENROUTER_API_URL="https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL=os.getenv("OPENROUTER_MODEL","google/gemma-3n-e2b-it:free")

SEO_SYS="You are an expert LinkedIn growth + SEO editor. Return strict JSON only."
SEO_USER_PREFIX=(
"Optimize the LinkedIn post below. Goals: clarity, engagement, discoverability. Rules: 120–200 words and <1300 chars; short lines; no section labels; no 'Suggested visual' or 'Character count'; 3–6 hashtags at end (mix broad+niche); natural domain keywords; keep any valid @mentions and links. Return JSON keys: optimized_post, llm_seo_score (0-100), keywords (<=12), hashtags (3-6). Post:\n\n"
)

EMOJI_RE=re.compile(r"[\U0001F300-\U0001FAFF]")
WORD_RE=re.compile(r"\b\w+\b")
HASHTAG_RE=re.compile(r"#\w+")

BROAD={"#ai","#machinelearning","#datascience","#deeplearning","#python","#neuralnetworks","#bigdata","#tech","#innovation"}
NICHE={"#bioinformatics","#drugdiscovery","#gans","#mlops","#computationalbiology","#molecularmodeling","#healthcare","#generativeai","#moleculardesign","#airesearch"}

def _load_api_key()->str:
    k=os.getenv("OPENROUTER_API_KEY")
    if k:return k
    try:
        from dotenv import load_dotenv
        load_dotenv();k=os.getenv("OPENROUTER_API_KEY");
    except: k=None
    if not k: raise RuntimeError("OPENROUTER_API_KEY not set")
    return k

def _call_openrouter(prompt:str,max_tokens:int=700,temperature:float=0.4)->Dict[str,Any]:
    headers={"Authorization":f"Bearer {_load_api_key()}","Content-Type":"application/json"}
    payload={"model":DEFAULT_MODEL,"messages":[{"role":"system","content":SEO_SYS},{"role":"user","content":SEO_USER_PREFIX+prompt}],"temperature":temperature,"top_p":0.9,"max_tokens":max_tokens,"include_reasoning":False,"response_format":{"type":"json_object"}}
    err=None
    for a in range(3):
        try:
            r=requests.post(OPENROUTER_API_URL,headers=headers,data=json.dumps(payload),timeout=120)
            if r.status_code<400:
                return r.json()
            err=RuntimeError(f"OpenRouter {r.status_code}: {r.text[:200]}")
        except Exception as e:
            err=e
        import time;time.sleep(1.5*(a+1))
    raise err or RuntimeError("OpenRouter request failed")

def _strip_labels(text:str)->str:
    if not text:return ""
    # Remove markdown formatting
    text=re.sub(r'\*\*([^*]+)\*\*',r'\1',text)  # Remove bold
    text=re.sub(r'\*([^*]+)\*',r'\1',text)  # Remove italic
    text=re.sub(r'^#+\s+','',text,flags=re.MULTILINE)  # Remove headers
    
    label_prefix=re.compile(r'^\s*(\*\*)?(\d+\)\s*)?(Hook|Context/Story|Context|Insights/Value|Insights|CTA)\s*(\*\*)?[:\-–—]\s*',re.I)
    label_only=re.compile(r'^\s*(\*\*)?(\d+\)\s*)?(Hook|Context/Story|Context|Insights/Value|Insights|CTA)\s*(\*\*)?[:\-–—]?\s*$',re.I)
    out=[];prev_blank=False
    for raw in text.splitlines():
        l=raw.strip()
        if re.search(r'(?i)Suggested\s+visual',l) or re.search(r'(?i)Character\s*count',l) or re.search(r'(?i)for\s+tool\s+relevance',l):
            continue
        if label_only.match(l):
            continue
        l=label_prefix.sub('',l)
        if not l and prev_blank: continue
        out.append(l)
        prev_blank=(l=="")
    return "\n".join(out).strip()

def _kw_density_score(text:str,keywords:List[str])->int:
    words=[w.lower() for w in WORD_RE.findall(text.lower())];tw=len(words)
    if not tw:return 0
    ks=sum(1 for w in words if w in {k.lower() for k in keywords});d=(ks/tw)*100
    if 2<=d<=5:return 100
    if d<2:return int(min(2,d)/2*100)
    return max(0,int(100-(d-5)*20))

def _hashtag_diversity_score(tags:List[str])->int:
    if not tags:return 0
    tags=[t.lower() for t in tags]
    c=len(tags)
    count=100 if 3<=c<=6 else max(0,100-abs(c-5)*20)
    b=sum(1 for t in tags if t in BROAD);n=sum(1 for t in tags if t in NICHE)
    div=int(min(b,n)/max(b or 1,n or 1)*100) if (b and n) else 50 if (b or n) else 0
    uniq=int(len(set(tags))/max(1,c)*100)
    return int(0.5*count+0.3*div+0.2*uniq)

def _readability_score(text:str)->int:
    s=[x.strip() for x in re.split(r'[.!?]\s',text) if x.strip()]
    if not s:return 0
    lens=[len(WORD_RE.findall(x)) for x in s];avg=sum(lens)/len(s)
    length=100 if 12<=avg<=22 else max(0,int(100-abs(avg-17)*6))
    emojis=min(100,len(EMOJI_RE.findall(text))*20)
    lines=[ln for ln in text.splitlines() if ln.strip()];
    maxlen=max((len(ln) for ln in lines),default=0)
    scan=100 if maxlen<=120 else max(0,int(100-(maxlen-120)*0.8))
    return int(0.5*length+0.2*emojis+0.3*scan)

def _heuristic_score(text:str,keywords:List[str],hashtags:List[str])->int:
    kd=_kw_density_score(text,keywords)
    hd=_hashtag_diversity_score(hashtags)
    rd=_readability_score(text)
    return int(0.45*kd+0.3*hd+0.25*rd)

def optimize_post_full(text:str)->Dict[str,Any]:
    raw=_strip_labels(text)
    llm_resp=_call_openrouter(raw)
    content=llm_resp["choices"][0]["message"]["content"]
    try:
        data=json.loads(content)
    except Exception:
        data={"optimized_post":raw,"llm_seo_score":60,"keywords":[],"hashtags":[]}
    opt=_strip_labels(str(data.get("optimized_post",""))) or raw
    tags=[t if t.startswith('#') else f'#{t}' for t in data.get("hashtags",[]) if isinstance(t,str)]
    tags=[t.strip() for t in tags if t.strip()]
    tags=[t for i,t in enumerate(tags) if t.lower() not in {x.lower() for x in tags[:i]}]
    kw=[k.strip() for k in data.get("keywords",[]) if isinstance(k,str) and k.strip()]
    llm_score=int(max(0,min(100,int(data.get("llm_seo_score",60)))))
    heur=_heuristic_score(opt,kw,tags)
    final=int(0.6*llm_score+0.4*heur)
    # ensure hashtags at end
    body_no_tags=HASHTAG_RE.sub('',opt).rstrip()
    tail_tags=" ".join(tags[:6])
    if tail_tags:
        optimized=body_no_tags+("\n\n" if not body_no_tags.endswith("\n") else "\n")+tail_tags
    else:
        optimized=body_no_tags
    return {"optimized_post":optimized.strip(),"seo_score":final,"keywords":kw,"hashtags":tags[:6],"llm_score":llm_score,"heuristic_score":heur}

def optimize_post(text:str)->Tuple[int,List[str]]:
    r=optimize_post_full(text)
    return r["seo_score"],r["keywords"]