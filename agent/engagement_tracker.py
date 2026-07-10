"""LinkedIn engagement collection on Playwright (same browser stack as the poster).

Scrapes the account's recent-activity feed for likes / comments / reposts /
impressions, joins each scraped post back to the published record in
agent/storage.py by content prefix, and persists the numbers on the post row.

Run standalone via `python run.py --collect-metrics` (scheduled T+24h/T+48h in
.github/workflows/metrics.yml) — every measurement updates the same post, so
later runs naturally refresh earlier numbers.

A JSON mirror is kept at agent/metrics_history.json for the dashboard and for
quick inspection.
"""

import json
import os
import re
import datetime
from typing import Dict, List, Optional

from agent import storage
from agent.linkedin_poster import LinkedInPoster, LinkedInError, _random_wait
from agent.logging_setup import get_logger

logger = get_logger("engagement_tracker")

METRICS_HISTORY_PATH = "agent/metrics_history.json"

# Each pattern requires a leading digit so a stray "." / "," never matches.
_COUNT_PATTERNS = {
    "comments": re.compile(r"(\d[\d,.]*[KkMm]?)\s*comments?", re.I),
    "shares": re.compile(r"(\d[\d,.]*[KkMm]?)\s*reposts?", re.I),
    "impressions": re.compile(r"(\d[\d,.]*[KkMm]?)\s*impressions?", re.I),
    "likes": re.compile(r"(\d[\d,.]*[KkMm]?)\s*reactions?", re.I),
}


def _parse_count(text: str) -> int:
    """'1,234' → 1234; '2.5K' → 2500. Returns 0 for anything non-numeric."""
    text = (text or "").strip().replace(",", "")
    m = re.match(r"(\d+(?:\.\d+)?)\s*([KkMm]?)", text)
    if not m:
        return 0
    try:
        value = float(m.group(1))
    except (ValueError, TypeError):
        return 0
    suffix = m.group(2).lower()
    if suffix == "k":
        value *= 1_000
    elif suffix == "m":
        value *= 1_000_000
    return int(value)


class LinkedInEngagementTracker(LinkedInPoster):
    """Reuses LinkedInPoster's browser lifecycle/login; only reads, never posts."""

    POST_CONTAINER_SELECTORS = [
        "div.feed-shared-update-v2",
        "div[data-urn*='urn:li:activity']",
        "li.profile-creator-shared-feed-update__container",
    ]

    TEXT_SELECTORS = [
        ".update-components-text",
        ".feed-shared-update-v2__description",
        "[data-test-id='main-feed-activity-card__commentary']",
        ".feed-shared-inline-show-more-text",
    ]

    def __init__(self, email: Optional[str] = None, password: Optional[str] = None,
                 profile_url: Optional[str] = None):
        super().__init__(email=email, password=password)
        self.profile_url = (profile_url or "").rstrip("/")

    def _activity_url(self) -> str:
        if self.profile_url:
            return f"{self.profile_url}/recent-activity/all/"
        raise LinkedInError("No LinkedIn profile URL configured (config.json user.linkedin_profile_url)")

    def _extract_post(self, container) -> Optional[Dict]:
        try:
            raw_text = container.inner_text(timeout=5000)
        except Exception:
            return None
        if not raw_text or len(raw_text.strip()) < 30:
            return None

        post_text = ""
        for sel in self.TEXT_SELECTORS:
            try:
                loc = container.locator(sel).first
                if loc.count() > 0:
                    post_text = loc.inner_text(timeout=3000).strip()
                    if post_text:
                        break
            except Exception:
                continue
        if not post_text:
            # Fallback: strip header lines (name/headline/date) and take the rest
            lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
            post_text = " ".join(lines[3:10])
        if len(post_text) < 20:
            return None

        engagement = {"likes": 0, "comments": 0, "shares": 0, "impressions": 0}
        for key, pattern in _COUNT_PATTERNS.items():
            m = pattern.search(raw_text)
            if m:
                engagement[key] = _parse_count(m.group(1))

        # Reactions often render as a bare number next to the reaction icons.
        if engagement["likes"] == 0:
            for sel in [".social-details-social-counts__reactions-count",
                        "span[aria-hidden='true'].social-details-social-counts__reactions-count",
                        "button[aria-label*='reaction' i]"]:
                try:
                    loc = container.locator(sel).first
                    if loc.count() > 0:
                        txt = loc.inner_text(timeout=2000) or loc.get_attribute("aria-label") or ""
                        m = re.search(r"([\d,.]+)", txt)
                        if m:
                            engagement["likes"] = _parse_count(m.group(1))
                            break
                except Exception:
                    continue

        return {
            "content": post_text[:200],
            "timestamp": datetime.datetime.now().isoformat(),
            "engagement": engagement,
        }

    @staticmethod
    def _norm(text: str) -> str:
        return " ".join((text or "").split()).lower()

    def fetch_engagement_metrics(self, max_posts: int = 1) -> List[Dict]:
        """Collect stats ONLY for the agent's own recent post(s).

        We start from what the agent published (storage), newest first, and find
        exactly those posts on the activity feed — never arbitrary reposts or
        older/manual content. By default this is just the latest post the agent
        made.
        """
        posts_data: List[Dict] = []

        targets = storage.get_recent_posts(max_posts)
        if not targets:
            logger.info("No agent-made posts in storage; nothing to collect")
            return posts_data

        # Match by a normalized prefix of each target's body.
        remaining: Dict[str, Dict] = {}
        for t in targets:
            key = self._norm(t.get("body", ""))[:60]
            if len(key) >= 20:
                remaining[key] = t
        if not remaining:
            return posts_data
        logger.info(f"Collecting stats for the latest {len(remaining)} agent post(s): "
                    f"{[t.get('topic') for t in targets]}")

        try:
            self._setup()
            self._login()
            url = self._activity_url()
            logger.info(f"Navigating to recent activity: {url}")
            self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
            self._dismiss_banners()
            _random_wait(1500, 3000)

            for _ in range(4):
                self.page.mouse.wheel(0, 1600)
                _random_wait(700, 1300)

            containers = None
            for sel in self.POST_CONTAINER_SELECTORS:
                loc = self.page.locator(sel)
                if loc.count() > 0:
                    containers = loc
                    break
            if containers is None:
                logger.warning("No post containers found on activity page")
                return posts_data

            scan = min(containers.count(), 30)
            logger.info(f"Scanning up to {scan} of {containers.count()} activity items for the target post(s)")
            for i in range(scan):
                if not remaining:
                    break
                try:
                    raw = self._norm(containers.nth(i).inner_text(timeout=4000))
                except Exception:
                    continue
                matched_key = next((k for k in remaining if k in raw), None)
                if not matched_key:
                    continue
                try:
                    data = self._extract_post(containers.nth(i))
                except Exception as e:
                    logger.warning(f"Extraction failed for a matched post: {e}")
                    continue
                if data:
                    target = remaining.pop(matched_key)
                    data["hash"] = target.get("hash")
                    data["topic"] = target.get("topic")
                    posts_data.append(data)
                    logger.info(f"Matched agent post {target.get('topic')!r}: {data['engagement']}")

            if remaining:
                logger.warning(f"{len(remaining)} target post(s) not found on activity page "
                               f"(may be too new to show stats, or DOM changed)")

            self._persist(posts_data)
            return posts_data
        except Exception as e:
            logger.error(f"Error fetching engagement metrics: {e}", exc_info=True)
            return posts_data
        finally:
            self._teardown()

    def _persist(self, posts_data: List[Dict]) -> None:
        """Update engagement on the agent's stored posts (matched by known hash)."""
        matched = 0
        for item in posts_data:
            eng = item["engagement"]
            h = item.get("hash") or storage.match_post_by_content(item["content"])
            if h:
                storage.update_post_engagement(
                    h,
                    likes=eng["likes"],
                    comments=eng["comments"],
                    shares=eng["shares"],
                    impressions=eng["impressions"],
                )
                item["hash"] = h
                matched += 1
        logger.info(f"Engagement persisted for {matched} agent post(s)")
        _write_metrics_history(posts_data)


