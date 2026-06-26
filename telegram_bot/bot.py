"""
Virtual Office — Telegram relay bot (text only, no AI).

Messages from Telegram users are forwarded to the Virtual Office API.
Staff replies typed in the web UI are sent back to users here.

Run:
    set TELEGRAM_BOT_TOKEN=your_token
    python -m telegram_bot.bot
"""
from __future__ import annotations

import asyncio
import os
import time

import httpx
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

# ── Config ────────────────────────────────────────────────────────────────────

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
API_BASE  = os.getenv("VIRTUAL_OFFICE_API", "http://localhost:8000")
POLL_INTERVAL = 2   # seconds between reply-queue polls


# ── Forward incoming messages to the office API ───────────────────────────────

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg  = update.message
    user = msg.from_user
    name = (user.full_name or user.username or str(user.id)).strip()

    async with httpx.AsyncClient(timeout=5) as client:
        try:
            await client.post(
                f"{API_BASE}/telegram/message",
                json={
                    "chat_id":  msg.chat_id,
                    "name":     name,
                    "username": user.username or "",
                    "text":     msg.text or "",
                },
            )
        except httpx.RequestError:
            await msg.reply_text("⚠️ Virtual Office API is offline. Please try again later.")


# ── Background task: poll for staff replies and send them ─────────────────────

async def reply_poller(app: Application) -> None:
    async with httpx.AsyncClient(timeout=5) as client:
        while True:
            await asyncio.sleep(POLL_INTERVAL)
            try:
                r = await client.get(f"{API_BASE}/telegram/pending-replies")
                for item in r.json().get("replies", []):
                    await app.bot.send_message(
                        chat_id=item["chat_id"],
                        text=item["text"],
                    )
            except Exception:
                pass   # silently retry next cycle


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    print(f"Virtual Office relay bot running — polling {API_BASE} every {POLL_INTERVAL}s")

    async with app:
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        await reply_poller(app)   # runs forever


if __name__ == "__main__":
    asyncio.run(main())
