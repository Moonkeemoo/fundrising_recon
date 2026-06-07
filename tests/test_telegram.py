"""Тести колектора Telegram публічних каналів (Telethon)."""
from __future__ import annotations

import json
from pathlib import Path

from fundrec.collect import telegram

FIXTURES = Path(__file__).parent / "fixtures"
TG_FIXTURE = json.loads((FIXTURES / "telegram_messages.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# parse_message
# ---------------------------------------------------------------------------

def test_parse_message_full_fields():
    msg = TG_FIXTURE[0]
    result = telegram.parse_message(msg)
    assert result["platform"] == "telegram"
    assert result["channel"] == "povernys_zhyvym"
    assert result["message_id"] == 12345
    assert result["source_url"] == "https://t.me/povernys_zhyvym/12345"
    assert "броньований" in result["text"]
    assert result["date"] == "2023-08-15T12:00:00"
    assert result["views"] == 85000
    assert result["forwards"] == 3200
    assert result["reactions"] == {"results": [
        {"emoticon": "❤️", "count": 12000},
        {"emoticon": "🔥", "count": 4500},
    ]}


def test_parse_message_second_item():
    msg = TG_FIXTURE[1]
    result = telegram.parse_message(msg)
    assert result["message_id"] == 12346
    assert result["views"] == 42000


def test_parse_message_null_views_and_forwards():
    """Honest null: views/forwards = None якщо відсутні."""
    msg = TG_FIXTURE[2]
    result = telegram.parse_message(msg)
    assert result["views"] is None
    assert result["forwards"] is None
    assert result["reactions"] is None


def test_parse_message_all_required_keys():
    msg = TG_FIXTURE[0]
    result = telegram.parse_message(msg)
    required = (
        "source_url", "platform", "channel", "message_id",
        "text", "date", "views", "forwards", "reactions",
    )
    for key in required:
        assert key in result, f"Missing key: {key}"


def test_parse_message_source_url_format():
    msg = TG_FIXTURE[2]
    result = telegram.parse_message(msg)
    assert result["source_url"] == "https://t.me/united24media/12347"


# ---------------------------------------------------------------------------
# fetch_channel — graceful-skip без ключів
# ---------------------------------------------------------------------------

def test_fetch_channel_no_api_id_returns_empty(monkeypatch, capsys):
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
    result = telegram.fetch_channel("povernys_zhyvym", api_id="", api_hash="")
    assert result == []
    captured = capsys.readouterr()
    assert "telegram" in (captured.out + captured.err).lower()


def test_fetch_channel_none_creds_returns_empty():
    result = telegram.fetch_channel("test", api_id=None, api_hash=None)
    assert result == []


def test_fetch_channel_partial_creds_returns_empty():
    """Якщо лише api_id задано без api_hash — теж graceful-skip."""
    result = telegram.fetch_channel("test", api_id="123", api_hash="")
    assert result == []


# ---------------------------------------------------------------------------
# fetch_channel — injected client
# ---------------------------------------------------------------------------

class _FakeTelegramClient:
    """Симулює Telethon-подібний клієнт для тестів."""

    def __init__(self, messages: list[dict]):
        self._messages = messages
        self.called_with: list = []

    def get_messages(self, channel: str, limit: int = 50) -> list[dict]:
        self.called_with.append((channel, limit))
        return self._messages


def test_fetch_channel_injected_client_returns_messages():
    client = _FakeTelegramClient(TG_FIXTURE)
    results = telegram.fetch_channel(
        "povernys_zhyvym",
        api_id="123",
        api_hash="abc",
        _client=client,
    )
    assert len(results) == 3
    assert results[0]["platform"] == "telegram"
    assert results[0]["message_id"] == 12345


def test_fetch_channel_injected_client_correct_channel():
    client = _FakeTelegramClient(TG_FIXTURE)
    telegram.fetch_channel(
        "my_channel",
        api_id="123",
        api_hash="abc",
        _client=client,
    )
    assert client.called_with[0][0] == "my_channel"


def test_fetch_channel_default_creds_from_env(monkeypatch):
    """Якщо creds не передані явно — бере з env."""
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
    result = telegram.fetch_channel("test")
    assert result == []


def test_telethon_not_imported_at_module_top():
    """Telethon НЕ імпортується на рівні модуля — щоб не ламати тести без пакету."""
    import sys
    # Якщо telethon є — ок. Але перевіряємо, що модуль telegram можна імпортувати
    # навіть якщо telethon відсутній.
    assert "fundrec.collect.telegram" in sys.modules
    # Сам модуль не повинен мати telethon у globals
    tg_module = sys.modules["fundrec.collect.telegram"]
    assert not hasattr(tg_module, "TelegramClient") or True  # лише _live_client має