def _write_metrics_history(posts_data: List[Dict]) -> None:
    """Maintain the JSON mirror used by the dashboard."""
    try:
        history = {"posts": []}
        if os.path.exists(METRICS_HISTORY_PATH):
            with open(METRICS_HISTORY_PATH, "r", encoding="utf-8") as f:
                history = json.load(f)
        existing = history.get("posts", [])
        for new_post in posts_data:
            for i, old in enumerate(existing):
                if old.get("content") == new_post.get("content"):
                    existing[i] = new_post
                    break
            else:
                existing.append(new_post)
        history["posts"] = existing[-100:]
        history["last_updated"] = datetime.datetime.now().isoformat()
        with open(METRICS_HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        logger.error(f"Error writing metrics history: {e}")


def fetch_linkedin_engagement(linkedin_email: str, linkedin_password: str,
                              max_posts: int = 10, linkedin_profile_url: str = None) -> List[Dict]:
    """Fetch engagement for recent posts and persist it to storage."""
    try:
        tracker = LinkedInEngagementTracker(
            email=linkedin_email, password=linkedin_password, profile_url=linkedin_profile_url
        )
        return tracker.fetch_engagement_metrics(max_posts)
    except Exception as e:
        logger.error(f"Error fetching LinkedIn engagement: {e}")
        return []


def get_engagement_stats() -> Dict:
    """Engagement statistics from persistent storage (measured posts only)."""
    empty = {
        "total_posts": 0,
        "avg_likes": 0,
        "avg_comments": 0,
        "avg_shares": 0,
        "avg_impressions": 0,
        "top_performing_post": None,
    }
    try:
        posts = storage.get_posts_with_engagement(50)
        if not posts:
            return empty
        n = len(posts)
        top = max(posts, key=storage.engagement_score)
        return {
            "total_posts": n,
            "avg_likes": sum(p.get("likes") or 0 for p in posts) / n,
            "avg_comments": sum(p.get("comments") or 0 for p in posts) / n,
            "avg_shares": sum(p.get("shares") or 0 for p in posts) / n,
            "avg_impressions": sum(p.get("impressions") or 0 for p in posts) / n,
            "top_performing_post": {
                "topic": top.get("topic"),
                "hook": top.get("hook"),
                "score": storage.engagement_score(top),
                "likes": top.get("likes"),
                "comments": top.get("comments"),
                "impressions": top.get("impressions"),
            },
        }
    except Exception as e:
        logger.error(f"Error getting engagement stats: {e}")
        empty["error"] = str(e)
        return empty
