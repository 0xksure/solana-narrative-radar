"""Telegram bot for Solana Narrative Radar alerts.

Supports both webhook mode (production) and polling mode (development).
Bot token from TELEGRAM_BOT_TOKEN env var.
"""
import json
import logging
import os
from datetime import datetime, timezone
from typing import List, Optional, Dict

import httpx
import psycopg2

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
RADAR_URL = "https://solana-narrative-radar-8vsib.ondigitalocean.app"

# ── DB helpers ──

def _get_conn():
    return psycopg2.connect(DATABASE_URL)


def subscribe(chat_id: int, username: Optional[str] = None) -> bool:
    """Subscribe a chat. Returns True if new, False if already subscribed."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO telegram_subscribers (chat_id, username, active)
                VALUES (%s, %s, TRUE)
                ON CONFLICT (chat_id) DO UPDATE SET active = TRUE, username = COALESCE(EXCLUDED.username, telegram_subscribers.username)
                RETURNING (xmax = 0) AS is_new
            """, (chat_id, username))
            is_new = cur.fetchone()[0]
        conn.commit()
        return is_new
    finally:
        conn.close()


def unsubscribe(chat_id: int) -> bool:
    """Unsubscribe a chat. Returns True if was active."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE telegram_subscribers SET active = FALSE WHERE chat_id = %s AND active = TRUE
                RETURNING id
            """, (chat_id,))
            result = cur.fetchone()
        conn.commit()
        return result is not None
    finally:
        conn.close()


def get_active_chat_ids() -> List[int]:
    """Get all active subscriber chat IDs."""
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT chat_id FROM telegram_subscribers WHERE active = TRUE")
            return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()


def get_subscriber_count() -> int:
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM telegram_subscribers WHERE active = TRUE")
            return cur.fetchone()[0]
    finally:
        conn.close()


# ── Telegram API ──

