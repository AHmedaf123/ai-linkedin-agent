import sqlite3
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

DB_PATH = os.getenv("AGENT_DB_PATH", "agent/agent_storage.db")

_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS posts (id INTEGER PRIMARY KEY, hash TEXT UNIQUE, title TEXT, body TEXT, seo_score INTEGER, seo_keywords TEXT, hashtags TEXT, timestamp TEXT)",
    "CREATE TABLE IF NOT EXISTS repo_queue (id INTEGER PRIMARY KEY, repo TEXT UNIQUE, added_at TEXT)",
    "CREATE TABLE IF NOT EXISTS used_repos (id INTEGER PRIMARY KEY, repo TEXT UNIQUE, used_at TEXT)",
    "CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT)",
    "CREATE TABLE IF NOT EXISTS post_history (id INTEGER PRIMARY KEY, title TEXT, length INTEGER, timestamp TEXT)",
    "CREATE TABLE IF NOT EXISTS locks (name TEXT PRIMARY KEY, owner TEXT, acquired_at TEXT)",
]


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db() -> None:
    conn = _connect()
    try:
        for s in _SCHEMA:
            conn.execute(s)
    finally:
        conn.close()


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


def enqueue_repo(repo: str) -> None:
    conn = _connect()
    try:
        now = datetime.utcnow().isoformat()
        try:
            conn.execute("INSERT OR IGNORE INTO repo_queue(repo, added_at) VALUES (?, ?)", (repo, now))
        finally:
            pass
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
        # remove it atomically
        conn.execute("DELETE FROM repo_queue WHERE repo = ?", (repo,))
        # mark used
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


def get_recent_posts(limit: int = 30) -> List[Dict[str, Any]]:
    conn = _connect()
    try:
        cur = conn.execute("SELECT title, body, seo_score, seo_keywords, hashtags, timestamp, hash FROM posts ORDER BY timestamp DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
        out = []
        for r in rows:
            try:
                kws = json.loads(r[3]) if r[3] else []
            except Exception:
                kws = []
            try:
                tags = json.loads(r[4]) if r[4] else []
            except Exception:
                tags = []
            out.append({"title": r[0], "body": r[1], "seo_score": r[2], "seo_keywords": kws, "hashtags": tags, "timestamp": r[5], "hash": r[6]})
        return out
    finally:
        conn.close()


def save_used_post(post: Dict[str, Any]) -> bool:
    conn = _connect()
    try:
        h = post.get("hash")
        if not h:
            import hashlib
            h = hashlib.md5(post.get("body", "").encode()).hexdigest()
        now = datetime.utcnow().isoformat()
        kws = json.dumps(post.get("seo_keywords", []))
        tags = json.dumps(post.get("hashtags", []))
        try:
            conn.execute("INSERT INTO posts(hash, title, body, seo_score, seo_keywords, hashtags, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (h, post.get("title"), post.get("body"), post.get("seo_score"), kws, tags, now))
            return True
        except sqlite3.IntegrityError:
            # already exists
            return False
    finally:
        conn.close()


def is_hash_used(h: str) -> bool:
    conn = _connect()
    try:
        cur = conn.execute("SELECT 1 FROM posts WHERE hash = ?", (h,))
        return cur.fetchone() is not None
    finally:
        conn.close()


def append_post_history(title: str, length: int) -> None:
    conn = _connect()
    try:
        now = datetime.utcnow().isoformat()
        conn.execute("INSERT INTO post_history(title, length, timestamp) VALUES (?, ?, ?)", (title, length, now))
    finally:
        conn.close()
