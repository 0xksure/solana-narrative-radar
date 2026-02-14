#!/usr/bin/env python3
"""Run the Telegram bot in polling mode (for development/standalone worker).

For production, use webhook mode via the /api/telegram/webhook endpoint instead.

Usage:
    TELEGRAM_BOT_TOKEN=xxx DATABASE_URL=xxx python run_telegram_bot.py

Webhook setup (preferred for production):
    Set TELEGRAM_BOT_TOKEN and call:
    curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
        -d "url=https://solana-narrative-radar-8vsib.ondigitalocean.app/api/telegram/webhook"
"""
import asyncio
import logging
import os
import sys

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Reuse our bot logic
from telegram_bot import (
    subscribe, unsubscribe, send_message,
    _build_status_message, _build_narratives_message, get_subscriber_count,
    RADAR_URL, _escape_md,
)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")


async def cmd_start(update: Update, context):
    chat_id = update.effective_chat.id
    username = update.effective_user.username if update.effective_user else None
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
    await update.message.reply_markdown(reply)


async def cmd_stop(update: Update, context):
    was_active = unsubscribe(update.effective_chat.id)
    reply = "🔕 Unsubscribed. Use /start to re-subscribe anytime." if was_active else "You weren't subscribed. Use /start to subscribe."
    await update.message.reply_text(reply)


async def cmd_status(update: Update, context):
    msg = await _build_status_message()
    await update.message.reply_markdown(msg)


async def cmd_narratives(update: Update, context):
    msg = await _build_narratives_message()
    await update.message.reply_markdown(msg)


async def cmd_alerts(update: Update, context):
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
    await update.message.reply_markdown(reply)


async def fallback(update: Update, context):
    reply = (
        "🔭 *Solana Narrative Radar Bot*\n\n"
        "/start — Subscribe to alerts\n"
        "/stop — Unsubscribe\n"
        "/status — Current summary\n"
        "/narratives — Active narratives\n"
        "/alerts — Alert settings"
    )
    await update.message.reply_markdown(reply)


def main():
    if not TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("narratives", cmd_narratives))
    app.add_handler(CommandHandler("alerts", cmd_alerts))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))

    logger.info("Starting Telegram bot in polling mode...")
    app.run_polling()


if __name__ == "__main__":
    main()
