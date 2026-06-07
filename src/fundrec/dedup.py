"""Дедуплікація і злиття кейсів: dedup_key + merge_cases.

dedup_key(case) -> str:
  Нормалізований ключ: host+path URL (без query/fragment) або slug actor_id+title.

merge_cases(cases) -> list[Case]:
  Кейси з однаковим ключем зливаються:
  - числові поля: перемагає провенанс з найвищим tier (1 > 2 > 3);
  - style / method: union;
  - провенанс: зберігається переможець кожного поля;
  - date_start: найраніша; date_end: найпізніша;
  - confidence_overall: max confidence збережених числових полів.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

from .schema import Case

# Числові поля, які конкурують за провенанс
_NUMERIC_FIELDS = ("amount_uah", "amount_usd", "goal_amount")


def _slugify(text: str) -> str:
    """Перетворює текст на ASCII-slug (для fallback-ключа)."""
    # Нормалізуємо Unicode → ASCII
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^\w\s-]", "", ascii_text.lower())
    return re.sub(r"[\s_-]+", "_", slug).strip("_")


def dedup_key(case: Case) -> str:
    """Повертає нормалізований ключ кейсу для дедуплікації.

    Пріоритет: URL host+path (без query/fragment, без trailing slash).
    Fallback: slug з actor_id + title (коли URL порожній або нераспізнається).
    """
    url = (case.url or "").strip()
    if url:
        try:
            parsed = urlparse(url)
            host = parsed.hostname or ""
            path = parsed.path.rstrip("/")
            if host:
                return f"{host}{path}".lower()
        except Exception:
            pass

    # Fallback: slug з actor_id + title
    return _slugify(f"{case.actor_id}_{case.title}")


def _tier_of(prov: dict, field: str) -> int:
    """Повертає tier провенансу поля або 99 якщо нема."""
    entry = prov.get(field)
    if isinstance(entry, dict):
        return int(entry.get("tier", 99))
    return 99


def _confidence_of(prov: dict, field: str) -> float:
    """Повертає confidence провенансу поля або 0.0 якщо нема."""
    entry = prov.get(field)
    if isinstance(entry, dict):
        return float(entry.get("confidence", 0.0))
    return 0.0


def _merge_two(a: Case, b: Case) -> Case:
    """Зливає два кейси в один. Мутує перший, повертає новий об'єкт."""
    # Числові поля: перемагає найвищий tier (менше число = вищий tier)
    new_provenance: dict = dict(a.provenance)
    new_values: dict = {}

    for field in _NUMERIC_FIELDS:
        tier_a = _tier_of(a.provenance, field)
        tier_b = _tier_of(b.provenance, field)
        val_a = getattr(a, field)
        val_b = getattr(b, field)

        # Вибираємо переможця: менший tier (1 < 2 < 3) перемагає
        if val_b is not None and (val_a is None or tier_b < tier_a):
            new_values[field] = val_b
            new_provenance[field] = b.provenance[field]
        elif val_a is not None:
            new_values[field] = val_a
            if field in a.provenance:
                new_provenance[field] = a.provenance[field]
        else:
            new_values[field] = None

        # Якщо tier однаковий — беремо значення з більшим confidence
        if val_a is not None and val_b is not None and tier_a == tier_b:
            conf_a = _confidence_of(a.provenance, field)
            conf_b = _confidence_of(b.provenance, field)
            if conf_b > conf_a:
                new_values[field] = val_b
                if field in b.provenance:
                    new_provenance[field] = b.provenance[field]

    # style / method: union (зберігаємо порядок)
    merged_style = list(dict.fromkeys(a.style + b.style))
    merged_method = list(dict.fromkeys(a.method + b.method))

    # Дати: найраніша date_start, найпізніша date_end
    dates_start = [d for d in (a.date_start, b.date_start) if d]
    dates_end = [d for d in (a.date_end, b.date_end) if d]
    merged_date_start = min(dates_start) if dates_start else None
    merged_date_end = max(dates_end) if dates_end else None

    # confidence_overall: max confidence збережених числових полів
    confidences = [
        _confidence_of(new_provenance, f)
        for f in _NUMERIC_FIELDS
        if new_values.get(f) is not None and f in new_provenance
    ]
    new_confidence = max(confidences) if confidences else max(a.confidence_overall, b.confidence_overall)

    # id: зберігаємо перший (або менший за алфавітом для детермінізму)
    merged_id = a.id if a.id <= b.id else b.id

    return Case(
        id=merged_id,
        title=a.title or b.title,
        actor_id=a.actor_id or b.actor_id,
        url=a.url or b.url,
        goal=a.goal or b.goal,
        style=merged_style,
        method=merged_method,
        date_start=merged_date_start,
        date_end=merged_date_end,
        year=a.year or b.year,
        amount_uah=new_values.get("amount_uah"),
        amount_usd=new_values.get("amount_usd"),
        goal_amount=new_values.get("goal_amount"),
        currency_raw=a.currency_raw or b.currency_raw,
        provenance=new_provenance,
        confidence_overall=new_confidence,
        verification_status=a.verification_status,
        extracted_at=a.extracted_at or b.extracted_at,
        extracted_by_model=a.extracted_by_model or b.extracted_by_model,
    )


def merge_cases(cases: list[Case]) -> list[Case]:
    """Дедуплікує і зливає кейси за ключем dedup_key.

    Для кожного унікального ключа послідовно зливає всі кейси з цим ключем.
    """
    if not cases:
        return []

    # Групуємо за ключем (зберігаємо порядок першого входження)
    groups: dict[str, list[Case]] = {}
    for c in cases:
        key = dedup_key(c)
        groups.setdefault(key, []).append(c)

    result: list[Case] = []
    for group in groups.values():
        merged = group[0]
        for other in group[1:]:
            merged = _merge_two(merged, other)
        result.append(merged)

    return result
