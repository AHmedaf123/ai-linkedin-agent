"""SQLite persistence layer — the single source of truth for posts, engagement,
scheduling state, and growth-agent rate limits.

Everything the agent needs to remember between runs lives in one file
(agent/agent_storage.db) so CI can persist it with a single commit/cache entry.
"""

import sqlite3
import json
import os
import math
import hashlib
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional

DB_PATH = os.getenv("AGENT_DB_PATH", "agent/agent_storage.db")

# Weighted engagement score, expressed in SQL so aggregation happens in the
# database (fixed-size output no matter how many rows exist).
_SCORE_SQL = ("(COALESCE(likes,0)*1.0 + COALESCE(comments,0)*3.0 "
              "+ COALESCE(shares,0)*5.0 + COALESCE(impressions,0)*0.01)")

DEFAULT_HALF_LIFE_DAYS = float(os.getenv("PERF_HALF_LIFE_DAYS", "45"))
DEFAULT_WINDOW_DAYS = int(os.getenv("PERF_WINDOW_DAYS", "90"))

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY,
        hash TEXT UNIQUE,
        title TEXT,
        body TEXT,
        hook TEXT,
        topic TEXT,
        source TEXT,
        template_id TEXT,
        seo_score INTEGER,
        seo_keywords TEXT,
        hashtags TEXT,
        posted_at TEXT,
        likes INTEGER DEFAULT NULL,
        comments INTEGER DEFAULT NULL,
        shares INTEGER DEFAULT NULL,
        impressions INTEGER DEFAULT NULL,
        engagement_updated_at TEXT,
        char_count INTEGER,
        hashtag_count INTEGER
    )""",
    "CREATE TABLE IF NOT EXISTS repo_queue (id INTEGER PRIMARY KEY, repo TEXT UNIQUE, added_at TEXT)",
    "CREATE TABLE IF NOT EXISTS used_repos (id INTEGER PRIMARY KEY, repo TEXT UNIQUE, used_at TEXT)",
    "CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT)",
    "CREATE TABLE IF NOT EXISTS locks (name TEXT PRIMARY KEY, owner TEXT, acquired_at TEXT)",
    "CREATE TABLE IF NOT EXISTS daily_counters (day TEXT, name TEXT, count INTEGER, PRIMARY KEY (day, name))",
]

# Columns added over time; applied to pre-existing DBs that lack them.
_POST_COLUMNS = {
    "hook": "TEXT",
    "topic": "TEXT",
    "source": "TEXT",
    "template_id": "TEXT",
    "posted_at": "TEXT",
    "likes": "INTEGER",
    "comments": "INTEGER",
    "shares": "INTEGER",
    "impressions": "INTEGER",
    "engagement_updated_at": "TEXT",
    "char_count": "INTEGER",
    "hashtag_count": "INTEGER",
}


def _decay_weight(posted_at: Optional[str], half_life_days: float) -> float:
    """Exponential time-decay: a post loses half its weight every half_life_days.

    Registered as a SQL function so weighted aggregation runs inside SQLite.
    """
    if not posted_at:
        return 1.0
    try:
        t = datetime.fromisoformat(posted_at)
    except Exception:
        return 1.0
    age_days = (datetime.utcnow() - t).total_seconds() / 86400.0
    if age_days < 0:
        age_days = 0.0
    return math.exp(-age_days / max(1.0, float(half_life_days)))


def _connect():
    parent = os.path.dirname(DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    # DELETE journal keeps the DB in a single file, which CI commits to git.
    conn.execute("PRAGMA journal_mode=DELETE;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    # SQL-side time decay for scalable weighted aggregation.
    conn.create_function("decay_weight", 2, _decay_weight)
    return conn


def _window_cutoff(window_days: Optional[int]) -> str:
    """ISO cutoff for a rolling window; empty string means 'all time'."""
    if not window_days:
        return ""
    return (datetime.utcnow() - timedelta(days=window_days)).isoformat()


def _migrate(conn) -> None:
    cur = conn.execute("PRAGMA table_info(posts)")
    existing = {row[1] for row in cur.fetchall()}
    for col, coltype in _POST_COLUMNS.items():
        if existing and col not in existing:
            conn.execute(f"ALTER TABLE posts ADD COLUMN {col} {coltype}")


def init_db() -> None:
    conn = _connect()
    try:
        for s in _SCHEMA:
            conn.execute(s)
        _migrate(conn)
    finally:
        conn.close()


def post_hash(body: str) -> str:
    return hashlib.md5((body or "").encode()).hexdigest()


def extract_hook(body: str) -> str:
    """First sentence (or line) of a post — the part LinkedIn shows above the fold."""
    text = (body or "").strip()
    if not text:
        return ""
    first_line = text.splitlines()[0].strip()
    for sep in (". ", "! ", "? "):
        idx = first_line.find(sep)
        if idx > 0:
            return first_line[: idx + 1].strip()
    return first_line[:200]


# --- Locks / state -----------------------------------------------------------

def acquire_lock(name: str, owner: str) -> bool:
    conn = _connect()
    try:
        now = datetime.utcnow().isoformat()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO locks(name, owner, acquired_at) VALUES (?, ?, ?)", (name, owner, now))
            conn.execute("COMMIT")
            return True
        except sqlite3.IntegrityError:
            conn.execute("ROLLBACK")
            return False
    finally:
        conn.close()


def release_lock(name: str, owner: str) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM locks WHERE name = ? AND owner = ?", (name, owner))
    finally:
        conn.close()


def get_state(key: str) -> Optional[str]:
    conn = _connect()
    try:
        cur = conn.execute("SELECT value FROM state WHERE key = ?", (key,))
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def set_state(key: str, value: str) -> None:
    conn = _connect()
    try:
        conn.execute("INSERT OR REPLACE INTO state(key, value) VALUES (?, ?)", (key, value))
    finally:
        conn.close()


# --- Repo queue --------------------------------------------------------------

def enqueue_repo(repo: str) -> None:
    conn = _connect()
    try:
        now = datetime.utcnow().isoformat()
        conn.execute("INSERT OR IGNORE INTO repo_queue(repo, added_at) VALUES (?, ?)", (repo, now))
    finally:
        conn.close()


def get_next_repo(skip_current: bool = False) -> Optional[str]:
    conn = _connect()
    try:
        cur = conn.execute("SELECT repo FROM repo_queue ORDER BY id LIMIT 1")
        row = cur.fetchone()
        if not row:
            return None
        repo = row[0]
        conn.execute("DELETE FROM repo_queue WHERE repo = ?", (repo,))
        now = datetime.utcnow().isoformat()
        conn.execute("INSERT OR IGNORE INTO used_repos(repo, used_at) VALUES (?, ?)", (repo, now))
        return repo
    finally:
        conn.close()


def mark_repo_used(repo: str) -> None:
    conn = _connect()
    try:
        now = datetime.utcnow().isoformat()
        conn.execute("INSERT OR IGNORE INTO used_repos(repo, used_at) VALUES (?, ?)", (repo, now))
    finally:
        conn.close()


def is_repo_used(repo: str) -> bool:
    conn = _connect()
    try:
        cur = conn.execute("SELECT 1 FROM used_repos WHERE repo = ?", (repo,))
        return cur.fetchone() is not None
    finally:
        conn.close()


# --- Posts -------------------------------------------------------------------

def _row_to_post(row) -> Dict[str, Any]:
    (title, body, hook, topic, source, template_id, seo_score, kws, tags,
     posted_at, likes, comments, shares, impressions, h) = row
    try:
        keywords = json.loads(kws) if kws else []
    except Exception:
        keywords = []
    try:
        hashtags = json.loads(tags) if tags else []
    except Exception:
        hashtags = []
    return {
        "title": title,
        "body": body,
        "hook": hook,
        "topic": topic,
        "source": source,
        "template_id": template_id,
        "seo_score": seo_score,
        "seo_keywords": keywords,
        "hashtags": hashtags,
        "posted_at": posted_at,
        "timestamp": posted_at,  # backward-compatible alias
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "impressions": impressions,
        "hash": h,
    }


_POST_SELECT = ("SELECT title, body, hook, topic, source, template_id, seo_score, "
                "seo_keywords, hashtags, posted_at, likes, comments, shares, impressions, hash FROM posts")


def get_recent_posts(limit: int = 30) -> List[Dict[str, Any]]:
    init_db()
    conn = _connect()
    try:
        cur = conn.execute(f"{_POST_SELECT} ORDER BY id DESC LIMIT ?", (limit,))
        return [_row_to_post(r) for r in cur.fetchall()]
    finally:
        conn.close()


def save_used_post(post: Dict[str, Any]) -> bool:
    """Record a published post. Returns False if the same body hash already exists."""
    init_db()
    conn = _connect()
    try:
        body = post.get("body", "")
        h = post.get("hash") or post_hash(body)
        now = datetime.utcnow().isoformat()
        hashtags = post.get("hashtags", [])
        kws = json.dumps(post.get("seo_keywords", []))
        tags = json.dumps(hashtags)
        hook = post.get("hook") or extract_hook(body)
        try:
            conn.execute(
                """INSERT INTO posts(hash, title, body, hook, topic, source, template_id,
                                     seo_score, seo_keywords, hashtags, posted_at,
                                     char_count, hashtag_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (h, post.get("title"), body, hook, post.get("topic"), post.get("source"),
                 str(post.get("template_id") or ""), post.get("seo_score"), kws, tags, now,
                 len(body), len(hashtags)),
            )
            return True
        except sqlite3.IntegrityError:
            return False
    finally:
        conn.close()


