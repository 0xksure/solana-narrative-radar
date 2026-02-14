"""Persistent narrative store with fuzzy matching and signal accumulation.

Uses PostgreSQL when DATABASE_URL is set, falls back to JSON file storage.
"""
import hashlib
import json
import os
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

STORE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "narratives_db.json")

DATABASE_URL = os.environ.get("DATABASE_URL", "")

_STOP_WORDS = frozenset({
    "the", "and", "for", "with", "on", "in", "of", "a", "an", "to", "is",
    "solana", "sol", "protocol", "ecosystem", "network", "based", "powered",
})

# ── Helpers (unchanged) ──

def _canonical(name: str) -> str:
    words = re.split(r"[^a-z0-9]+", name.lower())
    return " ".join(w for w in words if w and w not in _STOP_WORDS)


def _stable_id(canonical_name: str) -> str:
    return hashlib.sha256(canonical_name.encode()).hexdigest()[:16]


def _word_set(canonical: str) -> set:
    return set(canonical.split())


def _word_overlap(a: str, b: str) -> float:
    wa, wb = _word_set(a), _word_set(b)
    if not wa or not wb:
        return 0.0
    overlap = len(wa & wb)
    return overlap / min(len(wa), len(wb))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── PostgreSQL helpers ──

def _use_pg() -> bool:
    return bool(DATABASE_URL)


def _get_conn():
    import psycopg2
    return psycopg2.connect(DATABASE_URL)


_pg_initialized = False


