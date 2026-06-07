"""Шляхи, моделі, env. Єдине джерело конфігурації."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
SEEDS_DIR = DATA_DIR / "seeds"
DB_PATH = DATA_DIR / "fundrec.sqlite"
CASES_JSON = DATA_DIR / "cases.json"

# Генератор/екстрактор — Claude Agent SDK на підписці (Opus). Критик — прямий API (Sonnet).
EXTRACT_MODEL = os.environ.get("FUNDREC_EXTRACT_MODEL", "claude-opus-4-8")
JUDGE_MODEL = os.environ.get("FUNDREC_JUDGE_MODEL", "claude-sonnet-4-6")
# Навмисно НЕ ANTHROPIC_API_KEY (інакше SDK перемкне екстрактор на платний API).
CRITIC_API_KEY = os.environ.get("FUNDREC_CRITIC_API_KEY", "")
