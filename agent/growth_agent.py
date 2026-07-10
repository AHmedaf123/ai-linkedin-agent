"""Growth engine: engagement actions beyond posting.

Three capabilities, all opt-in and rate-limited through persistent daily
counters in agent/storage.py (so limits hold across processes and CI runs):

  1. First-comment: after publishing, the agent leaves the first comment on its
     own post with one extra insight (raises dwell time / early engagement).
  2. Niche commenting: finds recent posts for the configured niches and leaves
     a short, specific, LLM-generated comment (never generic praise).
  3. Connection requests: sends a small number of connect requests to people
     surfaced by niche keyword search.

Safety posture:
  - Disabled unless ENABLE_GROWTH=true (first-comment: ENABLE_FIRST_COMMENT=true).
  - Conservative daily caps (comments: GROWTH_MAX_COMMENTS_PER_DAY, default 8;
    connects: GROWTH_MAX_CONNECTS_PER_DAY, default 12) — keep these well under
    LinkedIn's limits; automation of this kind is against LinkedIn's ToS and
    aggressive volumes risk account restriction.
  - Human-like pacing: random 25–90s waits between actions plus scrolling.
"""

import os
import random
import re
import time
import logging
from typing import List, Optional

from agent import storage
from agent.linkedin_poster import LinkedInPoster, _random_wait
from agent.llm_generator import LLMGenerator

logger = logging.getLogger("linkedin-agent")

COMMENTS_COUNTER = "growth_comments"
CONNECTS_COUNTER = "growth_connections"

GENERIC_COMMENT_MARKERS = [
    "great post", "nice post", "thanks for sharing", "well said",
    "totally agree", "love this", "interesting post", "awesome",
]


