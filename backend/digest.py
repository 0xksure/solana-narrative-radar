"""
Email digest generation and sending for Solana Narrative Radar.
"""
import os
import json
import uuid
import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

import asyncpg
import httpx

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
DIGEST_API_KEY = os.environ.get("DIGEST_API_KEY", "")
AGENTMAIL_API_KEY = ""
AGENTMAIL_FROM = "maxverstrappen@agentmail.to"
BASE_URL = os.environ.get("BASE_URL", "https://solana-narrative-radar-8vsib.ondigitalocean.app")

REPORT_PATH = os.path.join(os.path.dirname(__file__), "data", "latest_report.json")

_pool: Optional[asyncpg.Pool] = None


def _load_agentmail_key():
    global AGENTMAIL_API_KEY
    if AGENTMAIL_API_KEY:
        return AGENTMAIL_API_KEY
    try:
        with open(os.path.expanduser("~/.config/agentmail/api_key")) as f:
            AGENTMAIL_API_KEY = f.read().strip()
    except Exception:
        AGENTMAIL_API_KEY = os.environ.get("AGENTMAIL_API_KEY", "")
    return AGENTMAIL_API_KEY


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
    return _pool


async def subscribe(email: str, frequency: str = "weekly") -> dict:
    pool = await get_pool()
    verify_token = str(uuid.uuid4())
    unsubscribe_token = str(uuid.uuid4())
    try:
        await pool.execute(
            """INSERT INTO email_subscribers (email, verify_token, unsubscribe_token, frequency)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (email) DO UPDATE SET frequency = $4, subscribed_at = NOW()""",
            email, verify_token, unsubscribe_token, frequency
        )
        return {"status": "ok", "message": "Subscribed successfully"}
    except Exception as e:
        logger.error("Subscribe error: %s", e)
        return {"status": "error", "message": str(e)}


async def unsubscribe(token: str) -> bool:
    pool = await get_pool()
    result = await pool.execute(
        "DELETE FROM email_subscribers WHERE unsubscribe_token = $1", token
    )
    return "DELETE 1" in result


