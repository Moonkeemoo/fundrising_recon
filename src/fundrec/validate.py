"""Детерміновані валідатори інваріантів Case (spec §8). Без LLM.

validate_case повертає список текстових проблем; порожній список = валідно.
"""
from __future__ import annotations

from . import schema
from .schema import Case

YEAR_MIN, YEAR_MAX = 2022, 2026
_NUMERIC_FIELDS = ("amount_uah", "amount_usd", "goal_amount")


def validate_case(c: Case) -> list[str]:
    problems: list[str] = []

    # Інв.1: кожне непорожнє число має provenance
    for f in _NUMERIC_FIELDS:
        val = getattr(c, f)
        if val is not None and f not in c.provenance:
            problems.append(f"missing provenance for {f}")

    # Інв.5/числа: невідʼємні суми
    for f in _NUMERIC_FIELDS:
        val = getattr(c, f)
        if val is not None and val < 0:
            problems.append(f"negative {f}: {val}")

    # рік у межах війни
    if c.year is not None and not (YEAR_MIN <= c.year <= YEAR_MAX):
        problems.append(f"year out of range [{YEAR_MIN},{YEAR_MAX}]: {c.year}")

    # ціль: category[/subcategory], category у словнику
    category = c.goal.split("/", 1)[0]
    if category not in schema.GOAL_CATEGORIES:
        problems.append(f"unknown goal category: {category}")

    # стилі/способи у словниках
    for tag in c.style:
        if tag not in schema.STYLE_TAGS:
            problems.append(f"unknown style tag: {tag}")
    for tag in c.method:
        if tag not in schema.METHOD_TAGS:
            problems.append(f"unknown method tag: {tag}")

    # verification у словнику
    if c.verification_status not in schema.VERIFICATION:
        problems.append(f"unknown verification_status: {c.verification_status}")

    return problems
