from __future__ import annotations

import datetime
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

# ── Constants ─────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent.parent
UI_DIR   = BASE_DIR / "ui"

STATE_FILES: dict[str, Path] = {
    "logistics_log": BASE_DIR / "daily-ops" / "logistics_log.md",
    "system_status": BASE_DIR / "tech-core" / "system_status.md",
    "quest_board":   BASE_DIR / "daily-ops" / "quest_board.md",
    "hr_log":        BASE_DIR / "administration" / "hr_log.md",
}

# ── Telegram relay store ──────────────────────────────────────────────────────
# { chat_id: { "name": str, "username": str, "messages": [...] } }
tg_chats: dict[int, dict[str, Any]] = {}

# Replies queued by UI staff, consumed by the bot process
# [ { "chat_id": int, "text": str } ]
tg_reply_queue: list[dict[str, Any]] = []

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Virtual Office API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Models ────────────────────────────────────────────────────────────────────

class LogWrite(BaseModel):
    content: str
    append: bool = True


class TgIncoming(BaseModel):
    chat_id:  int
    name:     str
    username: str = ""
    text:     str


class TgReply(BaseModel):
    chat_id: int
    text:    str


# ── Routes: health & UI ───────────────────────────────────────────────────────

@app.get("/")
def root() -> dict[str, str]:
    return {"status": "Virtual Office API running", "version": "1.0.0"}


@app.get("/app", response_class=FileResponse, include_in_schema=False)
def serve_ui() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")


# ── Routes: Telegram relay ────────────────────────────────────────────────────

@app.post("/telegram/message")
def telegram_incoming(body: TgIncoming) -> dict[str, str]:
    """Called by the bot when a Telegram user sends a message."""
    if body.chat_id not in tg_chats:
        tg_chats[body.chat_id] = {
            "name":     body.name,
            "username": body.username,
            "messages": [],
        }
    tg_chats[body.chat_id]["messages"].append({
        "from": "user",
        "text": body.text,
        "ts":   datetime.datetime.now().strftime("%H:%M"),
    })
    return {"status": "ok"}


@app.get("/telegram/messages")
def telegram_messages() -> dict[str, Any]:
    """Polled by the UI to show all active Telegram conversations."""
    return {
        "chats": [
            {
                "chat_id":  cid,
                "name":     data["name"],
                "username": data["username"],
                "messages": data["messages"],
            }
            for cid, data in tg_chats.items()
        ]
    }


@app.post("/telegram/reply")
def telegram_reply(body: TgReply) -> dict[str, str]:
    """Called by UI staff to send a reply to a Telegram user."""
    if body.chat_id not in tg_chats:
        raise HTTPException(status_code=404, detail="Chat not found")
    tg_chats[body.chat_id]["messages"].append({
        "from": "staff",
        "text": body.text,
        "ts":   datetime.datetime.now().strftime("%H:%M"),
    })
    tg_reply_queue.append({"chat_id": body.chat_id, "text": body.text})
    return {"status": "queued"}


@app.get("/telegram/pending-replies")
def telegram_pending() -> dict[str, Any]:
    """Polled by the bot to pick up replies queued by staff."""
    pending = tg_reply_queue.copy()
    tg_reply_queue.clear()
    return {"replies": pending}


# ── Routes: logs ──────────────────────────────────────────────────────────────

@app.get("/logs/{log_key}")
def read_log(log_key: str) -> dict[str, str]:
    path = STATE_FILES.get(log_key)
    if path is None:
        raise HTTPException(status_code=404, detail=f"Unknown log key: {log_key!r}")
    if not path.exists():
        return {"content": f"# {log_key}\n\n_No entries yet._", "path": str(path)}
    return {"content": path.read_text(encoding="utf-8"), "path": str(path)}


@app.post("/logs/{log_key}")
def write_log(log_key: str, body: LogWrite) -> dict[str, str]:
    path = STATE_FILES.get(log_key)
    if path is None:
        raise HTTPException(status_code=404, detail=f"Unknown log key: {log_key!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if body.append and path.exists():
        existing = path.read_text(encoding="utf-8")
        path.write_text(existing.rstrip() + "\n\n" + body.content + "\n", encoding="utf-8")
    else:
        path.write_text(body.content, encoding="utf-8")
    return {"status": "written", "path": str(path)}


# ── Routes: quest board ───────────────────────────────────────────────────────

@app.get("/quests")
def get_quests() -> dict[str, Any]:
    path = STATE_FILES["quest_board"]
    if not path.exists():
        return {"content": "", "quests": []}
    content = path.read_text(encoding="utf-8")
    quests: list[dict[str, Any]] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("- [ ]"):
            quests.append({"title": stripped[6:].strip(), "done": False})
        elif stripped.startswith("- [x]"):
            quests.append({"title": stripped[6:].strip(), "done": True})
    return {"content": content, "quests": quests}


@app.post("/quests/add")
def add_quest(body: dict[str, str]) -> dict[str, str]:
    title    = body.get("title", "").strip()
    assignee = body.get("assignee", "Unassigned").strip()
    priority = body.get("priority", "Normal").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Quest title is required")
    path = STATE_FILES["quest_board"]
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n- [ ] **{title}** — Assigned: {assignee} | Priority: {priority} | Added: {timestamp}"
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        path.write_text(existing.rstrip() + entry + "\n", encoding="utf-8")
    else:
        header = "# Quest Board\n\n_Active team assignments and operational tasks._\n"
        path.write_text(header + entry + "\n", encoding="utf-8")
    return {"status": "added", "quest": title}
