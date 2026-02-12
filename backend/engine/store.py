"""SQLite persistence for signal history and narrative tracking"""
import sqlite3
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "radar.db")


def get_db():
    """Get database connection, creating tables if needed"""
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
            topics TEXT,  -- JSON array
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
            signal_summary TEXT  -- JSON
        );
        
        CREATE INDEX IF NOT EXISTS idx_signals_source ON signals(source);
        CREATE INDEX IF NOT EXISTS idx_signals_collected ON signals(collected_at);
        CREATE INDEX IF NOT EXISTS idx_signals_run ON signals(run_id);
        CREATE INDEX IF NOT EXISTS idx_narratives_run ON narratives(run_id);
    """)
    
    return conn


def save_run(run_id: str, signals: List[Dict], narratives: List[Dict], summary: Dict):
    """Save a complete pipeline run to the database"""
    conn = get_db()
    try:
        now = datetime.utcnow().isoformat()
        
        # Save run metadata
        conn.execute(
            "INSERT OR REPLACE INTO runs (id, started_at, completed_at, total_signals, total_narratives, signal_summary) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, now, now, len(signals), len(narratives), json.dumps(summary))
        )
        
        # Save signals
        for s in signals:
            conn.execute(
                "INSERT INTO signals (source, signal_type, name, content, topics, score, collected_at, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    s.get("source", "unknown"),
                    s.get("signal_type", "unknown"),
                    s.get("name", "")[:500],
                    s.get("content", "")[:2000],
                    json.dumps(s.get("topics", [])),
                    s.get("score", 0),
                    s.get("collected_at", now),
                    run_id
                )
            )
        
        # Save narratives
        for n in narratives:
            conn.execute(
                "INSERT INTO narratives (name, confidence, direction, explanation, signal_count, generated_at, run_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    n.get("name", ""),
                    n.get("confidence", ""),
                    n.get("direction", ""),
                    n.get("explanation", ""),
                    len(n.get("supporting_signals", [])),
                    now,
                    run_id
                )
            )
        
        conn.commit()
    finally:
        conn.close()


def get_signal_velocity(topic: str, days: int = 7) -> Dict:
    """Calculate signal velocity for a topic over time"""
    conn = get_db()
    try:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        
        # Get signal counts per day for this topic
        rows = conn.execute("""
            SELECT date(collected_at) as day, COUNT(*) as count
            FROM signals
            WHERE topics LIKE ? AND collected_at > ?
            GROUP BY date(collected_at)
            ORDER BY day
        """, (f'%"{topic}"%', cutoff)).fetchall()
        
        if len(rows) < 2:
            return {"velocity": 0, "trend": "insufficient_data", "data_points": len(rows)}
        
        # Calculate trend
        counts = [r["count"] for r in rows]
        first_half = sum(counts[:len(counts)//2])
        second_half = sum(counts[len(counts)//2:])
        
        if first_half == 0:
            velocity = 100 if second_half > 0 else 0
        else:
            velocity = ((second_half - first_half) / first_half) * 100
        
        trend = "accelerating" if velocity > 20 else "decelerating" if velocity < -20 else "stable"
        
        return {
            "velocity": round(velocity, 1),
            "trend": trend,
            "data_points": len(rows),
            "daily_counts": {str(r["day"]): r["count"] for r in rows}
        }
    finally:
        conn.close()


def get_narrative_history(name: str, limit: int = 10) -> List[Dict]:
    """Get historical confidence/direction for a narrative"""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT confidence, direction, signal_count, generated_at
            FROM narratives
            WHERE name = ?
            ORDER BY generated_at DESC
            LIMIT ?
        """, (name, limit)).fetchall()
        
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_stats() -> Dict:
    """Get overall database stats"""
    conn = get_db()
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
            "last_run": last_run
        }
    finally:
        conn.close()
