"""Колектор Telegram публічних каналів (Telethon).

parse_message(msg) -> dict — чиста функція, тестується на фікстурі.
fetch_channel(channel, *, api_id, api_hash, limit, _client) -> list[dict]
  — graceful-skip без ключів; Telethon НЕ імпортується на рівні модуля
  (lazy import у _live_client щоб пакет вантажився без telethon).

Збираємо лише ПУБЛІЧНІ канали. Приватні чати — ні (PII-інваріант #6).
"""
from __future__ import annotations

import sys
from typing import Any

_CHANNEL_URL_TMPL = "https://t.me/{channel}/{message_id}"


def parse_message(msg: dict[str, Any]) -> dict[str, Any]:
    """Нормалізує повідомлення Telegram -> dict з провенансом.

    Honest null: views/forwards/reactions = None якщо відсутні.
    """
    channel: str = msg.get("channel", "")
    message_id: int = msg.get("id", 0)

    return {
        "source_url": _CHANNEL_URL_TMPL.format(channel=channel, message_id=message_id),
        "platform": "telegram",
        "channel": channel,
        "message_id": message_id,
        "text": msg.get("message"),
        "date": msg.get("date"),
        "views": msg.get("views"),
        "forwards": msg.get("forwards"),
        "reactions": msg.get("reactions"),
    }


def _live_client(api_id: str, api_hash: str):  # pragma: no cover
    """Створює реальний Telethon клієнт (lazy import).

    Викликається ТІЛЬКИ при живому прогоні. Не запускайте в тестах.
    Потребує разової інтерактивної авторизації (файл сесії data/.telegram.session).
    """
    from telethon.sync import TelegramClient  # noqa: PLC0415  # pragma: no cover

    from fundrec.config import DATA_DIR  # noqa: PLC0415  # pragma: no cover

    session_file = str(DATA_DIR / ".telegram.session")  # pragma: no cover
    return TelegramClient(session_file, int(api_id), api_hash)  # pragma: no cover


def fetch_channel(
    channel: str,
    *,
    api_id: str | None = None,
    api_hash: str | None = None,
    limit: int = 50,
    _client: Any | None = None,
) -> list[dict[str, Any]]:
    """Дістає повідомлення з публічного Telegram-каналу.

    Якщо api_id або api_hash не задані — graceful-skip: [] + лог.
    _client інжектиться в тестах (має метод .get_messages(channel, limit)).
    """
    import os  # pylint: disable=import-outside-toplevel

    if api_id is None:
        api_id = os.environ.get("TELEGRAM_API_ID", "")
    if api_hash is None:
        api_hash = os.environ.get("TELEGRAM_API_HASH", "")

    if not api_id or not api_hash:
        print("telegram: нема ключів (TELEGRAM_API_ID/HASH), пропускаю", file=sys.stderr)
        return []

    if _client is None:
        _client = _live_client(api_id, api_hash)  # pragma: no cover

    messages = _client.get_messages(channel, limit=limit)
    return [parse_message(msg) for msg in messages]