async def send_message(chat_id: int, text: str, parse_mode: str = "Markdown") -> bool:
    """Send a message via Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set, skipping send")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode, "disable_web_page_preview": True}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                return True
            # If Markdown fails, retry without parse_mode
            if resp.status_code == 400 and "parse" in resp.text.lower():
                payload["parse_mode"] = None
                resp = await client.post(url, json=payload)
                return resp.status_code == 200
            logger.error("Telegram send failed: %s %s", resp.status_code, resp.text)
            return False
    except Exception as e:
        logger.error("Telegram send error: %s", e)
        return False


async def broadcast(text: str) -> Dict[str, int]:
    """Send a message to all active subscribers. Returns success/fail counts."""
    chat_ids = get_active_chat_ids()
    sent, failed = 0, 0
    for chat_id in chat_ids:
        ok = await send_message(chat_id, text)
        if ok:
            sent += 1
        else:
            failed += 1
    logger.info("Telegram broadcast: %d sent, %d failed out of %d", sent, failed, len(chat_ids))
    return {"sent": sent, "failed": failed, "total": len(chat_ids)}


# ── Alert formatters ──

def format_new_narrative(name: str, confidence: str, direction: str) -> str:
    return (
        f"🆕 *New Narrative Detected*\n\n"
        f"*{_escape_md(name)}*\n"
        f"Confidence: {confidence} | Direction: {direction}\n\n"
        f"[View on Radar]({RADAR_URL})"
    )


def format_direction_change(name: str, old_direction: str, new_direction: str) -> str:
    return (
        f"📈 *Direction Change*\n\n"
        f"*{_escape_md(name)}*\n"
        f"{old_direction} → {new_direction}\n\n"
        f"[View on Radar]({RADAR_URL})"
    )


def format_narrative_faded(name: str, age_hours: int) -> str:
    if age_hours < 24:
        age_str = f"{age_hours}h"
    else:
        age_str = f"{age_hours // 24}d"
    return (
        f"👻 *Narrative Faded*\n\n"
        f"*{_escape_md(name)}* has faded after {age_str}\n\n"
        f"[View on Radar]({RADAR_URL})"
    )


def format_high_confidence(name: str, direction: str) -> str:
    return (
        f"🔥 *High Confidence Narrative*\n\n"
        f"*{_escape_md(name)}* has reached HIGH confidence\n"
        f"Direction: {direction}\n\n"
        f"[View on Radar]({RADAR_URL})"
    )


def _escape_md(text: str) -> str:
    """Escape Markdown v1 special chars."""
    for ch in ['_', '*', '`', '[']:
        text = text.replace(ch, f'\\{ch}')
    return text


# ── Notification dispatcher (called from narrative_store after merge) ──

async def notify_narrative_changes(
    new_narratives: List[Dict],
    direction_changes: List[Dict],
    faded_narratives: List[Dict],
    high_confidence_new: List[Dict],
):
    """Send alerts for all narrative changes. Called after merge_narratives."""
    if not TELEGRAM_BOT_TOKEN or not DATABASE_URL:
        return

    for n in new_narratives:
        msg = format_new_narrative(n["name"], n.get("confidence", "MEDIUM"), n.get("direction", "EMERGING"))
        await broadcast(msg)

    for n in direction_changes:
        msg = format_direction_change(n["name"], n["old_direction"], n["new_direction"])
        await broadcast(msg)

    for n in faded_narratives:
        msg = format_narrative_faded(n["name"], n.get("age_hours", 0))
        await broadcast(msg)

    for n in high_confidence_new:
        msg = format_high_confidence(n["name"], n.get("direction", "EMERGING"))
        await broadcast(msg)


# ── Webhook handler (called from FastAPI route) ──

async def handle_webhook_update(update: dict) -> str:
    """Process an incoming Telegram webhook update."""
    message = update.get("message", {})
    if not message:
        return "ok"

    chat_id = message.get("chat", {}).get("id")
    text = (message.get("text") or "").strip()
    username = message.get("from", {}).get("username")

    if not chat_id or not text:
        return "ok"

    if text == "/start":
        is_new = subscribe(chat_id, username)
        if is_new:
            reply = (
                "✅ *Subscribed to Solana Narrative Radar!*\n\n"
                "You'll receive alerts when:\n"
                "• 🆕 New narratives are detected\n"
                "• 📈 Narratives change direction\n"
                "• 👻 Narratives fade\n"
                "• 🔥 Narratives hit HIGH confidence\n\n"
                "Commands:\n"
                "/status — Current summary\n"
                "/narratives — All active narratives\n"
                "/alerts — Alert settings\n"
                "/stop — Unsubscribe"
            )
        else:
            reply = "👋 Welcome back! You're already subscribed."
        await send_message(chat_id, reply)

    elif text == "/stop":
        was_active = unsubscribe(chat_id)
        if was_active:
            reply = "🔕 Unsubscribed. Use /start to re-subscribe anytime."
        else:
            reply = "You weren't subscribed. Use /start to subscribe."
        await send_message(chat_id, reply)

    elif text == "/status":
        reply = await _build_status_message()
        await send_message(chat_id, reply)

    elif text == "/narratives":
        reply = await _build_narratives_message()
        await send_message(chat_id, reply)

    elif text == "/alerts":
        count = get_subscriber_count()
        reply = (
            "🔔 *Alert Settings*\n\n"
            "Currently sending alerts for:\n"
            "• 🆕 New narrative detection\n"
            "• 📈 Direction changes\n"
            "• 👻 Narrative fading\n"
            "• 🔥 High confidence milestones\n\n"
            f"Active subscribers: {count}\n"
            "Pipeline runs every 2 hours."
        )
        await send_message(chat_id, reply)

    else:
        reply = (
            "🔭 *Solana Narrative Radar Bot*\n\n"
            "/start — Subscribe to alerts\n"
            "/stop — Unsubscribe\n"
            "/status — Current summary\n"
            "/narratives — Active narratives\n"
            "/alerts — Alert settings"
        )
        await send_message(chat_id, reply)

    return "ok"


async def _build_status_message() -> str:
    """Build a status summary message."""
    try:
        from engine.narrative_store import load_store, get_active_narratives
        store = load_store()
        active = get_active_narratives(store)
        total = store.get("total_pipeline_runs", 0)

        high = sum(1 for n in active if n.get("current_confidence") == "HIGH")
        medium = sum(1 for n in active if n.get("current_confidence") == "MEDIUM")
        low = sum(1 for n in active if n.get("current_confidence") == "LOW")

        return (
            f"📊 *Narrative Radar Status*\n\n"
            f"Active narratives: {len(active)}\n"
            f"• HIGH confidence: {high}\n"
            f"• MEDIUM confidence: {medium}\n"
            f"• LOW confidence: {low}\n\n"
            f"Total pipeline runs: {total}\n"
            f"Last updated: {store.get('last_updated', 'unknown')}\n\n"
            f"[Open Radar]({RADAR_URL})"
        )
    except Exception as e:
        logger.error("Status message error: %s", e)
        return "⚠️ Could not fetch status. Try again later."


async def _build_narratives_message() -> str:
    """Build a list of active narratives."""
    try:
        from engine.narrative_store import load_store, get_active_narratives
        store = load_store()
        active = get_active_narratives(store)

        if not active:
            return "No active narratives detected yet. Check back after the next pipeline run."

        lines = ["📡 *Active Narratives*\n"]
        for n in active[:15]:  # Cap at 15 to avoid message length limits
            name = _escape_md(n.get("name", "?"))
            conf = n.get("current_confidence", "?")
            direction = n.get("current_direction", "?")
            count = n.get("detection_count", 0)
            emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "⚪"}.get(conf, "⚪")
            lines.append(f"{emoji} *{name}*\n   {conf} | {direction} | seen {count}x")

        lines.append(f"\n[View all on Radar]({RADAR_URL})")
        return "\n".join(lines)
    except Exception as e:
        logger.error("Narratives message error: %s", e)
        return "⚠️ Could not fetch narratives. Try again later."