def load_report() -> dict:
    try:
        with open(REPORT_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def generate_digest_html(report: dict, unsubscribe_token: str = "", frequency: str = "daily") -> str:
    """Generate HTML email digest from the latest report."""
    narratives = report.get("narratives", [])
    generated_at = report.get("generated_at", "")

    active = [n for n in narratives if n.get("confidence", "").lower() in ("high", "medium")]
    active.sort(key=lambda n: {"high": 0, "medium": 1}.get(n.get("confidence", "").lower(), 2))

    ideas = []
    for n in narratives:
        for idea in n.get("build_ideas", []):
            if isinstance(idea, str):
                ideas.append({"idea": idea, "narrative": n.get("name", "")})
            elif isinstance(idea, dict):
                ideas.append({**idea, "narrative": n.get("name", "")})
    ideas = ideas[:5]

    unsubscribe_url = f"{BASE_URL}/api/unsubscribe?token={unsubscribe_token}" if unsubscribe_token else "#"

    narratives_html = ""
    for n in active[:8]:
        name = n.get("name", "Unknown")
        confidence = n.get("confidence", "low")
        direction = n.get("direction", "—")
        signal_count = len(n.get("signals", []))
        conf_color = {"high": "#22c55e", "medium": "#f59e0b"}.get(confidence.lower(), "#64748b")
        dir_emoji = {"rising": "📈", "surging": "🚀", "stable": "➡️", "declining": "📉"}.get(direction.lower(), "—")

        projects = n.get("existing_projects", [])
        projects_html = ""
        if projects:
            tags = " ".join(f'<span style="background:#1a1a2e;padding:2px 8px;border-radius:10px;font-size:11px;color:#9945ff">{p}</span>' for p in projects[:4])
            projects_html = f'<div style="margin-top:6px">{tags}</div>'

        narratives_html += f"""
        <div style="background:#12121a;border:1px solid #1e1e2e;border-left:3px solid {conf_color};border-radius:8px;padding:14px 16px;margin-bottom:10px">
            <div style="display:flex;justify-content:space-between;align-items:center">
                <span style="font-weight:600;color:#e2e8f0;font-size:14px">{name}</span>
                <span style="font-size:12px;color:{conf_color};font-weight:600">{confidence.upper()}</span>
            </div>
            <div style="font-size:12px;color:#94a3b8;margin-top:4px">{dir_emoji} {direction.title()} · {signal_count} signals</div>
            {projects_html}
        </div>"""

    ideas_html = ""
    for idea in ideas:
        idea_text = idea.get("idea", idea.get("name", str(idea)))
        narrative = idea.get("narrative", "")
        ideas_html += f"""
        <div style="padding:8px 0;border-bottom:1px solid #1e1e2e;font-size:13px">
            <span style="color:#e2e8f0">💡 {idea_text}</span>
            <span style="color:#64748b;font-size:11px;margin-left:8px">({narrative})</span>
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0a0a0f;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif">
<div style="max-width:600px;margin:0 auto;padding:20px">
    <div style="text-align:center;padding:24px 0;border-bottom:1px solid #1e1e2e;margin-bottom:24px">
        <h1 style="margin:0;font-size:20px;color:#9945ff;font-weight:700">🔮 Solana Narrative Radar</h1>
        <p style="margin:6px 0 0;font-size:12px;color:#64748b">{frequency.title()} Digest · {generated_at[:10] if generated_at else 'Latest'}</p>
    </div>

    <h2 style="font-size:14px;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px">Top Active Narratives</h2>
    {narratives_html if narratives_html else '<p style="color:#64748b;font-size:13px">No active narratives detected.</p>'}

    <h2 style="font-size:14px;color:#94a3b8;text-transform:uppercase;letter-spacing:1px;margin:24px 0 12px">Build Ideas</h2>
    <div style="background:#12121a;border:1px solid #1e1e2e;border-radius:8px;padding:12px 16px">
        {ideas_html if ideas_html else '<p style="color:#64748b;font-size:13px">No build ideas in current cycle.</p>'}
    </div>

    <div style="text-align:center;margin:32px 0 16px">
        <a href="{BASE_URL}" style="display:inline-block;background:#9945ff;color:white;padding:10px 28px;border-radius:6px;text-decoration:none;font-weight:600;font-size:13px">View Full Radar →</a>
    </div>

    <div style="text-align:center;padding:20px 0;border-top:1px solid #1e1e2e;margin-top:24px">
        <p style="color:#475569;font-size:11px;margin:0">Autonomous AI Agent · Solana Narrative Radar</p>
        <a href="{unsubscribe_url}" style="color:#64748b;font-size:11px">Unsubscribe</a>
    </div>
</div>
</body>
</html>"""


async def send_digest_email(to_email: str, html: str, subject: str = "Solana Narrative Radar Digest"):
    """Send digest email via AgentMail API."""
    api_key = _load_agentmail_key()
    if not api_key:
        logger.error("No AgentMail API key configured")
        return False

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.agentmail.to/v0/inboxes/{AGENTMAIL_FROM}/messages",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "to": [{"email": to_email}],
                    "subject": subject,
                    "html": html,
                },
                timeout=30,
            )
            if resp.status_code in (200, 201, 202):
                logger.info("Digest sent to %s", to_email)
                return True
            else:
                logger.error("AgentMail error %s: %s", resp.status_code, resp.text[:200])
                return False
    except Exception as e:
        logger.error("Send error: %s", e)
        return False


async def trigger_digest(frequency: Optional[str] = None):
    """Send digest to all subscribers (optionally filtered by frequency)."""
    pool = await get_pool()
    report = load_report()
    if not report:
        logger.warning("No report available for digest")
        return {"sent": 0, "errors": 0}

    query = "SELECT id, email, unsubscribe_token, frequency FROM email_subscribers"
    params = []
    if frequency:
        query += " WHERE frequency = $1"
        params.append(frequency)

    rows = await pool.fetch(query, *params)
    sent = 0
    errors = 0

    for row in rows:
        html = generate_digest_html(report, row["unsubscribe_token"], row["frequency"])
        subject = f"{'🔮 ' if row['frequency'] == 'daily' else '📊 '}Solana Narratives — {row['frequency'].title()} Digest"
        ok = await send_digest_email(row["email"], html, subject)
        if ok:
            sent += 1
            await pool.execute(
                "UPDATE email_subscribers SET last_sent_at = NOW() WHERE id = $1", row["id"]
            )
        else:
            errors += 1

    logger.info("Digest complete: %d sent, %d errors", sent, errors)
    return {"sent": sent, "errors": errors, "total": len(rows)}
