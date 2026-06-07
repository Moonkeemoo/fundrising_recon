"""Детермінований парсер сум із текстового вмісту кампаній.

parse_amounts_from_text(text) -> {"amount_uah": float|None, "goal_amount": float|None}
    Витягує суму зібраного та ціль зі звичайного тексту.
    Honest null: повертає None якщо впевненого збігу немає.
    Tier-2: детермінований regex, не LLM.

Підтримувані формати:
  - Суфікси: млн, тис, к/k, млрд (case-insensitive)
  - Десяткові: «2,5 млн» або «2.5 млн»
  - Числа з пробілами/nbsp: «10 000 000 грн»
  - Маркери валюти ₴/грн/uah (опціональні при суфіксі)

Ключові слова зібрано (amount_uah):
  зібрал, зібрано, назбирал, вже, +
Ключові слова ціль (goal_amount):
  ціль, мета, потрібно, збираємо на
"""

from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Regex-блоки
# ---------------------------------------------------------------------------

# Число: ціле або десяткове (крапка або кома), з можливими пробілами/nbsp
# як роздільниками тисяч.
# Приклади: "2,5", "10 000 000", "1.2", "500"
_NUM = r"(\d[\d\s\xa0]*(?:[.,]\d+)?)"

# Множники
_MULT_PAT = re.compile(
    r"^\s*(?:(млрд|mлрд)|(млн|mлн)|(тис(?:яч)?|тыс)|(к|k))\b",
    re.IGNORECASE,
)

# Маркери валюти (опціональні)
_CURRENCY = r"(?:\s*(?:грн|гривень|uah|₴))?"


def _parse_number_and_mult(raw_num: str, rest: str) -> float | None:
    """Перетворює рядок числа + залишок тексту на float із множником.

    raw_num: рядок числа (може містити пробіли як роздільники тисяч і кому/крапку).
    rest:    рядок після числа (де шукаємо множник і валюту).
    """
    # Нормалізуємо число: прибираємо пробіли/nbsp, замінюємо кому на крапку
    cleaned = re.sub(r"[\s\xa0]", "", raw_num).replace(",", ".")
    try:
        value = float(cleaned)
    except ValueError:
        return None

    mult = 1.0
    m = _MULT_PAT.match(rest or "")
    if m:
        if m.group(1):   # млрд
            mult = 1e9
        elif m.group(2):  # млн
            mult = 1e6
        elif m.group(3):  # тис
            mult = 1e3
        elif m.group(4):  # к/k
            mult = 1e3
    elif mult == 1.0:
        # Без суфіксу — приймаємо лише якщо є чіткий маркер валюти одразу після числа
        currency_m = re.match(r"^\s*(?:грн|гривень|uah|₴)", rest or "", re.IGNORECASE)
        if not currency_m:
            # Перевіряємо: число вже включає роздільники тисяч (пробіли)
            # → safe тільки якщо у raw_num є пробіл (тобто велике число)
            if " " not in raw_num.strip() and "\xa0" not in raw_num:
                return None  # маленьке число без контексту — пропускаємо

    return value * mult


# ---------------------------------------------------------------------------
# Патерни для «зібрано» (amount_uah)
# ---------------------------------------------------------------------------

# Ключові слова перед числом:
_RAISED_KW = r"(?:зібрал[аиі]?|зібрано|назбирал[аиі]?|вже|collected|raised)"

# Спеціальний патерн для «+»
_PLUS_PAT = re.compile(
    r"\+\s*" + _NUM + r"\s*" + r"((?:млрд|млн|тис(?:яч)?|к|k)\b)?" + _CURRENCY,
    re.IGNORECASE | re.UNICODE,
)

_RAISED_PAT = re.compile(
    _RAISED_KW + r"[\s:]*" + _NUM + r"\s*(.{0,20})",
    re.IGNORECASE | re.UNICODE,
)

# ---------------------------------------------------------------------------
# Патерни для «ціль» (goal_amount)
# ---------------------------------------------------------------------------

_GOAL_KW = r"(?:ціль|цiль|мета|потрібно|потрiбно|збираємо\s+на|збираємо на)"

_GOAL_PAT = re.compile(
    _GOAL_KW + r"[\s:—\-]*" + _NUM + r"\s*(.{0,20})",
    re.IGNORECASE | re.UNICODE,
)


# ---------------------------------------------------------------------------
# Публічний API
# ---------------------------------------------------------------------------

def parse_amounts_from_text(text: str) -> dict[str, Any]:
    """Витягує суми зібраного та цілі з довільного тексту.

    Повертає:
        {"amount_uah": float|None, "goal_amount": float|None}
    Honest: None якщо не знайдено впевненого збігу.
    Не плутає ціль із зібраним.
    """
    if not text:
        return {"amount_uah": None, "goal_amount": None}

    # Нормалізуємо nbsp → пробіл
    text = text.replace("\xa0", " ")

    amount_uah: float | None = None
    goal_amount: float | None = None

    # --- Шукаємо зібрано ---
    # Пробуємо всі збіги патерну; беремо останній (найбільш специфічний)
    for m in _RAISED_PAT.finditer(text):
        raw_num = m.group(1)
        rest = m.group(2)
        val = _parse_number_and_mult(raw_num, rest)
        if val is not None and val > 0:
            amount_uah = val  # берем останній збіг

    # Також патерн «+»
    for m in _PLUS_PAT.finditer(text):
        raw_num = m.group(1)
        mult_str = m.group(2) or ""
        # Перевіряємо що це справді «+» в контексті суми (не телефон)
        # Контекст: «+» на початку або після пробілу, не всередині числа
        start = m.start()
        if start > 0 and text[start - 1].isdigit():
            continue  # частина телефону
        val = _parse_number_and_mult(raw_num, mult_str + " ")
        if val is not None and val > 0:
            # Перевіряємо що значення виглядає як сума (не мала цифра типу +3 автомобілі)
            if val >= 100 or mult_str:
                amount_uah = val

    # --- Шукаємо ціль ---
    for m in _GOAL_PAT.finditer(text):
        raw_num = m.group(1)
        rest = m.group(2)
        val = _parse_number_and_mult(raw_num, rest)
        if val is not None and val > 0:
            goal_amount = val  # берем останній збіг

    return {"amount_uah": amount_uah, "goal_amount": goal_amount}
