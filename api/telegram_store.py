from __future__ import annotations

import json
import os
from typing import Any

CHATS_KEY = "vo:tg:chats"
QUEUE_KEY = "vo:tg:reply_queue"

_mem_chats: dict[int, dict[str, Any]] = {}
_mem_queue: list[dict[str, Any]] = []


def storage_backend() -> str:
    return "redis" if _redis() is not None else "memory"


def _redis() -> Any | None:
    url = os.getenv("KV_REST_API_URL") or os.getenv("UPSTASH_REDIS_REST_URL")
    token = os.getenv("KV_REST_API_TOKEN") or os.getenv("UPSTASH_REDIS_REST_TOKEN")
    if not url or not token:
        return None
    from upstash_redis import Redis

    return Redis(url=url, token=token)


def _decode_chats(raw: str | bytes | None) -> dict[int, dict[str, Any]]:
    if not raw:
        return {}
    data = json.loads(raw)
    return {int(k): v for k, v in data.items()}


def load_chats() -> dict[int, dict[str, Any]]:
    client = _redis()
    if client is None:
        return _mem_chats
    return _decode_chats(client.get(CHATS_KEY))


def save_chats(chats: dict[int, dict[str, Any]]) -> None:
    client = _redis()
    if client is None:
        _mem_chats.clear()
        _mem_chats.update(chats)
        return
    client.set(CHATS_KEY, json.dumps({str(k): v for k, v in chats.items()}))


def add_incoming_message(
    chat_id: int,
    name: str,
    username: str,
    text: str,
    ts: str,
) -> None:
    chats = load_chats()
    if chat_id not in chats:
        chats[chat_id] = {"name": name, "username": username, "messages": []}
    chats[chat_id]["messages"].append({"from": "user", "text": text, "ts": ts})
    save_chats(chats)


def add_staff_reply(chat_id: int, text: str, ts: str) -> None:
    chats = load_chats()
    if chat_id not in chats:
        raise KeyError(chat_id)
    chats[chat_id]["messages"].append({"from": "staff", "text": text, "ts": ts})
    save_chats(chats)
    enqueue_reply({"chat_id": chat_id, "text": text})


def enqueue_reply(item: dict[str, Any]) -> None:
    client = _redis()
    if client is None:
        _mem_queue.append(item)
        return
    client.rpush(QUEUE_KEY, json.dumps(item))


def drain_reply_queue() -> list[dict[str, Any]]:
    client = _redis()
    if client is None:
        pending = _mem_queue.copy()
        _mem_queue.clear()
        return pending

    raw_items = client.lrange(QUEUE_KEY, 0, -1)
    if raw_items:
        client.delete(QUEUE_KEY)
    return [json.loads(item) for item in raw_items]
