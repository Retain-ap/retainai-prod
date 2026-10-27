"""Sliding-window rate limits shared by every backend worker.

Counters live in a small SQLite file on the persistent data disk, so gunicorn
workers enforce one combined limit instead of one limit each. Keys are stored
only as SHA-256 digests, never as raw emails or IP addresses. If the file cannot
be used, limits fall back to per-process memory rather than failing requests.
"""

import hashlib
import os
import sqlite3
import threading
import time

from storage import DATA_ROOT


RATE_LIMIT_DB = os.getenv("RATE_LIMIT_DB") or os.path.join(DATA_ROOT, "rate_limits.sqlite3")
_LOCK = threading.Lock()
_MEMORY = {}
_SCHEMA_READY = False
_RETENTION_SECONDS = 24 * 60 * 60


def _digest(bucket, key):
    return hashlib.sha256(f"{bucket}\0{key}".encode("utf-8")).hexdigest()


def _connect():
    global _SCHEMA_READY
    os.makedirs(os.path.dirname(os.path.abspath(RATE_LIMIT_DB)), exist_ok=True)
    conn = sqlite3.connect(RATE_LIMIT_DB, timeout=5, isolation_level=None)
    if not _SCHEMA_READY:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS rate_events (k TEXT NOT NULL, at REAL NOT NULL)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS rate_events_k_at ON rate_events (k, at)")
        _SCHEMA_READY = True
    return conn


def _memory_hit(digests, window, record):
    now = time.time()
    with _LOCK:
        counts = {}
        for digest, _limit in digests:
            rows = [value for value in _MEMORY.get(digest, []) if now - value < window]
            _MEMORY[digest] = rows
            counts[digest] = len(rows)
        if any(counts[digest] >= limit for digest, limit in digests):
            return True
        if record:
            for digest, _limit in digests:
                _MEMORY[digest].append(now)
        return False


def hit(keys, window, record=True):
    """Return True when any ``(bucket, key, limit)`` is already at its limit.

    When none is limited and ``record`` is true, one event is recorded for every
    key in the same transaction, so concurrent workers cannot both slip past.
    """
    digests = [(_digest(bucket, key), limit) for bucket, key, limit in keys]
    now = time.time()
    try:
        conn = _connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            # Buckets use different windows, so prune only beyond the longest one.
            conn.execute("DELETE FROM rate_events WHERE at < ?", (now - _RETENTION_SECONDS,))
            for digest, limit in digests:
                (count,) = conn.execute(
                    "SELECT COUNT(*) FROM rate_events WHERE k = ? AND at >= ?",
                    (digest, now - window),
                ).fetchone()
                if count >= limit:
                    conn.execute("COMMIT")
                    return True
            if record:
                conn.executemany(
                    "INSERT INTO rate_events (k, at) VALUES (?, ?)",
                    [(digest, now) for digest, _limit in digests],
                )
            conn.execute("COMMIT")
            return False
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return _memory_hit(digests, window, record)


def record(bucket, key):
    """Record one event without checking a limit (e.g. a failed login)."""
    hit([(bucket, key, float("inf"))], window=_RETENTION_SECONDS)


def clear(bucket, key):
    digest = _digest(bucket, key)
    with _LOCK:
        _MEMORY.pop(digest, None)
    try:
        conn = _connect()
        try:
            conn.execute("DELETE FROM rate_events WHERE k = ?", (digest,))
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        pass


def reset():
    """Forget every counter. Intended for tests."""
    with _LOCK:
        _MEMORY.clear()
    try:
        conn = _connect()
        try:
            conn.execute("DELETE FROM rate_events")
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        pass
