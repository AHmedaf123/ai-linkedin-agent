import requests, datetime as dt, time, logging, random
from typing import Dict, List, Any, Optional

logger = logging.getLogger("linkedin-agent")

def fetch_recent_github_activity(username: str, days: int = 2, token: Optional[str] = None, max_retries: int = 3):
    """Fetch recent GitHub activity for a user with rate limit handling
    
    Args:
        username: GitHub username
        days: Number of days of history to fetch
        token: GitHub API token for higher rate limits
        max_retries: Maximum number of retries on rate limit or server errors
        
    Returns:
        Dict containing recent commits, PRs, stars, and issues
    """
    url = f"https://api.github.com/users/{username}/events/public"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "AI-LinkedIn-Agent"
    }
    
    # Add token if provided
    if token:
        headers["Authorization"] = f"token {token}"
    
    # Initialize ETag storage for conditional requests
    etag = None
    events = []
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            # Add ETag for conditional request if we have one
            if etag:
                headers["If-None-Match"] = etag
            
            logger.info(f"Fetching GitHub activity for user {username}")
            r = requests.get(url, headers=headers, timeout=30)
            
            # Store ETag for future requests
            if "ETag" in r.headers:
                etag = r.headers["ETag"]
            
            # Handle rate limiting
            if r.status_code == 403 or r.status_code == 429:
                # Check rate limit info
                reset_time = int(r.headers.get("X-RateLimit-Reset", 0))
                if reset_time > 0:
                    wait_time = max(reset_time - int(time.time()), 0)
                    logger.warning(f"Rate limited by GitHub API. Waiting {wait_time} seconds until reset.")
                    if wait_time > 0 and wait_time < 900:  # Don't wait more than 15 minutes
                        time.sleep(wait_time + 1)  # Add 1 second buffer
                        retry_count += 1
                        continue
                
                # If no reset time or too long, use exponential backoff
                wait_time = (2 ** retry_count) + random.uniform(0, 1)
                logger.warning(f"GitHub API request failed with status {r.status_code}. Retrying in {wait_time:.1f} seconds.")
                time.sleep(wait_time)
                retry_count += 1
                continue
            
            # Handle not modified (304) - use cached data
            if r.status_code == 304:
                logger.info("GitHub data not modified since last request")
                break
                
            # Handle other errors
            if r.status_code != 200:
                logger.warning(f"GitHub API request failed with status {r.status_code}: {r.text}")
                # Use exponential backoff for server errors (5xx)
                if r.status_code >= 500:
                    wait_time = (2 ** retry_count) + random.uniform(0, 1)
                    logger.warning(f"Server error. Retrying in {wait_time:.1f} seconds.")
                    time.sleep(wait_time)
                    retry_count += 1
                    continue
                # For client errors other than rate limiting, just break
                break
            
            # Success - parse the data
            events = r.json()
            break
            
        except requests.RequestException as e:
            logger.error(f"Error fetching GitHub activity: {str(e)}")
            # Use exponential backoff
            wait_time = (2 ** retry_count) + random.uniform(0, 1)
            logger.warning(f"Request error. Retrying in {wait_time:.1f} seconds.")
            time.sleep(wait_time)
            retry_count += 1
            if retry_count >= max_retries:
                logger.error("Max retries reached for GitHub API")
                break
    
    # Process the events
    signal = {
        "commits": [],
        "prs": [],
        "stars": [],
        "issues": [],
    }
    
    if not events:
        logger.warning("No GitHub events retrieved")
        return signal
    
    try:
        # Filter events by date
        cutoff = dt.datetime.utcnow() - dt.timedelta(days=days)
        def to_dt(s): 
            return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
        recent = [e for e in events if to_dt(e["created_at"]) >= cutoff]
        
        # Extract relevant information
        for e in recent:
            t = e.get("type")
            repo = e.get("repo", {}).get("name", "")
            if t == "PushEvent":
                for c in e["payload"].get("commits", []):
                    signal["commits"].append({
                        "repo": repo,
                        "msg": c.get("message","").strip()
                    })
            elif t == "PullRequestEvent":
                pr = e["payload"]["pull_request"]
                signal["prs"].append({"repo": repo, "title": pr.get("title","").strip(), "action": e["payload"].get("action","")})
            elif t == "WatchEvent":  # starred
                signal["stars"].append({"repo": repo})
            elif t == "IssuesEvent":
                issue = e["payload"]["issue"]
                signal["issues"].append({"repo": repo, "title": issue.get("title","").strip(), "action": e["payload"].get("action","")})
    except Exception as e:
        logger.error(f"Error processing GitHub events: {str(e)}")
    
    logger.info(f"Processed {len(recent)} GitHub events: {len(signal['commits'])} commits, {len(signal['prs'])} PRs, {len(signal['stars'])} stars, {len(signal['issues'])} issues")
    return signal