def _daily_cap(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _pace():
    """Human-like pause between actions."""
    lo = float(os.getenv("GROWTH_MIN_DELAY_S", "25"))
    hi = float(os.getenv("GROWTH_MAX_DELAY_S", "90"))
    delay = random.uniform(lo, max(lo, hi))
    logger.debug(f"Growth pacing: sleeping {delay:.0f}s")
    time.sleep(delay)


def _clean_comment(text: str) -> str:
    text = (text or "").strip().strip('"').strip()
    text = re.sub(r"#\w+", "", text)          # no hashtags in comments
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _is_acceptable_comment(text: str) -> bool:
    if not text or len(text.split()) < 8 or len(text) > 600:
        return False
    lowered = text.lower()
    return not any(marker in lowered for marker in GENERIC_COMMENT_MARKERS)


def generate_comment(post_text: str, as_author: bool = False) -> Optional[str]:
    """LLM-generated comment; returns None when nothing acceptable comes back."""
    if as_author:
        instruction = (
            "You just published the LinkedIn post below. Write the FIRST COMMENT on your own post "
            "adding ONE extra insight, caveat, or resource that did not fit in the post. "
            "20-40 words, first person, no hashtags, no emojis, no self-congratulation."
        )
    else:
        instruction = (
            "Write a thoughtful LinkedIn comment on the post below. Add one specific technical point, "
            "a concrete example from the field, or one sharp informed question. 20-50 words. "
            "Never use generic praise ('great post', 'thanks for sharing'). No hashtags, at most one emoji."
        )
    messages = [{
        "role": "user",
        "content": (
            "SYSTEM INSTRUCTION: You are an AI/ML researcher engaging authentically on LinkedIn.\n\n"
            f"{instruction}\n\nPOST:\n{post_text[:1200]}\n\nReply with the comment text only."
        ),
    }]
    for _ in range(2):
        try:
            raw = LLMGenerator._call_openrouter(messages, max_tokens=150, temperature=0.7)
            comment = _clean_comment(raw)
            if _is_acceptable_comment(comment):
                return comment
        except Exception as e:
            logger.warning(f"Comment generation failed: {e}")
    return None


class GrowthAgent(LinkedInPoster):
    """Reuses the poster's Playwright session for engagement actions."""

    def _submit_comment(self, container, comment_text: str) -> bool:
        """Open the comment box inside a post container, type, submit."""
        try:
            comment_btn = container.locator(
                "button[aria-label*='Comment' i], button:has-text('Comment')"
            ).first
            if comment_btn.count() == 0:
                return False
            comment_btn.click(timeout=5000)
            _random_wait(800, 1600)

            editor = container.locator(
                ".comments-comment-box div[contenteditable='true'], div[contenteditable='true'][role='textbox']"
            ).last
            if editor.count() == 0:
                editor = self.page.locator("div[contenteditable='true'][role='textbox']").last
            if editor.count() == 0:
                return False
            editor.click(timeout=3000)
            editor.fill(comment_text)
            _random_wait(700, 1400)

            for sel in [
                "button.comments-comment-box__submit-button--cr",
                "button.comments-comment-box__submit-button",
                "button:has-text('Comment')",
                "button[class*='submit']",
            ]:
                submit = container.locator(sel).first
                if submit.count() == 0:
                    submit = self.page.locator(sel).first
                if submit.count() > 0 and submit.is_visible():
                    submit.click(timeout=4000)
                    _random_wait(1000, 2000)
                    return True
            # Fallback: Ctrl+Enter submits in the LinkedIn comment box
            editor.press("Control+Enter")
            _random_wait(1000, 2000)
            return True
        except Exception as e:
            logger.warning(f"Failed to submit comment: {e}")
            return False

    # --- 1. First comment on own post -----------------------------------------

    def post_first_comment(self, own_profile_url: str, post_snippet: str, comment_text: str) -> bool:
        try:
            self._setup()
            self._login()
            url = f"{own_profile_url.rstrip('/')}/recent-activity/all/"
            self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
            self._dismiss_banners()
            _random_wait(1500, 3000)

            containers = self.page.locator("div.feed-shared-update-v2, div[data-urn*='urn:li:activity']")
            needle = " ".join(post_snippet.split()).lower()[:60]
            target = None
            for i in range(min(containers.count(), 5)):
                c = containers.nth(i)
                try:
                    text = " ".join(c.inner_text(timeout=4000).split()).lower()
                except Exception:
                    continue
                if needle and needle in text:
                    target = c
                    break
            if target is None and containers.count() > 0:
                target = containers.first  # newest post is the one just published
            if target is None:
                logger.warning("First-comment: could not locate own post")
                return False

            ok = self._submit_comment(target, comment_text)
            logger.info(f"First comment {'posted' if ok else 'FAILED'} on own post")
            return ok
        except Exception as e:
            logger.error(f"First-comment failed: {e}", exc_info=True)
            return False
        finally:
            self._teardown()

    # --- 2 & 3. Niche engagement session ---------------------------------------

    def _comment_on_search_results(self, keyword: str, budget: int) -> int:
        """Comment on recent niche posts; returns number of comments made."""
        made = 0
        url = f"https://www.linkedin.com/search/results/content/?keywords={keyword.replace(' ', '%20')}&sortBy=%22date_posted%22"
        self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self._dismiss_banners()
        _random_wait(2000, 3500)

        containers = self.page.locator("div.feed-shared-update-v2, div[data-urn*='urn:li:activity']")
        n = containers.count()
        logger.info(f"Niche search '{keyword}': {n} posts visible")
        for i in range(min(n, budget * 2)):
            if made >= budget:
                break
            c = containers.nth(i)
            try:
                post_text = c.inner_text(timeout=4000)
            except Exception:
                continue
            if len(post_text.strip()) < 120:
                continue
            comment = generate_comment(post_text)
            if not comment:
                continue
            if self._submit_comment(c, comment):
                made += 1
                storage.increment_daily_counter(COMMENTS_COUNTER)
                logger.info(f"Commented on niche post ({made}/{budget}): {comment[:80]!r}")
                _pace()
        return made

    def _send_connection_requests(self, keyword: str, budget: int) -> int:
        """Send connect requests from a people search; returns number sent."""
        sent = 0
        url = f"https://www.linkedin.com/search/results/people/?keywords={keyword.replace(' ', '%20')}"
        self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self._dismiss_banners()
        _random_wait(2000, 3500)

        buttons = self.page.locator("button:has-text('Connect')")
        n = buttons.count()
        logger.info(f"People search '{keyword}': {n} Connect buttons visible")
        for i in range(min(n, budget)):
            try:
                btn = buttons.nth(i)
                if not btn.is_visible():
                    continue
                btn.click(timeout=4000)
                _random_wait(900, 1800)
                # Modal: send without a personalized note
                for sel in ["button[aria-label='Send without a note']",
                            "button:has-text('Send without a note')",
                            "button[aria-label='Send now']",
                            "button:has-text('Send')"]:
                    modal_btn = self.page.locator(sel).first
                    if modal_btn.count() > 0 and modal_btn.is_visible():
                        modal_btn.click(timeout=3000)
                        break
                sent += 1
                storage.increment_daily_counter(CONNECTS_COUNTER)
                logger.info(f"Connection request sent ({sent}/{budget})")
                _pace()
            except Exception as e:
                logger.debug(f"Connect attempt {i} failed: {e}")
                continue
        return sent

    def run_growth_session(self, niches: List[str]) -> dict:
        """One browser session: niche comments then connection requests."""
        max_comments = _daily_cap("GROWTH_MAX_COMMENTS_PER_DAY", 8)
        max_connects = _daily_cap("GROWTH_MAX_CONNECTS_PER_DAY", 12)
        comments_left = max_comments - storage.get_daily_counter(COMMENTS_COUNTER)
        connects_left = max_connects - storage.get_daily_counter(CONNECTS_COUNTER)
        result = {"comments": 0, "connections": 0}

        if comments_left <= 0 and connects_left <= 0:
            logger.info("Growth session skipped: daily caps already reached")
            return result
        if not niches:
            logger.warning("Growth session skipped: no niches configured")
            return result

        try:
            self._setup()
            self._login()
            keywords = random.sample(niches, min(2, len(niches)))
            for kw in keywords:
                if comments_left - result["comments"] <= 0:
                    break
                result["comments"] += self._comment_on_search_results(
                    kw, budget=max(1, (comments_left - result["comments"]) // len(keywords) or 1)
                )
            if connects_left > 0:
                result["connections"] = self._send_connection_requests(
                    random.choice(niches), budget=connects_left
                )
            logger.info(f"Growth session done: {result}")
            return result
        except Exception as e:
            logger.error(f"Growth session failed: {e}", exc_info=True)
            return result
        finally:
            self._teardown()


# --- Public entry points --------------------------------------------------------

def _credentials():
    email = os.getenv("LINKEDIN_EMAIL") or os.getenv("LINKEDIN_USER")
    password = os.getenv("LINKEDIN_PASSWORD") or os.getenv("LINKEDIN_PASS")
    return email, password


def run_first_comment(profile_url: str, post_body: str) -> bool:
    """Generate an extra-insight comment and post it under the just-published post."""
    if os.getenv("ENABLE_FIRST_COMMENT", "false").lower() != "true":
        logger.info("First-comment disabled (ENABLE_FIRST_COMMENT != true)")
        return False
    comment = generate_comment(post_body, as_author=True)
    if not comment:
        logger.warning("First-comment skipped: could not generate an acceptable comment")
        return False
    email, password = _credentials()
    agent = GrowthAgent(email=email, password=password)
    snippet = (post_body or "").strip()[:80]
    return agent.post_first_comment(profile_url, snippet, comment)


def run_growth(niches: List[str]) -> dict:
    """Run a rate-limited engagement session (comments + connection requests)."""
    if os.getenv("ENABLE_GROWTH", "false").lower() != "true":
        logger.info("Growth engine disabled (ENABLE_GROWTH != true)")
        return {"comments": 0, "connections": 0}
    email, password = _credentials()
    agent = GrowthAgent(email=email, password=password)
    return agent.run_growth_session(niches)
