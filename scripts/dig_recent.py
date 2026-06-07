"""Свіжий прогін: найновіші пости (page 1) по ВСІХ каналах із
data/seeds/telegram_channels.txt → останні ~30 днів зборів.

Релевант-гейт у ingest відсіює не-збори ще до LLM-екстракції (економія).
Екстракція безкоштовна (CLI). Запуск:
    FUNDREC_CRITIC_API_KEY="" python scripts/dig_recent.py [max_items]
"""
from __future__ import annotations

import sys
from pathlib import Path

from fundrec.collect import telegram_web
from fundrec.ingest import run_ingest

ROOT = Path(__file__).resolve().parents[1]
CH_FILE = ROOT / "data" / "seeds" / "telegram_channels.txt"

max_items = int(sys.argv[1]) if len(sys.argv) > 1 else 150


def main() -> None:
    channels = [c.strip() for c in CH_FILE.read_text(encoding="utf-8").splitlines() if c.strip()]
    print(f"=== каналів: {len(channels)} | max_items={max_items} ===", flush=True)

    def tg(theme: str) -> list:
        # page 1 = найновіші пости; багато постів на канал
        return telegram_web.search_channels(
            theme, channels=channels, pages=1, max_results=max_items * 3
        )

    s = run_ingest(
        "збір допомога ЗСУ дрони медицина авто",
        sources=["telegram"],
        max_items=max_items,
        verify=False,
        _components={"collect": {"telegram": tg}},
    )
    print(
        "telegram:",
        {k: s.get(k) for k in ("campaigns", "cases", "skipped_irrelevant", "exported")},
        flush=True,
    )
    print("=== RECENT DIG DONE ===", flush=True)


if __name__ == "__main__":
    main()
