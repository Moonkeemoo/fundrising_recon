"""Шляхи, моделі, env. Єдине джерело конфігурації.

Використання:
    python -m fundrec.config --check-keys   # показати статус ключів (значення НЕ друкуються)
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
SEEDS_DIR = DATA_DIR / "seeds"
DB_PATH = DATA_DIR / "fundrec.sqlite"
CASES_JSON = DATA_DIR / "cases.json"


# ---------------------------------------------------------------------------
# .env — завантажуємо до зчитування ключів (якщо є)
# ---------------------------------------------------------------------------

def _load_dotenv() -> None:
    """Завантажує KEY=VALUE з ROOT/.env (не перебиває вже задані змінні).

    Без додаткових залежностей. Пропускає коментарі (#) та порожні рядки.
    """
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


# Автозавантаження .env можна вимкнути (тести роблять це для герметичності).
if os.environ.get("FUNDREC_SKIP_DOTENV") != "1":
    _load_dotenv()

# ---------------------------------------------------------------------------
# Моделі
# ---------------------------------------------------------------------------

# Генератор/екстрактор — Claude Agent SDK на підписці (Opus). Критик — прямий API (Sonnet).
EXTRACT_MODEL = os.environ.get("FUNDREC_EXTRACT_MODEL", "claude-opus-4-8")
JUDGE_MODEL = os.environ.get("FUNDREC_JUDGE_MODEL", "claude-sonnet-4-6")
# Навмисно НЕ ANTHROPIC_API_KEY (інакше SDK перемкне екстрактор на платний API).
CRITIC_API_KEY = os.environ.get("FUNDREC_CRITIC_API_KEY", "")

# ---------------------------------------------------------------------------
# API-ключі джерел F2
# ---------------------------------------------------------------------------

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
TELEGRAM_API_ID = os.environ.get("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH", "")
META_ADS_TOKEN = os.environ.get("META_ADS_TOKEN", "")

# ---------------------------------------------------------------------------
# Статус ключів
# ---------------------------------------------------------------------------

_ALL_KEYS = (
    "YOUTUBE_API_KEY",
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "META_ADS_TOKEN",
    "FUNDREC_CRITIC_API_KEY",
)


def keys_status() -> dict[str, bool]:
    """Повертає dict {ім'я_ключа: bool} — задано чи ні. Значення НІКОЛИ не включаються."""
    return {k: bool(os.environ.get(k, "")) for k in _ALL_KEYS}


def check_keys() -> None:
    """Друкує таблицю статусу ключів. Значення ніколи не виводяться."""
    import sys

    status = keys_status()
    out = sys.stdout
    out.write("fundrec API keys status:\n")
    out.write(f"  {'Key':<30} {'Status'}\n")
    out.write(f"  {'-'*30} {'-'*10}\n")
    for key, is_set in status.items():
        label = "zadano" if is_set else "ne zadano"
        out.write(f"  {key:<30} {label}\n")
    out.flush()


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="fundrec config util")
    parser.add_argument("--check-keys", action="store_true", help="Показати статус ключів")
    args = parser.parse_args()

    if args.check_keys:
        check_keys()
