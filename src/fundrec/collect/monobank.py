"""Колектор банок Monobank: дістає публічний JSON банки -> сирий dict.

amount/goal у JSON — у копійках; ділимо на 100 -> гривні. Реальний формат
ендпоінта підтвердити на першому живому запуску (spec §10).
"""
from __future__ import annotations

from typing import Any

JAR_URL = "https://send.monobank.ua/jar/{jar_id}"
JAR_JSON_URL = "https://send.monobank.ua/api/handler"  # підтвердити на живому запуску


def parse_jar(jar_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    amount = payload.get("amount")
    goal = payload.get("goal")
    return {
        "jar_id": jar_id,
        "url": JAR_URL.format(jar_id=jar_id),
        "title": payload.get("title"),
        "amount_uah": (amount / 100.0) if amount is not None else None,
        "goal_amount": (goal / 100.0) if goal is not None else None,
        "currency_raw": payload.get("currency", "UAH"),
    }


def fetch_jar(jar_id: str, *, _client: Any | None = None) -> dict[str, Any]:
    """Дістає банку. _client інжектиться в тестах; інакше httpx."""
    if _client is None:
        import httpx
        _client = httpx.Client(follow_redirects=True)
    resp = _client.get(JAR_URL.format(jar_id=jar_id), timeout=20)
    resp.raise_for_status()
    return parse_jar(jar_id, resp.json())