def is_hash_used(h: str) -> bool:
    init_db()
    conn = _connect()
    try:
        cur = conn.execute("SELECT 1 FROM posts WHERE hash = ?", (h,))
        return cur.fetchone() is not None
    finally:
        conn.close()


def update_post_engagement(h: str, likes: int = 0, comments: int = 0,
                           shares: int = 0, impressions: int = 0) -> bool:
    init_db()
    conn = _connect()
    try:
        now = datetime.utcnow().isoformat()
        cur = conn.execute(
            """UPDATE posts SET likes = ?, comments = ?, shares = ?, impressions = ?,
                                engagement_updated_at = ? WHERE hash = ?""",
            (likes, comments, shares, impressions, now, h),
        )
        return cur.rowcount > 0
    finally:
        conn.close()


def _normalize_for_match(text: str) -> str:
    return " ".join((text or "").split()).lower()


def match_post_by_content(scraped_text: str, prefix_len: int = 120) -> Optional[str]:
    """Match scraped post text back to a stored post; returns its hash or None.

    LinkedIn truncates/re-wraps text, so match on a normalized prefix in both
    directions (stored startswith scraped, or scraped startswith stored).
    """
    needle = _normalize_for_match(scraped_text)[:prefix_len]
    if len(needle) < 20:
        return None
    init_db()
    conn = _connect()
    try:
        cur = conn.execute("SELECT hash, body FROM posts ORDER BY id DESC LIMIT 100")
        for h, body in cur.fetchall():
            stored = _normalize_for_match(body)
            if stored[:prefix_len].startswith(needle[:60]) or needle.startswith(stored[:60]):
                return h
        return None
    finally:
        conn.close()