def _ensure_tables():
    global _pg_initialized
    if _pg_initialized:
        return
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS narrative_store (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    canonical_name TEXT,
                    status TEXT DEFAULT 'ACTIVE',
                    first_detected TIMESTAMPTZ,
                    last_detected TIMESTAMPTZ,
                    last_updated TIMESTAMPTZ,
                    faded_at TIMESTAMPTZ,
                    detection_count INTEGER DEFAULT 0,
                    missed_count INTEGER DEFAULT 0,
                    current_confidence TEXT DEFAULT 'MEDIUM',
                    current_direction TEXT DEFAULT 'EMERGING',
                    explanation TEXT,
                    trend_evidence TEXT,
                    market_opportunity TEXT,
                    topics JSONB DEFAULT '[]',
                    all_signals JSONB DEFAULT '[]',
                    ideas JSONB DEFAULT '[]',
                    references_ JSONB DEFAULT '[]',
                    confidence_history JSONB DEFAULT '[]',
                    direction_history JSONB DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS narrative_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
            """)
        conn.commit()
        _migrate_json_if_needed(conn)
        _pg_initialized = True
    finally:
        conn.close()


def _migrate_json_if_needed(conn):
    """If JSON file exists and DB is empty, migrate data."""
    if not os.path.exists(STORE_PATH):
        return
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM narrative_store")
        count = cur.fetchone()[0]
    if count > 0:
        return

    logger.info("Migrating narratives from JSON to PostgreSQL...")
    try:
        with open(STORE_PATH) as f:
            store = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return

    narratives = store.get("narratives", {})
    with conn.cursor() as cur:
        for nid, entry in narratives.items():
            _upsert_narrative(cur, nid, entry)
        # Meta
        cur.execute(
            "INSERT INTO narrative_meta (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            ("total_pipeline_runs", str(store.get("total_pipeline_runs", 0))),
        )
        cur.execute(
            "INSERT INTO narrative_meta (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            ("last_updated", store.get("last_updated", "")),
        )
    conn.commit()

    # Rename JSON to .bak
    bak = STORE_PATH + ".bak"
    try:
        os.rename(STORE_PATH, bak)
        logger.info(f"JSON migrated, renamed to {bak}")
    except OSError:
        pass


def _upsert_narrative(cur, nid: str, entry: Dict):
    cur.execute("""
        INSERT INTO narrative_store (id, name, canonical_name, status, first_detected, last_detected,
            last_updated, faded_at, detection_count, missed_count, current_confidence, current_direction,
            explanation, trend_evidence, market_opportunity, topics, all_signals, ideas, references_,
            confidence_history, direction_history)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (id) DO UPDATE SET
            name=EXCLUDED.name, canonical_name=EXCLUDED.canonical_name, status=EXCLUDED.status,
            first_detected=EXCLUDED.first_detected, last_detected=EXCLUDED.last_detected,
            last_updated=EXCLUDED.last_updated, faded_at=EXCLUDED.faded_at,
            detection_count=EXCLUDED.detection_count, missed_count=EXCLUDED.missed_count,
            current_confidence=EXCLUDED.current_confidence, current_direction=EXCLUDED.current_direction,
            explanation=EXCLUDED.explanation, trend_evidence=EXCLUDED.trend_evidence,
            market_opportunity=EXCLUDED.market_opportunity, topics=EXCLUDED.topics,
            all_signals=EXCLUDED.all_signals, ideas=EXCLUDED.ideas, references_=EXCLUDED.references_,
            confidence_history=EXCLUDED.confidence_history, direction_history=EXCLUDED.direction_history
    """, (
        nid,
        entry.get("name", ""),
        entry.get("canonical_name", ""),
        entry.get("status", "ACTIVE"),
        entry.get("first_detected"),
        entry.get("last_detected"),
        entry.get("last_updated"),
        entry.get("faded_at"),
        entry.get("detection_count", 0),
        entry.get("missed_count", 0),
        entry.get("current_confidence", "MEDIUM"),
        entry.get("current_direction", "EMERGING"),
        entry.get("explanation", ""),
        entry.get("trend_evidence", ""),
        entry.get("market_opportunity", ""),
        json.dumps(entry.get("topics", [])),
        json.dumps(entry.get("all_signals", [])),
        json.dumps(entry.get("ideas", [])),
        json.dumps(entry.get("references", [])),
        json.dumps(entry.get("confidence_history", [])),
        json.dumps(entry.get("direction_history", [])),
    ))


def _row_to_entry(row, columns) -> Dict:
    d = dict(zip(columns, row))
    # Parse JSONB fields
    for key in ("topics", "all_signals", "ideas", "references_", "confidence_history", "direction_history"):
        val = d.get(key)
        if isinstance(val, str):
            d[key] = json.loads(val)
    # Map references_ -> references
    d["references"] = d.pop("references_", [])
    # Convert datetimes to ISO strings
    for key in ("first_detected", "last_detected", "last_updated", "faded_at"):
        val = d.get(key)
        if val and hasattr(val, "isoformat"):
            d[key] = val.isoformat()
    return d


_COLUMNS = [
    "id", "name", "canonical_name", "status", "first_detected", "last_detected",
    "last_updated", "faded_at", "detection_count", "missed_count", "current_confidence",
    "current_direction", "explanation", "trend_evidence", "market_opportunity",
    "topics", "all_signals", "ideas", "references_", "confidence_history", "direction_history",
]


def _load_all_narratives_pg() -> Dict[str, Dict]:
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {', '.join(_COLUMNS)} FROM narrative_store")
            rows = cur.fetchall()
        return {row[0]: _row_to_entry(row, _COLUMNS) for row in rows}
    finally:
        conn.close()


def _load_meta_pg() -> Dict:
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT key, value FROM narrative_meta")
            return {r[0]: r[1] for r in cur.fetchall()}
    finally:
        conn.close()


# ── JSON fallback (original) ──

def _load_store_json() -> Dict:
    try:
        with open(STORE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"narratives": {}, "last_updated": None, "total_pipeline_runs": 0}


def _save_store_json(store: Dict):
    os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
    store["last_updated"] = _now_iso()
    with open(STORE_PATH, "w") as f:
        json.dump(store, f, indent=2)


# ── Public API ──

def load_store() -> Dict:
    """Load the narrative store."""
    if _use_pg():
        _ensure_tables()
        narratives = _load_all_narratives_pg()
        meta = _load_meta_pg()
        return {
            "narratives": narratives,
            "last_updated": meta.get("last_updated"),
            "total_pipeline_runs": int(meta.get("total_pipeline_runs", 0)),
        }
    return _load_store_json()


def save_store(store: Dict):
    """Persist the store."""
    if _use_pg():
        _ensure_tables()
        now = _now_iso()
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                for nid, entry in store.get("narratives", {}).items():
                    _upsert_narrative(cur, nid, entry)
                cur.execute(
                    "INSERT INTO narrative_meta (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                    ("total_pipeline_runs", str(store.get("total_pipeline_runs", 0))),
                )
                cur.execute(
                    "INSERT INTO narrative_meta (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                    ("last_updated", now),
                )
            conn.commit()
        finally:
            conn.close()
        store["last_updated"] = now
    else:
        _save_store_json(store)


def find_match(canonical_name: str, store: Dict, threshold: float = 0.5) -> Optional[str]:
    best_id, best_score = None, threshold
    for nid, entry in store.get("narratives", {}).items():
        score = _word_overlap(canonical_name, entry.get("canonical_name", ""))
        if score > best_score:
            best_id, best_score = nid, score
    return best_id


def _dedup_signals(signals: List[Dict], cap: int = 30) -> List[Dict]:
    seen_urls = {}
    no_url = []
    for s in signals:
        url = s.get("url", "")
        if url:
            existing = seen_urls.get(url)
            if existing is None or s.get("score", 0) > existing.get("score", 0):
                seen_urls[url] = s
        else:
            no_url.append(s)
    merged = list(seen_urls.values()) + no_url
    merged.sort(key=lambda x: x.get("score", 0), reverse=True)
    return merged[:cap]


def merge_narratives(new_narratives: List[Dict], store: Dict) -> Dict:
    now = _now_iso()
    store.setdefault("narratives", {})
    store["total_pipeline_runs"] = store.get("total_pipeline_runs", 0) + 1

    matched_ids = set()

    for n in new_narratives:
        name = n.get("name", "")
        canon = _canonical(name)
        matched_id = find_match(canon, store)

        if matched_id:
            entry = store["narratives"][matched_id]
            entry["name"] = name
            entry["canonical_name"] = canon
            entry["last_detected"] = now
            entry["last_updated"] = now
            entry["detection_count"] = entry.get("detection_count", 0) + 1
            entry["missed_count"] = 0
            entry["status"] = "ACTIVE"
            entry["current_confidence"] = n.get("confidence", entry.get("current_confidence", "MEDIUM"))
            entry["current_direction"] = n.get("direction", entry.get("current_direction", "EMERGING"))
            entry["explanation"] = n.get("explanation", entry.get("explanation", ""))
            entry["trend_evidence"] = n.get("trend_evidence", entry.get("trend_evidence", ""))
            entry["market_opportunity"] = n.get("market_opportunity", entry.get("market_opportunity", ""))
            entry["topics"] = n.get("topics", entry.get("topics", []))
            entry["ideas"] = n.get("ideas", entry.get("ideas", []))
            entry["references"] = n.get("references", entry.get("references", []))

            entry.setdefault("confidence_history", [])
            entry["confidence_history"].append({"time": now, "confidence": entry["current_confidence"]})
            entry["confidence_history"] = entry["confidence_history"][-20:]

            entry.setdefault("direction_history", [])
            entry["direction_history"].append({"time": now, "direction": entry["current_direction"]})
            entry["direction_history"] = entry["direction_history"][-20:]

            old_signals = entry.get("all_signals", [])
            new_signals = n.get("supporting_signals", [])
            entry["all_signals"] = _dedup_signals(old_signals + new_signals, cap=30)

            matched_ids.add(matched_id)
        else:
            nid = _stable_id(canon)
            while nid in store["narratives"]:
                nid = nid + "x"

            store["narratives"][nid] = {
                "id": nid,
                "name": name,
                "canonical_name": canon,
                "first_detected": now,
                "last_detected": now,
                "last_updated": now,
                "detection_count": 1,
                "missed_count": 0,
                "status": "ACTIVE",
                "confidence_history": [{"time": now, "confidence": n.get("confidence", "MEDIUM")}],
                "direction_history": [{"time": now, "direction": n.get("direction", "EMERGING")}],
                "current_confidence": n.get("confidence", "MEDIUM"),
                "current_direction": n.get("direction", "EMERGING"),
                "explanation": n.get("explanation", ""),
                "trend_evidence": n.get("trend_evidence", ""),
                "market_opportunity": n.get("market_opportunity", ""),
                "topics": n.get("topics", []),
                "all_signals": _dedup_signals(n.get("supporting_signals", []), cap=30),
                "ideas": n.get("ideas", []),
                "references": n.get("references", []),
            }
            matched_ids.add(nid)

    for nid, entry in store["narratives"].items():
        if nid not in matched_ids and entry.get("status") == "ACTIVE":
            entry["missed_count"] = entry.get("missed_count", 0) + 1
            if entry["missed_count"] >= 3:
                entry["status"] = "FADED"
                entry["faded_at"] = now

    for entry in store["narratives"].values():
        if entry.get("status") == "FADED" and entry.get("faded_at"):
            try:
                faded_dt = datetime.fromisoformat(entry["faded_at"])
                if datetime.now(timezone.utc) - faded_dt > timedelta(days=7):
                    entry["status"] = "ARCHIVED"
            except (ValueError, TypeError):
                pass

    return store


def get_active_narratives(store: Dict) -> List[Dict]:
    if _use_pg():
        _ensure_tables()
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT {', '.join(_COLUMNS)} FROM narrative_store
                    WHERE status = 'ACTIVE'
                    ORDER BY
                        CASE current_confidence WHEN 'HIGH' THEN 3 WHEN 'MEDIUM' THEN 2 ELSE 1 END DESC,
                        detection_count DESC
                """)
                return [_row_to_entry(row, _COLUMNS) for row in cur.fetchall()]
        finally:
            conn.close()

    conf_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    active = [e for e in store.get("narratives", {}).values() if e.get("status") == "ACTIVE"]
    active.sort(key=lambda e: (conf_order.get(e.get("current_confidence", "LOW"), 0), e.get("detection_count", 0)), reverse=True)
    return active


