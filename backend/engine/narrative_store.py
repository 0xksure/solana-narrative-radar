"""Persistent narrative store with fuzzy matching and signal accumulation."""
import hashlib
import json
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

STORE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "narratives_db.json")

# Words to ignore when computing canonical names / overlap
_STOP_WORDS = frozenset({
    "the", "and", "for", "with", "on", "in", "of", "a", "an", "to", "is",
    "solana", "sol", "protocol", "ecosystem", "network", "based", "powered",
})


def _canonical(name: str) -> str:
    """Lowercase, strip punctuation, remove stop words."""
    words = re.split(r"[^a-z0-9]+", name.lower())
    return " ".join(w for w in words if w and w not in _STOP_WORDS)


def _stable_id(canonical_name: str) -> str:
    return hashlib.sha256(canonical_name.encode()).hexdigest()[:16]


def _word_set(canonical: str) -> set:
    return set(canonical.split())


def _word_overlap(a: str, b: str) -> float:
    """Return fraction of overlapping words (Jaccard-ish: intersection / min(len_a, len_b))."""
    wa, wb = _word_set(a), _word_set(b)
    if not wa or not wb:
        return 0.0
    overlap = len(wa & wb)
    return overlap / min(len(wa), len(wb))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Public API ──


def load_store() -> Dict:
    """Load the narrative store from disk."""
    try:
        with open(STORE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"narratives": {}, "last_updated": None, "total_pipeline_runs": 0}


def save_store(store: Dict):
    """Persist the store to disk."""
    os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
    store["last_updated"] = _now_iso()
    with open(STORE_PATH, "w") as f:
        json.dump(store, f, indent=2)


def find_match(canonical_name: str, store: Dict, threshold: float = 0.5) -> Optional[str]:
    """Find an existing narrative ID whose canonical name overlaps above threshold.
    
    Returns the best-matching narrative ID, or None.
    """
    best_id, best_score = None, threshold
    for nid, entry in store.get("narratives", {}).items():
        score = _word_overlap(canonical_name, entry.get("canonical_name", ""))
        if score > best_score:
            best_id, best_score = nid, score
    return best_id


def _dedup_signals(signals: List[Dict], cap: int = 30) -> List[Dict]:
    """Deduplicate signals by URL, keep most recent / highest engagement, cap at `cap`."""
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
    # Sort by score descending, then take cap
    merged.sort(key=lambda x: x.get("score", 0), reverse=True)
    return merged[:cap]


def merge_narratives(new_narratives: List[Dict], store: Dict) -> Dict:
    """Merge new pipeline narratives into the persistent store.
    
    - Fuzzy-matches new narratives to existing ones
    - Accumulates signals
    - Increments missed_count for unmatched active narratives
    - Returns updated store
    """
    now = _now_iso()
    store.setdefault("narratives", {})
    store["total_pipeline_runs"] = store.get("total_pipeline_runs", 0) + 1

    matched_ids = set()

    for n in new_narratives:
        name = n.get("name", "")
        canon = _canonical(name)
        matched_id = find_match(canon, store)

        if matched_id:
            # Update existing narrative
            entry = store["narratives"][matched_id]
            entry["name"] = name  # use latest name
            entry["canonical_name"] = canon
            entry["last_detected"] = now
            entry["last_updated"] = now
            entry["detection_count"] = entry.get("detection_count", 0) + 1
            entry["missed_count"] = 0
            entry["status"] = "ACTIVE"

            # Update current fields
            entry["current_confidence"] = n.get("confidence", entry.get("current_confidence", "MEDIUM"))
            entry["current_direction"] = n.get("direction", entry.get("current_direction", "EMERGING"))
            entry["explanation"] = n.get("explanation", entry.get("explanation", ""))
            entry["trend_evidence"] = n.get("trend_evidence", entry.get("trend_evidence", ""))
            entry["market_opportunity"] = n.get("market_opportunity", entry.get("market_opportunity", ""))
            entry["topics"] = n.get("topics", entry.get("topics", []))
            entry["ideas"] = n.get("ideas", entry.get("ideas", []))
            entry["references"] = n.get("references", entry.get("references", []))

            # History
            entry.setdefault("confidence_history", [])
            entry["confidence_history"].append({"time": now, "confidence": entry["current_confidence"]})
            entry["confidence_history"] = entry["confidence_history"][-20:]  # cap history

            entry.setdefault("direction_history", [])
            entry["direction_history"].append({"time": now, "direction": entry["current_direction"]})
            entry["direction_history"] = entry["direction_history"][-20:]

            # Accumulate signals
            old_signals = entry.get("all_signals", [])
            new_signals = n.get("supporting_signals", [])
            entry["all_signals"] = _dedup_signals(old_signals + new_signals, cap=30)

            matched_ids.add(matched_id)
        else:
            # Create new entry
            nid = _stable_id(canon)
            # Avoid collision
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

    # Handle unmatched active narratives — increment missed_count
    for nid, entry in store["narratives"].items():
        if nid not in matched_ids and entry.get("status") == "ACTIVE":
            entry["missed_count"] = entry.get("missed_count", 0) + 1
            if entry["missed_count"] >= 3:
                entry["status"] = "FADED"
                entry["faded_at"] = now

    # Archive narratives that have been FADED for 7+ days
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
    """Get ACTIVE narratives sorted by confidence then detection_count."""
    conf_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    active = []
    for entry in store.get("narratives", {}).values():
        if entry.get("status") == "ACTIVE":
            active.append(entry)
    active.sort(key=lambda e: (conf_order.get(e.get("current_confidence", "LOW"), 0), e.get("detection_count", 0)), reverse=True)
    return active


def get_recently_faded(store: Dict, hours: int = 24) -> List[Dict]:
    """Get narratives that faded within the last `hours` hours."""
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
    """Return hint lines for the LLM prompt listing previously detected narratives."""
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


def store_entry_to_api(entry: Dict) -> Dict:
    """Convert a store entry to the API/report format expected by the frontend."""
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
        "status": entry.get("status", "ACTIVE"),
        "first_detected": entry.get("first_detected", ""),
        "last_detected": entry.get("last_detected", ""),
        "detection_count": entry.get("detection_count", 0),
        "confidence_history": entry.get("confidence_history", []),
        "direction_history": entry.get("direction_history", []),
        "total_pipeline_runs": 0,  # filled in by caller
    }
