import requests
import json
import os
import base64
import logging

from .seo_optimizer import optimize_post

logger = logging.getLogger("linkedin-agent")

QUEUE_PATH = "agent/repo_queue.json"
USED_PATH = "agent/used_repos.json"


def fetch_readme_content(repo: str, github_token: str = None) -> str:
    """Fetch and parse README content from GitHub repository."""
    url = f"https://api.github.com/repos/AHmedaf123/{repo}/readme"
    headers = {}
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            readme_data = resp.json()
            content = base64.b64decode(readme_data['content']).decode('utf-8')
            
            lines = content.split('\n')
            description_lines = []
            skip_patterns = ['#', '!', '[', '```', '---', '===']
            
            for line in lines:
                line = line.strip()
                
                if not line or any(line.startswith(pat) for pat in skip_patterns):
                    continue
                
                if len(line) > 20:
                    description_lines.append(line)
                
                if len(' '.join(description_lines)) > 250:
                    break
            
            summary = ' '.join(description_lines)
            return summary[:300] + "..." if len(summary) > 300 else summary
            
    except Exception as e:
        logger.error(f"Error fetching README for {repo}: {str(e)}")
    
    return ""


def fetch_repo_details(repo: str) -> dict:
    """Fetch comprehensive repository details from GitHub API."""
    url = f"https://api.github.com/repos/AHmedaf123/{repo}"
    github_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_API_TOKEN")
    
    headers = {}
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            logger.error(f"GitHub API returned {resp.status_code} for {repo}")
            return None
        
        data = resp.json()
    except Exception as e:
        logger.error(f"Error fetching repo details for {repo}: {str(e)}")
        return None
    
    readme_content = fetch_readme_content(repo, github_token)
    
    return {
        "name": data["name"],
        "desc": data.get("description") or "An AI-based project",
        "readme": readme_content,
        "url": data["html_url"],
        "language": data.get("language", "Python"),
        "topics": data.get("topics", []),
        "stars": data.get("stargazers_count", 0),
        "forks": data.get("forks_count", 0)
    }


def generate_repo_post(repo: str) -> dict:
    """Generate a repository-based LinkedIn post using LLM."""
    data = fetch_repo_details(repo)
    if not data:
        return None
    
    try:
        from .llm_generator import generate_post as llm_generate_post
        post = llm_generate_post(repo=data)
        if post:
            return post
    except Exception as e:
        logger.error(f"LLM generation failed for {repo}: {str(e)}")
    
    readme_snippet = f"\n\n{data['readme']}" if data.get('readme') else ""
    stars_info = f"⭐ {data['stars']} stars" if data.get('stars', 0) > 0 else ""
    
    fallback_body = f"""Just wrapped up work on {data['name']}, and I'm excited to share it with the community.

{data.get('desc', 'An AI-based project focused on solving real-world challenges.')}{readme_snippet}

Built with {data.get('language', 'Python')}, this project tackles some interesting problems in the {', '.join(data.get('topics', ['AI'])[:3])} space. {stars_info}

Check it out and let me know your thoughts. Always open to feedback and collaboration.

🔗 {data['url']}

#AI #MachineLearning #OpenSource #GitHub"""
    
    seo_score, seo_keywords = optimize_post(fallback_body)
    
    return {
        "title": f"{data['name']} - Project Showcase",
        "body": fallback_body.strip(),
        "seo_score": seo_score,
        "seo_keywords": seo_keywords,
        "hashtags": ["#AI", "#MachineLearning", "#OpenSource", "#GitHub"]
    }


def get_next_repo_post(skip_current: bool = False) -> dict:
    """Get next repository post from queue."""
    try:
        with open(QUEUE_PATH, "r") as f:
            repos = json.load(f)["pending_repos"]
    except Exception as e:
        logger.error(f"Error loading repo queue: {str(e)}")
        return None
    
    if not repos:
        return None
    
    if skip_current and len(repos) > 1:
        repo = repos.pop(1)
    else:
        repo = repos.pop(0)
    
    try:
        with open(QUEUE_PATH, "w") as f:
            json.dump({"pending_repos": repos}, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving repo queue: {str(e)}")
        return None
    
    try:
        if os.path.exists(USED_PATH):
            with open(USED_PATH, "r") as f:
                used = json.load(f)
        else:
            used = []
        
        used.append(repo)
        
        with open(USED_PATH, "w") as f:
            json.dump(used, f, indent=2)
    except Exception as e:
        logger.warning(f"Error updating used repos: {str(e)}")
    
    try:
        return generate_repo_post(repo)
    except Exception as e:
        logger.error(f"Error generating post for {repo}: {str(e)}")
        return None