def get_recently_faded(store: Dict, hours: int = 24) -> List[Dict]:
    if _use_pg():
        _ensure_tables()
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT {', '.join(_COLUMNS)} FROM narrative_store
                    WHERE status = 'FADED' AND faded_at > now() - interval '%s hours'
                """, (hours,))
                return [_row_to_entry(row, _COLUMNS) for row in cur.fetchall()]
        finally:
            conn.close()

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    faded = []
    for entry in store.get("narratives", {}).values():
        if entry.get("status") == "FADED" and entry.get("faded_at"):
            try:
                faded_dt = datetime.fromisoformat(entry["faded_at"])
                if faded_dt > cutoff:
                    faded.append(entry)
            except (ValueError, TypeError):
                pass
    return faded


def get_active_narrative_hints(store: Dict) -> List[str]:
    hints = []
    now = datetime.now(timezone.utc)
    for entry in store.get("narratives", {}).values():
        if entry.get("status") not in ("ACTIVE", "FADED"):
            continue
        name = entry.get("name", "")
        count = entry.get("detection_count", 0)
        try:
            last = datetime.fromisoformat(entry.get("last_detected", ""))
            delta = now - last
            hours = int(delta.total_seconds() / 3600)
            if hours < 1:
                ago = f"{int(delta.total_seconds()/60)}m ago"
            elif hours < 24:
                ago = f"{hours}h ago"
            else:
                ago = f"{delta.days}d ago"
        except Exception:
            ago = "unknown"
        hints.append(f"- {name} (detected {count} times, last: {ago})")
    return hints


def _compute_trending_status(entry: Dict) -> str:
    status = entry.get("status", "ACTIVE")
    if status == "FADED":
        return "FADED"
    first = entry.get("first_detected", "")
    if first:
        try:
            first_dt = datetime.fromisoformat(first)
            if datetime.now(timezone.utc) - first_dt < timedelta(hours=24):
                return "NEW"
        except (ValueError, TypeError):
            pass
    hist = entry.get("confidence_history", [])
    conf_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    if len(hist) >= 2:
        recent = conf_order.get(hist[-1].get("confidence", ""), 1)
        prev = conf_order.get(hist[-2].get("confidence", ""), 1)
        if recent > prev:
            return "RISING"
        if recent < prev:
            return "DECLINING"
    if entry.get("detection_count", 0) >= 3:
        return "STABLE"
    return "RISING" if entry.get("detection_count", 0) <= 1 else "STABLE"


def store_entry_to_api(entry: Dict) -> Dict:
    return {
        "name": entry.get("name", ""),
        "confidence": entry.get("current_confidence", "MEDIUM"),
        "direction": entry.get("current_direction", "EMERGING"),
        "explanation": entry.get("explanation", ""),
        "trend_evidence": entry.get("trend_evidence", ""),
        "market_opportunity": entry.get("market_opportunity", ""),
        "topics": entry.get("topics", []),
        "supporting_signals": entry.get("all_signals", []),
        "ideas": entry.get("ideas", []),
        "references": entry.get("references", []),
        "status": _compute_trending_status(entry),
        "first_detected": entry.get("first_detected", ""),
        "last_detected": entry.get("last_detected", ""),
        "detection_count": entry.get("detection_count", 0),
        "confidence_history": entry.get("confidence_history", []),
        "direction_history": entry.get("direction_history", []),
        "total_pipeline_runs": 0,
    }
