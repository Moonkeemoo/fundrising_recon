"""LLM-екстракція raw -> Case.

Детерміновані surface-функції (build_prompt / parse_extraction) — тестуються.
Мережевий виклик ізольований у extract_case(_complete=...). Жорстке правило
дисципліни: provenance ставиться на КОЖНЕ непорожнє число; tier береться з
джерела; confidence — за tier (spec §5).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from . import schema
from .schema import Case, Source

_TIER_CONFIDENCE = {1: 0.95, 2: 0.6, 3: 0.35}
_NUMERIC_FIELDS = ("amount_uah", "amount_usd", "goal_amount")


def build_prompt(raw: dict[str, Any], source: Source) -> str:
    return (
        "Витягни структуровані дані про збір коштів із сирого запису джерела.\n"
        "Поверни СТРОГО JSON з полями: title, goal, style[], method[], year, "
        "date_start, date_end, amount_uah, amount_usd, goal_amount, currency_raw.\n"
        "Не вигадуй чисел: якщо значення немає в джерелі — став null.\n\n"
        f"Дозволені goal (category або category/subcategory): {sorted(schema.GOAL_CATEGORIES)}\n"
        f"Дозволені style: {sorted(schema.STYLE_TAGS)}\n"
        f"Дозволені method: {sorted(schema.METHOD_TAGS)}\n\n"
        f"Джерело: {source.url} (tier {source.tier})\n"
        f"Сирий запис: {raw}\n"
    )


def parse_extraction(
    llm_obj: dict[str, Any], raw: dict[str, Any], source: Source,
    *, model: str, case_id: str, actor_id: str,
) -> Case:
    confidence = _TIER_CONFIDENCE.get(source.tier, 0.35)
    provenance: dict[str, dict] = {}
    for f in _NUMERIC_FIELDS:
        if llm_obj.get(f) is not None:
            provenance[f] = {
                "source_url": source.url, "confidence": confidence,
                "tier": source.tier, "note": "",
            }
    return Case(
        id=case_id,
        title=llm_obj.get("title") or raw.get("title") or "",
        actor_id=actor_id,
        url=source.url,
        goal=llm_obj.get("goal") or "other",
        style=list(llm_obj.get("style") or []),
        method=list(llm_obj.get("method") or []),
        date_start=llm_obj.get("date_start"),
        date_end=llm_obj.get("date_end"),
        year=llm_obj.get("year"),
        amount_uah=llm_obj.get("amount_uah"),
        amount_usd=llm_obj.get("amount_usd"),
        goal_amount=llm_obj.get("goal_amount"),
        currency_raw=llm_obj.get("currency_raw"),
        provenance=provenance,
        confidence_overall=confidence if provenance else 0.0,
        verification_status="auto",
        extracted_at=datetime.now(timezone.utc).isoformat(),
        extracted_by_model=model,
    )


def extract_case(
    raw: dict[str, Any], source: Source,
    *, case_id: str, actor_id: str, model: str,
    _complete: Callable[[str], dict] | None = None,
) -> Case:
    if _complete is None:
        _complete = _live_complete
    prompt = build_prompt(raw, source)
    llm_obj = _complete(prompt)
    return parse_extraction(llm_obj, raw, source, model=model, case_id=case_id, actor_id=actor_id)


def _live_complete(prompt: str) -> dict:  # pragma: no cover - мережа/LLM
    """Живий виклик через Claude Agent SDK (підписка). Повертає dict із JSON."""
    import json

    from claude_agent_sdk import query  # type: ignore

    chunks: list[str] = []
    for msg in query(prompt=prompt):
        text = getattr(msg, "text", None)
        if text:
            chunks.append(text)
    return json.loads("".join(chunks))
