"""Герметичність тестів: НЕ читаємо реальний .env і не залежимо від ключів у
оточенні розробника. Інакше наявність ключів у .env ламає graceful-skip тести.

Виконується до імпорту fundrec.config у тест-модулях (pytest вантажить conftest
першим), тож автозавантаження .env вимкнеться, а ключі не «протечуть» у тести.
"""
from __future__ import annotations

import os

import pytest

os.environ["FUNDREC_SKIP_DOTENV"] = "1"
for _k in (
    "YOUTUBE_API_KEY", "TELEGRAM_API_ID", "TELEGRAM_API_HASH",
    "META_ADS_TOKEN", "FUNDREC_CRITIC_API_KEY",
):
    os.environ.pop(_k, None)


# ---------------------------------------------------------------------------
# Network guard — блокує будь-які справжні HTTP-виклики у тестах.
# Якщо тест не ін'єктує fake-клієнт і все одно доходить до httpx —
# падає з чітким RuntimeError, а не зі "з'єднанням відхилено".
# ---------------------------------------------------------------------------

def _blocked(*args, **kwargs):  # noqa: ARG001
    raise RuntimeError(
        "network blocked in tests — inject a fake client"
    )


@pytest.fixture(autouse=True)
def _block_real_network(monkeypatch):
    """Блокує реальні мережеві виклики через httpx у кожному тесті."""
    import httpx  # noqa: PLC0415

    monkeypatch.setattr(httpx.Client, "send", _blocked)
    monkeypatch.setattr(httpx, "get", _blocked)
    monkeypatch.setattr(httpx, "post", _blocked)
    monkeypatch.setattr(httpx, "request", _blocked)
