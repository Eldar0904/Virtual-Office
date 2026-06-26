"""
Virtual Office — Telegram relay bot (text only, no AI).

Messages from Telegram users are forwarded to the Virtual Office API.
Staff replies typed in the web UI are sent back to users here.

Run (from project root):
    python -m telegram_bot.bot
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
API_BASE = os.getenv(
    "VIRTUAL_OFFICE_API",
    "https://virtual-office-delta-fawn.vercel.app",
).rstrip("/")
POLL_INTERVAL = 2  # seconds between reply-queue polls


# ── Handlers ──────────────────────────────────────────────────────────────────

async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Welcome to Virtual Office Front Desk.\n"
        "Send a message and our team will reply here."
    )


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    user = msg.from_user
    name = (user.full_name or user.username or str(user.id)).strip()

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.post(
                f"{API_BASE}/telegram/message",
                json={
                    "chat_id": msg.chat_id,
                    "name": name,
                    "username": user.username or "",
                    "text": msg.text or "",
                },
            )
            r.raise_for_status()
        except httpx.HTTPError:
            await msg.reply_text("⚠️ Virtual Office API is offline. Please try again later.")
            return

    await msg.reply_text("✓ Message received. Our team will reply shortly.")


async def reply_poller(app: Application) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        while True:
            await asyncio.sleep(POLL_INTERVAL)
            try:
                r = await client.get(f"{API_BASE}/telegram/pending-replies")
                r.raise_for_status()
                for item in r.json().get("replies", []):
                    await app.bot.send_message(
                        chat_id=item["chat_id"],
                        text=item["text"],
                    )
            except Exception:
                pass


async def check_api() -> bool:
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.get(f"{API_BASE}/")
            return r.status_code == 200
        except httpx.HTTPError:
            return False


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    if not await check_api():
        print(f"WARNING: API not reachable at {API_BASE}")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    print(f"Virtual Office relay bot running")
    print(f"  API:     {API_BASE}")
    print(f"  Polling: every {POLL_INTERVAL}s for staff replies")

    async with app:
        await app.start()
        poller = asyncio.create_task(reply_poller(app))
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        await poller


if __name__ == "__main__":
    asyncio.run(main())
