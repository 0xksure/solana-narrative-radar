"""Track narrative state over time: NEW, RISING, STABLE, DECLINING, FADED"""
import json
import os
from datetime import datetime, timezone
from typing import List, Dict

HISTORY_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "narrative_history.json")


def _load_history() -> Dict:
    try:
        with open(HISTORY_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"narratives": {}, "last_updated": None}


def _save_history(history: Dict):
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)


def _normalize_name(name: str) -> str:
    return name.strip().lower()


def _confidence_to_num(conf: str) -> int:
    return {"HIGH": 3, "MEDIUM": 2, "LOW": 1}.get((conf or "").upper(), 0)


def update_narrative_states(narratives: List[Dict]) -> List[Dict]:
    """Compare current narratives against history and assign status fields.
    
    Returns the narratives list with 'status' added to each, plus any FADED narratives appended.
    """
    now = datetime.now(timezone.utc).isoformat()
    history = _load_history()
    prev = history.get("narratives", {})
    
    current_keys = set()
    
    for n in narratives:
        key = _normalize_name(n.get("name", ""))
        current_keys.add(key)
        cur_conf = _confidence_to_num(n.get("confidence", ""))
        
        if key in prev:
            prev_conf = prev[key].get("confidence_num", 0)
            if cur_conf > prev_conf:
                n["status"] = "RISING"
            elif cur_conf < prev_conf:
                n["status"] = "DECLINING"
            else:
                n["status"] = "STABLE"
            # Update history entry
            prev[key]["last_seen"] = now
            prev[key]["confidence"] = n.get("confidence", "")
            prev[key]["confidence_num"] = cur_conf
            prev[key]["seen_count"] = prev[key].get("seen_count", 1) + 1
        else:
            n["status"] = "NEW"
            prev[key] = {
                "name": n.get("name", ""),
                "confidence": n.get("confidence", ""),
                "confidence_num": cur_conf,
                "first_seen": now,
                "last_seen": now,
                "seen_count": 1,
            }
    
    # Find FADED narratives (were in history but not in current)
    faded = []
    for key, entry in prev.items():
        if key not in current_keys and entry.get("last_seen") != "faded":
            faded.append({
                "name": entry["name"],
                "confidence": entry.get("confidence", "LOW"),
                "direction": "STABILIZING",
                "explanation": f"This narrative was previously detected but is no longer showing strong signals.",
                "status": "FADED",
                "supporting_signals": [],
                "ideas": [],
                "first_seen": entry.get("first_seen"),
                "last_seen": entry.get("last_seen"),
            })
    
    history["narratives"] = prev
    history["last_updated"] = now
    _save_history(history)
    
    return narratives + faded
