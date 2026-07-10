"""Performance digest: turns stored post-engagement history into (1) prompt
context for the LLM and (2) a pre-publish gate against known-bad patterns.

SCALABILITY CONTRACT
--------------------
The digest fed to the LLM is ALWAYS bounded in size, regardless of how many
posts are in the database (10 or 100,000):

  - Top-N best posts (raw hook + topic + score)          -> N lines  (default 5)
  - Bottom-N worst posts (raw hook + topic)              -> N lines  (default 5)
  - Everything else is compressed into aggregate rows    -> a few lines
    (best topics / length bucket / hashtag count / hour), computed with SQL
    GROUP BY inside storage.py, not by pulling rows into Python.
  - Recent hooks to avoid                                -> up to 8 lines

All aggregation is time-decayed and windowed (recent posts weigh more), so the
system keeps adapting to current LinkedIn behaviour instead of averaging over
years of stale data.
"""

import logging
from typing import Dict, List, Tuple

from agent import storage
from agent.deduper import _tfidf_max_similarity

logger = logging.getLogger("linkedin-agent")

LOW_PERFORMER_SIMILARITY_THRESHOLD = 0.6

TOP_N = 5
BOTTOM_N = 5
RECENT_HOOKS = 8
AGG_TOP_ROWS = 3  # how many winning rows to show per aggregate dimension
MIN_POSTS_FOR_LOSERS = 3  # below this we have no meaningful "what flopped" signal


def _fmt(value) -> str:
    return f"{value:.1f}" if isinstance(value, float) else str(value)


def _best_rows(perf: Dict[str, Dict[str, float]], k: int = AGG_TOP_ROWS) -> List[Tuple[str, float, int]]:
    ranked = sorted(perf.items(), key=lambda kv: kv[1]["avg_score"], reverse=True)
    return [(name, v["avg_score"], v["count"]) for name, v in ranked[:k]]


def get_performance_insights(window_days: int = None) -> Dict:
    """Single bounded data source for both the digest text and topic generation."""
    window_days = window_days if window_days is not None else storage.DEFAULT_WINDOW_DAYS
    measured = storage.count_measured_posts(window_days)
    return {
        "measured": measured,
        "window_days": window_days,
        "top_posts": storage.get_top_posts(TOP_N, window_days) if measured else [],
        "bottom_posts": storage.get_bottom_posts(BOTTOM_N, window_days) if measured else [],
        "aggregate": storage.get_aggregate_performance(window_days) if measured else {},
        "recent_hooks": [p.get("hook") for p in storage.get_recent_posts(RECENT_HOOKS) if p.get("hook")],
    }


def build_performance_digest(window_days: int = None) -> str:
    """Bounded, human-readable performance summary for the generation prompt.

    Returns '' when there is nothing useful to say, so callers can append blindly.
    """
    try:
        ins = get_performance_insights(window_days)
        lines: List[str] = []

        if ins["measured"]:
            lines.append(
                f"PERFORMANCE CONTEXT — real data from your last {ins['measured']} measured posts "
                f"(last {ins['window_days']} days, recent posts weighted more):"
            )

            if ins["top_posts"]:
                lines.append("What worked best (copy this kind of opening and angle):")
                for p in ins["top_posts"]:
                    lines.append(
                        f"  - [{_fmt(storage.engagement_score(p))}] ({p.get('topic')}) \"{p.get('hook')}\""
                    )

            # Only surface "losers" once we have enough posts for it to be meaningful,
            # and never repeat a post that's already listed as a winner.
            if ins["measured"] >= MIN_POSTS_FOR_LOSERS and ins["bottom_posts"]:
                top_hashes = {p.get("hash") for p in ins["top_posts"]}
                losers = [p for p in ins["bottom_posts"] if p.get("hash") not in top_hashes]
                if losers:
                    lines.append("What flopped (avoid these openings and angles):")
                    for p in losers:
                        lines.append(
                            f"  - [{_fmt(storage.engagement_score(p))}] ({p.get('topic')}) \"{p.get('hook')}\""
                        )

            agg = ins["aggregate"]
            topics = _best_rows(agg.get("by_topic", {}))
            if topics:
                lines.append("Best-performing topics on average: "
                             + ", ".join(f"{t} ({_fmt(s)})" for t, s, _ in topics))
            length = _best_rows(agg.get("by_length", {}), k=1)
            if length:
                lines.append(f"Best post length: {length[0][0]} (avg {_fmt(length[0][1])}).")
            htc = _best_rows(agg.get("by_hashtag_count", {}), k=1)
            if htc:
                lines.append(f"Best hashtag count: {htc[0][0]} (avg {_fmt(htc[0][1])}).")
            hour = _best_rows(agg.get("by_posting_hour", {}), k=1)
            if hour:
                lines.append(f"Best posting hour (UTC): {hour[0][0]} (avg {_fmt(hour[0][1])}).")

        if ins["recent_hooks"]:
            if not lines:
                lines.append("PERFORMANCE CONTEXT — from your recent posts:")
            hooks_list = "; ".join(f'"{h}"' for h in ins["recent_hooks"])
            lines.append(f"Do NOT reuse or paraphrase these recent openings: {hooks_list}")

        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Could not build performance digest: {e}")
        return ""


def build_topic_generation_context(window_days: int = None) -> str:
    """Compact, bounded context used to *generate the next topic* from what worked."""
    try:
        ins = get_performance_insights(window_days)
        if not ins["measured"]:
            return ""
        lines = ["Signals from your measured posts (recent-weighted):"]
        topics = _best_rows(ins["aggregate"].get("by_topic", {}))
        if topics:
            lines.append("Topics that got the most engagement: "
                         + ", ".join(f"{t} ({_fmt(s)}, n={c})" for t, s, c in topics))
        if ins["top_posts"]:
            lines.append("Winning angles (hooks):")
            for p in ins["top_posts"][:3]:
                lines.append(f"  - {p.get('hook')}")
        if ins["measured"] >= MIN_POSTS_FOR_LOSERS and ins["bottom_posts"]:
            top_hashes = {p.get("hash") for p in ins["top_posts"]}
            losers = [p for p in ins["bottom_posts"] if p.get("hash") not in top_hashes]
            if losers:
                lines.append("Weak angles to avoid:")
                for p in losers[:3]:
                    lines.append(f"  - {p.get('hook')}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Could not build topic-generation context: {e}")
        return ""


def get_low_performer_hooks(n: int = BOTTOM_N) -> List[str]:
    """Hooks of the lowest-engagement recent posts (SQL-bounded)."""
    try:
        if storage.count_measured_posts() < 4:
            return []
        return [p.get("hook") for p in storage.get_bottom_posts(n) if p.get("hook")]
    except Exception as e:
        logger.warning(f"Could not compute low-performer hooks: {e}")
        return []


def is_similar_to_low_performers(body: str,
                                 threshold: float = LOW_PERFORMER_SIMILARITY_THRESHOLD
                                 ) -> Tuple[bool, float]:
    """Does this draft open like the posts that historically performed worst?"""
    hooks = get_low_performer_hooks()
    if not hooks:
        return False, 0.0
    candidate_hook = storage.extract_hook(body)
    score, _ = _tfidf_max_similarity(candidate_hook, hooks)
    if score > threshold:
        logger.warning(
            f"Draft hook matches a low-performing pattern (similarity {score:.2f}): {candidate_hook!r}"
        )
        return True, score
    return False, score
