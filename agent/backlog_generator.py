import requests, json, os, base64
# Fix import path
from .seo_optimizer import optimize_post

QUEUE = "agent/repo_queue.json"
USED = "agent/used_repos.json"

def fetch_readme_content(repo, github_token=None):
    """Fetch README content from GitHub repository"""
    url = f"https://api.github.com/repos/AHmedaf123/{repo}/readme"
    headers = {}
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            readme_data = r.json()
            # Decode base64 content
            content = base64.b64decode(readme_data['content']).decode('utf-8')
            # Extract first few sentences or paragraphs
            lines = content.split('\n')
            description_lines = []
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#') and not line.startswith('!') and not line.startswith('['):
                    description_lines.append(line)
                    if len(' '.join(description_lines)) > 150:  # Limit description length
                        break
            return ' '.join(description_lines)[:200] + "..." if len(' '.join(description_lines)) > 200 else ' '.join(description_lines)
    except (requests.RequestException, json.JSONDecodeError, KeyError) as e:
        print(f"Error fetching README for {repo}: {str(e)}")
    
    return None

def fetch_repo_details(repo):
    url = f"https://api.github.com/repos/AHmedaf123/{repo}"
    github_token = os.getenv("GITHUB_TOKEN")
    headers = {}
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
    except (requests.RequestException, json.JSONDecodeError) as e:
        print(f"Error fetching repo details for {repo}: {str(e)}")
        return None
    
    # Fetch README content
    readme_content = fetch_readme_content(repo, github_token)
    
    return {
        "name": data["name"],
        "desc": data.get("description", "AI-based project."),
        "readme": readme_content,
        "url": data["html_url"],
        "language": data.get("language", "Python"),
        "topics": data.get("topics", [])
    }

# Delayed import to avoid circular dependency
# from .llm_generator import generate_post as llm_generate_post

def generate_repo_post(repo):
    """Generate a repo-based LinkedIn post using LLM (DeepSeek R1 via OpenRouter).
    Falls back to simple template if repo details cannot be fetched.
    """
    data = fetch_repo_details(repo)
    if not data:
        return None

    # Try LLM generation first (lazy import to avoid circular dependency)
    try:
        from .llm_generator import generate_post as llm_generate_post  # local import
        post = llm_generate_post(repo=data)
        if post:
            return post
    except Exception:
        # Fallback below if LLM unavailable
        pass

    # Fallback: minimal template if LLM fails
    readme_preview = f"\n\n📖 What it does: {data['readme']}" if data.get('readme') else ""
    body = (
        f"Showcasing: {data['name']}\n\n"
        f"{data.get('desc','AI-based project.')}\n"
        f"{readme_preview}\n\n"
        f"🔗 {data['url']}"
    )
    seo_score, seo_keywords = optimize_post(body)
    return {
        "title": f"{data['name']} — Highlights",
        "body": body.strip(),
        "seo_score": seo_score,
        "seo_keywords": seo_keywords,
        "hashtags": ["#AI", "#MachineLearning", "#OpenSource", "#GitHub"]
    }

def get_next_repo_post(skip_current=False):
    try:
        with open(QUEUE, "r") as f:
            repos = json.load(f)["pending_repos"]
    except (FileNotFoundError, json.JSONDecodeError, PermissionError) as e:
        print(f"Error loading repo queue: {str(e)}")
        return None

    if not repos:
        return None  # fallback to niche topic

    # If skip_current is True, try to get the second repo in the queue
    if skip_current and len(repos) > 1:
        repo = repos.pop(1)  # Take the second repo
    else:
        repo = repos.pop(0)  # Take the first repo
        
    try:
        with open(QUEUE, "w") as f:
            json.dump({"pending_repos": repos}, f, indent=2)
    except (PermissionError, OSError) as e:
        print(f"Error saving repo queue: {str(e)}")
        return None
        return None

    # Mark repo as used
    try:
        if os.path.exists(USED):
            with open(USED, "r") as f:
                used = json.load(f)
        else:
            used = []
        used.append(repo)
        with open(USED, "w") as f:
            json.dump(used, f, indent=2)
    except (FileNotFoundError, json.JSONDecodeError, PermissionError, OSError) as e:
        print(f"Error updating used repos: {str(e)}")
        # Continue anyway, this is not critical

    try:
        return generate_repo_post(repo)
    except Exception as e:
        print(f"Error generating post for repo {repo}: {str(e)}")
        return None