def get_posts_with_engagement(limit: int = 50) -> List[Dict[str, Any]]:
    """Posts that have at least one engagement measurement, newest first."""
    init_db()
    conn = _connect()
    try:
        cur = conn.execute(
            f"{_POST_SELECT} WHERE engagement_updated_at IS NOT NULL ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [_row_to_post(r) for r in cur.fetchall()]
    finally:
        conn.close()


def engagement_score(post: Dict[str, Any]) -> float:
    """Weighted engagement: comments and shares matter more than likes;
    impressions contribute weakly so reach breaks ties."""
    return (
        (post.get("likes") or 0) * 1.0
        + (post.get("comments") or 0) * 3.0
        + (post.get("shares") or 0) * 5.0
        + (post.get("impressions") or 0) * 0.01
    )


def _grouped_weighted_avg(group_expr: str, *, window_days: Optional[int] = DEFAULT_WINDOW_DAYS,
                          half_life: float = DEFAULT_HALF_LIFE_DAYS, min_posts: int = 1,
                          extra_where: str = "") -> Dict[str, Dict[str, float]]:
    """Time-decayed weighted-average engagement per group, computed in SQL.

    Output size == number of distinct groups (e.g. ~18 topics, 3 length buckets),
    NOT the number of rows — so this stays O(1)-ish whether the table has 10 or
    100,000 posts. Only measured posts (engagement_updated_at set) are counted.
    """
    init_db()
    conn = _connect()
    try:
        cutoff = _window_cutoff(window_days)
        where = ["engagement_updated_at IS NOT NULL", f"({group_expr}) IS NOT NULL"]
        params: List[Any] = []
        if cutoff:
            where.append("posted_at >= ?")
            params.append(cutoff)
        if extra_where:
            where.append(extra_where)
        sql = (
            f"SELECT ({group_expr}) AS grp, "
            f"       SUM({_SCORE_SQL} * decay_weight(posted_at, ?)) AS wsum, "
            f"       SUM(decay_weight(posted_at, ?)) AS wtot, "
            f"       COUNT(*) AS cnt "
            f"FROM posts WHERE {' AND '.join(where)} GROUP BY grp"
        )
        rows = conn.execute(sql, [half_life, half_life, *params]).fetchall()
        out: Dict[str, Dict[str, float]] = {}
        for grp, wsum, wtot, cnt in rows:
            if cnt < min_posts or not wtot:
                continue
            out[str(grp)] = {"avg_score": (wsum or 0.0) / wtot, "count": int(cnt)}
        return out
    finally:
        conn.close()


def get_topic_performance(min_posts: int = 1, window_days: Optional[int] = DEFAULT_WINDOW_DAYS) -> Dict[str, Dict[str, float]]:
    """Time-decayed weighted avg engagement per topic (SQL GROUP BY, fixed output)."""
    return _grouped_weighted_avg("topic", window_days=window_days, min_posts=min_posts)


def get_template_performance(window_days: Optional[int] = DEFAULT_WINDOW_DAYS) -> Dict[str, Dict[str, float]]:
    """Time-decayed weighted avg engagement per template_id (SQL GROUP BY)."""
    return _grouped_weighted_avg("COALESCE(NULLIF(template_id, ''), 'default')", window_days=window_days)


_LENGTH_BUCKET_SQL = ("CASE WHEN char_count IS NULL THEN 'unknown' "
                      "WHEN char_count < 400 THEN 'short(<400)' "
                      "WHEN char_count < 800 THEN 'medium(400-800)' "
                      "ELSE 'long(>800)' END")


def get_aggregate_performance(window_days: Optional[int] = DEFAULT_WINDOW_DAYS,
                              half_life: float = DEFAULT_HALF_LIFE_DAYS) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Compressed performance across several dimensions — all bounded output.

    Returns weighted-avg engagement grouped by topic, length bucket, hashtag
    count, and posting hour. This is the 'everything else' summary that replaces
    dumping raw posts into the LLM: no matter how big the table grows, this
    returns a handful of summary rows per dimension.
    """
    return {
        "by_topic": _grouped_weighted_avg("topic", window_days=window_days, half_life=half_life),
        "by_length": _grouped_weighted_avg(_LENGTH_BUCKET_SQL, window_days=window_days, half_life=half_life),
        "by_hashtag_count": _grouped_weighted_avg("hashtag_count", window_days=window_days, half_life=half_life),
        "by_posting_hour": _grouped_weighted_avg("strftime('%H', posted_at)", window_days=window_days, half_life=half_life),
    }


def _ranked_posts(order: str, n: int, window_days: Optional[int]) -> List[Dict[str, Any]]:
    init_db()
    conn = _connect()
    try:
        cutoff = _window_cutoff(window_days)
        where = ["engagement_updated_at IS NOT NULL"]
        params: List[Any] = []
        if cutoff:
            where.append("posted_at >= ?")
            params.append(cutoff)
        sql = (f"{_POST_SELECT} WHERE {' AND '.join(where)} "
               f"ORDER BY {_SCORE_SQL} {order} LIMIT ?")
        rows = conn.execute(sql, [*params, n]).fetchall()
        return [_row_to_post(r) for r in rows]
    finally:
        conn.close()


def get_top_posts(n: int = 5, window_days: Optional[int] = DEFAULT_WINDOW_DAYS) -> List[Dict[str, Any]]:
    """Top-N posts by weighted engagement (bounded output for the digest)."""
    return _ranked_posts("DESC", n, window_days)


def get_bottom_posts(n: int = 5, window_days: Optional[int] = DEFAULT_WINDOW_DAYS) -> List[Dict[str, Any]]:
    """Bottom-N measured posts by engagement (bounded output for the digest)."""
    return _ranked_posts("ASC", n, window_days)


def count_measured_posts(window_days: Optional[int] = DEFAULT_WINDOW_DAYS) -> int:
    init_db()
    conn = _connect()
    try:
        cutoff = _window_cutoff(window_days)
        if cutoff:
            cur = conn.execute(
                "SELECT COUNT(*) FROM posts WHERE engagement_updated_at IS NOT NULL AND posted_at >= ?",
                (cutoff,))
        else:
            cur = conn.execute("SELECT COUNT(*) FROM posts WHERE engagement_updated_at IS NOT NULL")
        return int(cur.fetchone()[0])
    finally:
        conn.close()


# --- Daily counters (growth-agent rate limits) --------------------------------

def get_daily_counter(name: str) -> int:
    init_db()
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT count FROM daily_counters WHERE day = ? AND name = ?",
            (date.today().isoformat(), name),
        )
        row = cur.fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def increment_daily_counter(name: str, by: int = 1) -> int:
    init_db()
    conn = _connect()
    try:
        today = date.today().isoformat()
        conn.execute(
            """INSERT INTO daily_counters(day, name, count) VALUES (?, ?, ?)
               ON CONFLICT(day, name) DO UPDATE SET count = count + ?""",
            (today, name, by, by),
        )
        cur = conn.execute("SELECT count FROM daily_counters WHERE day = ? AND name = ?", (today, name))
        return cur.fetchone()[0]
    finally:
        conn.close()


# --- Backward compatibility ----------------------------------------------------

def append_post_history(title: str, length: int) -> None:
    """Legacy shim: post history now lives in the posts table."""
    return None
