"""Драйвер масового збору (dig). Запуск: python scripts/dig.py [scale]

scale: 'mod' (помірний, дефолт) | 'big' (великий).
Використовує:
  - CLI-екстракцію (безкоштовно, підписка) — extract._live_complete за замовч.
  - пагінацію Telegram (pages) + 11 seed-каналів
  - банки Monobank (tier-1 надійні цифри) + jar-дедуп
  - verify=False (критик для tier-3 нічого не змінює)
"""
from __future__ import annotations

import sys

from fundrec.collect import telegram_web
from fundrec.ingest import run_ingest

scale = sys.argv[1] if len(sys.argv) > 1 else "mod"
TG_PAGES = 3 if scale == "mod" else 6
TG_MAX = 40 if scale == "mod" else 250
YT_MAX = 5 if scale == "mod" else 8

YT_THEMES = [
    "FPV дрони для ЗСУ",
    "тактична медицина для військових",
    "евакуаційне авто для ЗСУ",
    "РЕБ та антидрони для ЗСУ",
    "збір на автомобіль для бригади ЗСУ",
    "реабілітація поранених військових",
    "збір на ремонт техніки ЗСУ",
    "гуманітарна допомога цивільним",
]
if scale == "mod":
    YT_THEMES = YT_THEMES[:3]


def tg_collector(theme: str) -> list:
    return telegram_web.search_channels(theme, pages=TG_PAGES, max_results=TG_MAX)


def main() -> None:
    # Telegram (широка тема, щоб ловити всі збори; пагінація вглиб історії)
    print(f"=== TELEGRAM (pages={TG_PAGES}, max={TG_MAX}) ===", flush=True)
    s = run_ingest(
        "збір допомога ЗСУ дрони медицина авто",
        sources=["telegram"],
        max_items=TG_MAX,
        verify=False,
        _components={"collect": {"telegram": tg_collector}},
    )
    print("telegram:", {k: s[k] for k in ("campaigns", "cases", "exported")}, flush=True)

    # YouTube по темах
    for t in YT_THEMES:
        print(f"=== YOUTUBE: {t} ===", flush=True)
        s = run_ingest(t, sources=["youtube"], max_items=YT_MAX, verify=False)
        print("youtube:", {k: s[k] for k in ("campaigns", "cases", "exported")}, flush=True)

    print("=== DIG DONE ===", flush=True)


if __name__ == "__main__":
    main()
