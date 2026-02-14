"""Persistence for signal history and narrative tracking.

Uses PostgreSQL when DATABASE_URL is set, falls back to SQLite.
"""
import json
import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "radar.db")
DATABASE_URL = os.environ.get("DATABASE_URL", "")


def _use_pg() -> bool:
    return bool(DATABASE_URL)


# ── PostgreSQL backend ──

_pg_initialized = False


def _get_pg_conn():
    import psycopg2
    return psycopg2.connect(DATABASE_URL)


def _ensure_pg_tables():
    global _pg_initialized
    if _pg_initialized:
        return
    conn = _get_pg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id SERIAL PRIMARY KEY,
                    source TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    content TEXT,
                    topics JSONB DEFAULT '[]',
                    score REAL DEFAULT 0,
                    collected_at TEXT NOT NULL,
                    run_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS signal_narratives (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    confidence TEXT,
                    direction TEXT,
                    explanation TEXT,
                    signal_count INTEGER DEFAULT 0,
                    generated_at TEXT NOT NULL,
                    run_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    total_signals INTEGER DEFAULT 0,
                    total_narratives INTEGER DEFAULT 0,
                    signal_summary JSONB
                );
                CREATE INDEX IF NOT EXISTS idx_signals_source ON signals(source);
                CREATE INDEX IF NOT EXISTS idx_signals_collected ON signals(collected_at);
                CREATE INDEX IF NOT EXISTS idx_signals_run ON signals(run_id);
                CREATE INDEX IF NOT EXISTS idx_snarr_run ON signal_narratives(run_id);
            """)
        conn.commit()
        _migrate_sqlite_if_needed(conn)
        _pg_initialized = True
    finally:
        conn.close()


def _migrate_sqlite_if_needed(pg_conn):
    """Migrate SQLite data to PostgreSQL if SQLite DB exists and PG tables are empty."""
    if not os.path.exists(DB_PATH):
        return
    with pg_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM signals")
        if cur.fetchone()[0] > 0:
            return

    logger.info("Migrating signal store from SQLite to PostgreSQL...")
    import sqlite3
    sconn = sqlite3.connect(DB_PATH)
    sconn.row_factory = sqlite3.Row
    try:
        with pg_conn.cursor() as cur:
            # Migrate runs
            for r in sconn.execute("SELECT * FROM runs").fetchall():
                cur.execute(
                    "INSERT INTO runs (id, started_at, completed_at, total_signals, total_narratives, signal_summary) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (r["id"], r["started_at"], r["completed_at"], r["total_signals"], r["total_narratives"], r["signal_summary"]),
                )
            # Migrate signals
            for r in sconn.execute("SELECT * FROM signals").fetchall():
                cur.execute(
                    "INSERT INTO signals (source, signal_type, name, content, topics, score, collected_at, run_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (r["source"], r["signal_type"], r["name"], r["content"], r["topics"], r["score"], r["collected_at"], r["run_id"]),
                )
            # Migrate narratives
            for r in sconn.execute("SELECT * FROM narratives").fetchall():
                cur.execute(
                    "INSERT INTO signal_narratives (name, confidence, direction, explanation, signal_count, generated_at, run_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (r["name"], r["confidence"], r["direction"], r["explanation"], r["signal_count"], r["generated_at"], r["run_id"]),
                )
        pg_conn.commit()
        logger.info("SQLite signal store migrated to PostgreSQL")
        # Rename sqlite db
        try:
            os.rename(DB_PATH, DB_PATH + ".bak")
        except OSError:
            pass
    finally:
        sconn.close()


# ── SQLite backend (fallback) ──

def _get_sqlite_db():
    import sqlite3
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            name TEXT NOT NULL,
            content TEXT,
            topics TEXT,
            score REAL DEFAULT 0,
            collected_at TEXT NOT NULL,
            run_id TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS narratives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            confidence TEXT,
            direction TEXT,
            explanation TEXT,
            signal_count INTEGER DEFAULT 0,
            generated_at TEXT NOT NULL,
            run_id TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            total_signals INTEGER DEFAULT 0,
            total_narratives INTEGER DEFAULT 0,
            signal_summary TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_signals_source ON signals(source);
        CREATE INDEX IF NOT EXISTS idx_signals_collected ON signals(collected_at);
        CREATE INDEX IF NOT EXISTS idx_signals_run ON signals(run_id);
        CREATE INDEX IF NOT EXISTS idx_narratives_run ON narratives(run_id);
    """)
    return conn


