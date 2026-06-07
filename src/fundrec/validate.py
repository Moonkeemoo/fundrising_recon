"""Детерміновані валідатори інваріантів Case/Campaign/CreativeAsset (spec §8). Без LLM.

validate_case/validate_campaign/validate_creative повертають список текстових
проблем; порожній список = валідно.
"""
from __future__ import annotations

from . import schema
from .schema import Campaign, Case, CreativeAsset

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


# --- Кампанія ---

_CAMPAIGN_NUMERIC_FIELDS = ("amount_uah", "amount_usd", "reach", "engagement", "spend")


def validate_campaign(c: Campaign) -> list[str]:
    """Перевіряє Campaign на відповідність інваріантам spec §8 (F1)."""
    problems: list[str] = []

    # Інв.1: кожна непорожня числова метрика → provenance
    for f in _CAMPAIGN_NUMERIC_FIELDS:
        val = getattr(c, f)
        if val is not None and f not in c.provenance:
            problems.append(f"missing provenance for {f}")

    # Інв.5: невідʼємні метрики
    for f in _CAMPAIGN_NUMERIC_FIELDS:
        val = getattr(c, f)
        if val is not None and val < 0:
            problems.append(f"negative {f}: {val}")

    # type у словнику
    if c.type not in schema.CAMPAIGN_TYPES:
        problems.append(f"unknown campaign type: {c.type}")

    # channels
    for ch in c.channels:
        if ch not in schema.CHANNELS:
            problems.append(f"unknown channel: {ch}")

    # form_factor
    for ff in c.form_factor:
        if ff not in schema.FORM_FACTORS:
            problems.append(f"unknown form_factor: {ff}")

    # cta_type (якщо задано)
    if c.cta_type is not None and c.cta_type not in schema.CTA_TYPES:
        problems.append(f"unknown cta_type: {c.cta_type}")

    # tone
    for t in c.tone:
        if t not in schema.TONES:
            problems.append(f"unknown tone: {t}")

    # face (якщо задано)
    if c.face is not None and c.face not in schema.FACE_TYPES:
        problems.append(f"unknown face: {c.face}")

    # cadence (якщо задано)
    if c.cadence is not None and c.cadence not in schema.CADENCE:
        problems.append(f"unknown cadence: {c.cadence}")

    # goal category
    category = c.goal.split("/", 1)[0]
    if category not in schema.GOAL_CATEGORIES:
        problems.append(f"unknown goal category: {category}")

    # verification_status
    if c.verification_status not in schema.VERIFICATION:
        problems.append(f"unknown verification_status: {c.verification_status}")

    # year
    if c.year is not None and not (YEAR_MIN <= c.year <= YEAR_MAX):
        problems.append(f"year out of range [{YEAR_MIN},{YEAR_MAX}]: {c.year}")

    return problems


# --- Креативний актив ---

_CREATIVE_NUMERIC_FIELDS = ("views", "likes")


def validate_creative(a: CreativeAsset) -> list[str]:
    """Перевіряє CreativeAsset на відповідність інваріантам spec §8 (F1)."""
    problems: list[str] = []

    # format у словнику
    if a.format not in schema.CREATIVE_FORMATS:
        problems.append(f"unknown creative format: {a.format}")

    # platform у словнику каналів
    if a.platform not in schema.CHANNELS:
        problems.append(f"unknown platform: {a.platform}")

    # числові метрики: provenance + невідʼємність
    for f in _CREATIVE_NUMERIC_FIELDS:
        val = getattr(a, f)
        if val is not None and f not in a.provenance:
            problems.append(f"missing provenance for {f}")
        if val is not None and val < 0:
            problems.append(f"negative {f}: {val}")

    return problems
