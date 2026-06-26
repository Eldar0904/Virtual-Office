from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ── Constants ─────────────────────────────────────────────────────────────────

OLLAMA_BASE = "http://localhost:11434/v1"
CHAT_MODEL = "llama3.1:8b"

BASE_DIR = Path(__file__).parent.parent

STATE_FILES: dict[str, Path] = {
    "logistics_log": BASE_DIR / "daily-ops" / "logistics_log.md",
    "system_status": BASE_DIR / "tech-core" / "system_status.md",
    "quest_board":   BASE_DIR / "daily-ops" / "quest_board.md",
    "hr_log":        BASE_DIR / "administration" / "hr_log.md",
}

AGENT_PERSONAS: dict[str, str] = {
    "Chief's Assistant": (
        "You are the Chief's Assistant at a professional virtual office. "
        "You handle high-level coordination, executive summaries, meeting preparation, "
        "and strategic oversight. Be formal, concise, and proactive."
    ),
    "Logistics": (
        "You are the Logistics Specialist at a virtual office. "
        "You manage resource tracking, task routing, operational workflows, "
        "and delivery coordination. Be systematic and detail-oriented."
    ),
    "Front Desk": (
        "You are the Front Desk Coordinator at a virtual office. "
        "You handle scheduling, visitor management, communications routing, "
        "and daily briefings. Be friendly, organised, and responsive."
    ),
    "HR": (
        "You are the HR Manager at a virtual office. "
        "You manage personnel matters, team welfare, onboarding, "
        "and policy compliance. Be empathetic, professional, and supportive."
    ),
    "SysAdmin": (
        "You are the System Administrator at a virtual office. "
        "You oversee technical infrastructure, system health monitoring, "
        "debugging, and security. Be technical, precise, and methodical."
    ),
}

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Virtual Office API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Models ────────────────────────────────────────────────────────────────────

class ChatPayload(BaseModel):
    agent: str
    message: str
    history: list[dict[str, str]] = []


class LogWrite(BaseModel):
    content: str
    append: bool = True


# ── Routes: health ────────────────────────────────────────────────────────────

@app.get("/")
def root() -> dict[str, str]:
    return {"status": "Virtual Office API running", "version": "1.0.0"}


# ── Routes: chat ──────────────────────────────────────────────────────────────

@app.post("/chat/stream")
async def chat_stream(payload: ChatPayload) -> StreamingResponse:
    """Stream token-by-token responses from the local Ollama instance."""
    system_prompt = AGENT_PERSONAS.get(
        payload.agent, AGENT_PERSONAS["Chief's Assistant"]
    )

    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    # Keep last 10 turns for context window hygiene
    messages.extend(payload.history[-10:])
    messages.append({"role": "user", "content": payload.message})

    async def token_generator():
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    f"{OLLAMA_BASE}/chat/completions",
                    json={"model": CHAT_MODEL, "messages": messages, "stream": True},
                    headers={"Content-Type": "application/json"},
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        raw = line[6:]
                        if raw.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(raw)
                            delta = chunk["choices"][0]["delta"].get("content", "")
                            if delta:
                                yield delta
                        except (json.JSONDecodeError, KeyError):
                            continue
        except httpx.ConnectError:
            yield "\n\n⚠️ Ollama is not reachable at localhost:11434. Run `ollama serve` to start it."
        except httpx.HTTPStatusError as exc:
            yield f"\n\n⚠️ Ollama returned HTTP {exc.response.status_code}."

    return StreamingResponse(token_generator(), media_type="text/plain")


@app.post("/chat")
async def chat_blocking(payload: ChatPayload) -> dict[str, str]:
    """Non-streaming fallback for single-shot responses."""
    system_prompt = AGENT_PERSONAS.get(
        payload.agent, AGENT_PERSONAS["Chief's Assistant"]
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    messages.extend(payload.history[-10:])
    messages.append({"role": "user", "content": payload.message})

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{OLLAMA_BASE}/chat/completions",
                json={"model": CHAT_MODEL, "messages": messages, "stream": False},
            )
            r.raise_for_status()
            content: str = r.json()["choices"][0]["message"]["content"]
            return {"response": content}
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Ollama unreachable at localhost:11434")


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
    title = body.get("title", "").strip()
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