def get_db():
    """Get database connection (PG or SQLite), creating tables if needed."""
    if _use_pg():
        _ensure_pg_tables()
        return _PgConnWrapper()
    return _get_sqlite_db()


class _PgConnWrapper:
    """Wraps psycopg2 connection to provide sqlite3-like Row interface for routes.py compatibility."""

    def __init__(self):
        self._conn = _get_pg_conn()

    def execute(self, sql, params=None):
        # Convert SQLite-style ? placeholders to %s
        sql = sql.replace("?", "%s")
        cur = self._conn.cursor()
        cur.execute(sql, params or ())
        return _PgCursorWrapper(cur)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


class _PgCursorWrapper:
    """Wraps psycopg2 cursor to return DictRow objects from fetchall/fetchone."""
    def __init__(self, cur):
        self._cur = cur

    def fetchall(self):
        if not self._cur.description:
            return []
        columns = [d[0] for d in self._cur.description]
        return [_DictRow(dict(zip(columns, r))) for r in self._cur.fetchall()]

    def fetchone(self):
        if not self._cur.description:
            return None
        columns = [d[0] for d in self._cur.description]
        row = self._cur.fetchone()
        return _DictRow(dict(zip(columns, row))) if row else None


class _DictRow:
    """Mimics sqlite3.Row for dict-style access."""
    def __init__(self, data):
        self._data = data

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self._data.values())[key]
        return self._data[key]

    def keys(self):
        return self._data.keys()


def save_run(run_id: str, signals: List[Dict], narratives: List[Dict], summary: Dict):
    """Save a complete pipeline run."""
    if _use_pg():
        _ensure_pg_tables()
        conn = _get_pg_conn()
        try:
            now = datetime.utcnow().isoformat()
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO runs (id, started_at, completed_at, total_signals, total_narratives, signal_summary) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO UPDATE SET completed_at=EXCLUDED.completed_at, total_signals=EXCLUDED.total_signals, total_narratives=EXCLUDED.total_narratives, signal_summary=EXCLUDED.signal_summary",
                    (run_id, now, now, len(signals), len(narratives), json.dumps(summary)),
                )
                for s in signals:
                    cur.execute(
                        "INSERT INTO signals (source, signal_type, name, content, topics, score, collected_at, run_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (s.get("source", "unknown"), s.get("signal_type", "unknown"), s.get("name", "")[:500],
                         s.get("content", "")[:2000], json.dumps(s.get("topics", [])), s.get("score", 0),
                         s.get("collected_at", now), run_id),
                    )
                for n in narratives:
                    cur.execute(
                        "INSERT INTO signal_narratives (name, confidence, direction, explanation, signal_count, generated_at, run_id) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (n.get("name", ""), n.get("confidence", ""), n.get("direction", ""),
                         n.get("explanation", ""), len(n.get("supporting_signals", [])), now, run_id),
                    )
            conn.commit()
        finally:
            conn.close()
        return

    # SQLite fallback
    conn = _get_sqlite_db()
    try:
        now = datetime.utcnow().isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO runs (id, started_at, completed_at, total_signals, total_narratives, signal_summary) VALUES (?,?,?,?,?,?)",
            (run_id, now, now, len(signals), len(narratives), json.dumps(summary)),
        )
        for s in signals:
            conn.execute(
                "INSERT INTO signals (source, signal_type, name, content, topics, score, collected_at, run_id) VALUES (?,?,?,?,?,?,?,?)",
                (s.get("source", "unknown"), s.get("signal_type", "unknown"), s.get("name", "")[:500],
                 s.get("content", "")[:2000], json.dumps(s.get("topics", [])), s.get("score", 0),
                 s.get("collected_at", now), run_id),
            )
        for n in narratives:
            conn.execute(
                "INSERT INTO narratives (name, confidence, direction, explanation, signal_count, generated_at, run_id) VALUES (?,?,?,?,?,?,?)",
                (n.get("name", ""), n.get("confidence", ""), n.get("direction", ""),
                 n.get("explanation", ""), len(n.get("supporting_signals", [])), now, run_id),
            )
        conn.commit()
    finally:
        conn.close()


def get_signal_velocity(topic: str, days: int = 7) -> Dict:
    if _use_pg():
        _ensure_pg_tables()
        conn = _get_pg_conn()
        try:
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT collected_at::date as day, COUNT(*) as count
                    FROM signals
                    WHERE topics::text LIKE %s AND collected_at > %s
                    GROUP BY collected_at::date
                    ORDER BY day
                """, (f'%"{topic}"%', cutoff))
                rows = cur.fetchall()
            if len(rows) < 2:
                return {"velocity": 0, "trend": "insufficient_data", "data_points": len(rows)}
            counts = [r[1] for r in rows]
            first_half = sum(counts[:len(counts)//2])
            second_half = sum(counts[len(counts)//2:])
            velocity = ((second_half - first_half) / first_half * 100) if first_half else (100 if second_half > 0 else 0)
            trend = "accelerating" if velocity > 20 else "decelerating" if velocity < -20 else "stable"
            return {"velocity": round(velocity, 1), "trend": trend, "data_points": len(rows),
                    "daily_counts": {str(r[0]): r[1] for r in rows}}
        finally:
            conn.close()

    # SQLite fallback
    conn = _get_sqlite_db()
    try:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        rows = conn.execute("""
            SELECT date(collected_at) as day, COUNT(*) as count
            FROM signals WHERE topics LIKE ? AND collected_at > ?
            GROUP BY date(collected_at) ORDER BY day
        """, (f'%"{topic}"%', cutoff)).fetchall()
        if len(rows) < 2:
            return {"velocity": 0, "trend": "insufficient_data", "data_points": len(rows)}
        counts = [r["count"] for r in rows]
        first_half = sum(counts[:len(counts)//2])
        second_half = sum(counts[len(counts)//2:])
        velocity = ((second_half - first_half) / first_half * 100) if first_half else (100 if second_half > 0 else 0)
        trend = "accelerating" if velocity > 20 else "decelerating" if velocity < -20 else "stable"
        return {"velocity": round(velocity, 1), "trend": trend, "data_points": len(rows),
                "daily_counts": {str(r["day"]): r["count"] for r in rows}}
    finally:
        conn.close()


def get_narrative_history(name: str, limit: int = 10) -> List[Dict]:
    if _use_pg():
        _ensure_pg_tables()
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT confidence, direction, signal_count, generated_at
                    FROM signal_narratives WHERE name = %s ORDER BY generated_at DESC LIMIT %s
                """, (name, limit))
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            conn.close()

    conn = _get_sqlite_db()
    try:
        rows = conn.execute("""
            SELECT confidence, direction, signal_count, generated_at
            FROM narratives WHERE name = ? ORDER BY generated_at DESC LIMIT ?
        """, (name, limit)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_stats() -> Dict:
    if _use_pg():
        _ensure_pg_tables()
        conn = _get_pg_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM signals")
                total_signals = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM runs")
                total_runs = cur.fetchone()[0]
                cur.execute("SELECT COUNT(DISTINCT name) FROM signal_narratives")
                total_narratives = cur.fetchone()[0]
                cur.execute("SELECT MIN(started_at) FROM runs")
                first_run = cur.fetchone()[0]
                cur.execute("SELECT MAX(completed_at) FROM runs")
                last_run = cur.fetchone()[0]
            return {
                "total_signals_collected": total_signals,
                "total_runs": total_runs,
                "unique_narratives": total_narratives,
                "tracking_since": first_run,
                "last_run": last_run,
            }
        finally:
            conn.close()

    conn = _get_sqlite_db()
    try:
        total_signals = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        total_runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        total_narratives = conn.execute("SELECT COUNT(DISTINCT name) FROM narratives").fetchone()[0]
        first_run = conn.execute("SELECT MIN(started_at) FROM runs").fetchone()[0]
        last_run = conn.execute("SELECT MAX(completed_at) FROM runs").fetchone()[0]
        return {
            "total_signals_collected": total_signals,
            "total_runs": total_runs,
            "unique_narratives": total_narratives,
            "tracking_since": first_run,
            "last_run": last_run,
        }
    finally:
        conn.close()
