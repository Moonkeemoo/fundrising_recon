"""LLM-екстракція raw -> Case / Campaign / CreativeAsset / Partner.

Детерміновані surface-функції (build_prompt / parse_extraction /
build_campaign_prompt / parse_campaign_extraction) — тестуються.
Мережевий виклик ізольований у extract_case / extract_campaign
(_complete=...). Жорстке правило дисципліни: provenance ставиться на
КОЖНЕ непорожнє число; tier береться з джерела; confidence — за tier
(spec §5).
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Callable

from . import schema
from .schema import Campaign, Case, CreativeAsset, Partner, Source

_TIER_CONFIDENCE = {1: 0.95, 2: 0.6, 3: 0.35}
_NUMERIC_FIELDS = ("amount_uah", "amount_usd", "goal_amount")
_CAMPAIGN_NUMERIC_FIELDS = ("amount_uah", "amount_usd", "reach", "engagement", "spend", "assets_count")


def _json_from_text(text: str) -> dict:
    """Витягує JSON-об'єкт з тексту LLM-відповіді.

    Підтримує:
    - Сирий JSON: {"key": ...}
    - Markdown-фенс: ```json\\n{...}\\n```
    - Ведучий/завершальний прозовий текст — беремо перший {...} блок.

    Raises ValueError якщо JSON не знайдено.
    """
    import json  # noqa: PLC0415

    if not text:
        raise ValueError("порожній текст — немає JSON")

    # 1. Спробуємо знайти ```json ... ``` або ``` ... ``` фенс
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))

    # 2. Знаходимо перший {...} блок (ігноруємо зовнішній прозовий текст)
    brace_start = text.find("{")
    if brace_start == -1:
        raise ValueError(f"JSON-об'єкт не знайдено в тексті: {text[:200]!r}")

    # Знаходимо відповідну закриваючу дужку
    depth = 0
    for i, ch in enumerate(text[brace_start:], start=brace_start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[brace_start: i + 1])

    raise ValueError(f"Незакрита JSON-дужка в тексті: {text[:200]!r}")


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


# ---------------------------------------------------------------------------
# Campaign extraction (F3)
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    """Перетворює текст на ASCII-slug (для id партнерів)."""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^\w\s-]", "", ascii_text.lower())
    return re.sub(r"[\s_-]+", "_", slug).strip("_") or "partner"


def build_campaign_prompt(raw: dict[str, Any], source: Source) -> str:
    """Будує промпт для LLM-екстракції Campaign + CreativeAsset[] + Partner[].

    Правила:
    - Не вигадуй чисел: якщо значення немає в джерелі — став null.
    - Класифікуй style-теги ЛИШЕ з дозволених словників.
    - playbook_note — коротка ОПИСОВА нотатка про підхід, НЕ порада.
    - Повертай СТРОГО JSON без зайвого тексту.
    """
    return (
        "Витягни структуровані дані про фандрайзингову кампанію з сирого запису.\n"
        "Поверни СТРОГО JSON (без зайвого тексту) з такою структурою:\n"
        "{\n"
        '  "title": str, "goal": str, "type": str, "channels": [],\n'
        '  "date_start": str|null, "date_end": str|null, "year": int|null,\n'
        '  "form_factor": [], "cta_type": str|null, "tone": [], "face": str|null,\n'
        '  "cadence": str|null, "playbook_note": str,\n'
        '  "amount_uah": float|null, "amount_usd": float|null,\n'
        '  "reach": float|null, "engagement": float|null,\n'
        '  "spend": float|null, "assets_count": float|null,\n'
        '  "case_id": str|null,\n'
        '  "creatives": [{"platform": str, "format": str, "copy_text": str|null,\n'
        '    "hook": str|null, "cta": str|null, "media_url": str|null,\n'
        '    "published": str|null, "impressions_range": str|null,\n'
        '    "spend_range": str|null, "views": float|null, "likes": float|null}],\n'
        '  "partners": [{"name": str, "role": str, "links": []}]\n'
        "}\n\n"
        "Не вигадуй чисел: якщо значення немає в джерелі — став null.\n"
        "playbook_note — ОПИСОВА нотатка про підхід кампанії (не порада).\n\n"
        f"Дозволені campaign type: {sorted(schema.CAMPAIGN_TYPES)}\n"
        f"Дозволені channels: {sorted(schema.CHANNELS)}\n"
        f"Дозволені form_factor: {sorted(schema.FORM_FACTORS)}\n"
        f"Дозволені cta_type: {sorted(schema.CTA_TYPES)}\n"
        f"Дозволені tone: {sorted(schema.TONES)}\n"
        f"Дозволені face: {sorted(schema.FACE_TYPES)}\n"
        f"Дозволені cadence: {sorted(schema.CADENCE)}\n"
        f"Дозволені partner role: {sorted(schema.PARTNER_ROLES)}\n"
        f"Дозволені creative format: {sorted(schema.CREATIVE_FORMATS)}\n"
        f"Дозволені goal category: {sorted(schema.GOAL_CATEGORIES)}\n\n"
        f"Джерело: {source.url} (tier {source.tier})\n"
        f"Сирий запис: {raw}\n"
    )


def parse_campaign_extraction(
    obj: dict[str, Any],
    raw: dict[str, Any],
    source: Source,
    *,
    model: str,
    campaign_id: str,
    actor_id: str,
) -> tuple[Campaign, list[CreativeAsset], list[Partner]]:
    """Будує (Campaign, [CreativeAsset], [Partner]) з відповіді LLM.

    Правила provenance:
    - Кожна ненульова числова метрика кампанії (amount_uah/usd, reach,
      engagement, spend, assets_count) отримує provenance з tier+confidence.
    - Null метрики — без provenance (honest null).
    - views/likes на CreativeAsset: аналогічно.

    Невідомі теги (tone, channels, form_factor) мовчки відфільтровуються
    — зберігаються лише значення з контрольованих словників (spec §8:
    «clean data», validate перевіряє ті самі словники).
    """
    confidence = _TIER_CONFIDENCE.get(source.tier, 0.35)
    provenance: dict[str, Any] = {}

    for f in _CAMPAIGN_NUMERIC_FIELDS:
        val = obj.get(f)
        if val is not None:
            provenance[f] = {
                "source_url": source.url,
                "confidence": confidence,
                "tier": source.tier,
                "note": "",
            }

    # Відфільтровуємо невідомі теги
    channels = [c for c in (obj.get("channels") or []) if c in schema.CHANNELS]
    form_factor = [f for f in (obj.get("form_factor") or []) if f in schema.FORM_FACTORS]
    tone = [t for t in (obj.get("tone") or []) if t in schema.TONES]

    # Partners
    partners: list[Partner] = []
    for p_raw in obj.get("partners") or []:
        name = p_raw.get("name") or ""
        p_id = _slugify(name)
        role = p_raw.get("role") or "partner"
        if role not in schema.PARTNER_ROLES:
            role = "partner"
        partners.append(Partner(
            id=p_id,
            name=name,
            role=role,
            links=list(p_raw.get("links") or []),
        ))

    partner_ids = [p.id for p in partners]

    campaign = Campaign(
        id=campaign_id,
        actor_id=actor_id,
        title=obj.get("title") or raw.get("title") or "",
        goal=obj.get("goal") or "other",
        type=obj.get("type") or "mixed",
        channels=channels,
        date_start=obj.get("date_start"),
        date_end=obj.get("date_end"),
        year=obj.get("year"),
        form_factor=form_factor,
        cta_type=obj.get("cta_type"),
        tone=tone,
        face=obj.get("face"),
        cadence=obj.get("cadence"),
        playbook_note=obj.get("playbook_note"),
        amount_uah=obj.get("amount_uah"),
        amount_usd=obj.get("amount_usd"),
        reach=obj.get("reach"),
        engagement=obj.get("engagement"),
        spend=obj.get("spend"),
        assets_count=obj.get("assets_count"),
        case_id=obj.get("case_id"),
        partner_ids=partner_ids,
        provenance=provenance,
        confidence_overall=confidence if provenance else 0.0,
        verification_status="auto",
        extracted_at=datetime.now(timezone.utc).isoformat(),
        extracted_by_model=model,
    )

    # CreativeAssets
    creatives: list[CreativeAsset] = []
    for i, c_raw in enumerate(obj.get("creatives") or []):
        c_prov: dict[str, Any] = {}
        for metric in ("views", "likes"):
            val = c_raw.get(metric)
            if val is not None:
                c_prov[metric] = {
                    "source_url": source.url,
                    "confidence": confidence,
                    "tier": source.tier,
                    "note": "",
                }
        c_format = c_raw.get("format") or "image"
        if c_format not in schema.CREATIVE_FORMATS:
            c_format = "image"
        c_platform = c_raw.get("platform") or ""
        if c_platform not in schema.CHANNELS:
            c_platform = "web"
        creatives.append(CreativeAsset(
            id=f"{campaign_id}-a{i}",
            campaign_id=campaign_id,
            platform=c_platform,
            format=c_format,
            copy_text=c_raw.get("copy_text"),
            hook=c_raw.get("hook"),
            cta=c_raw.get("cta"),
            media_url=c_raw.get("media_url"),
            published=c_raw.get("published"),
            impressions_range=c_raw.get("impressions_range"),
            spend_range=c_raw.get("spend_range"),
            views=c_raw.get("views"),
            likes=c_raw.get("likes"),
            provenance=c_prov,
        ))

    return campaign, creatives, partners


def extract_campaign(
    raw: dict[str, Any],
    source: Source,
    *,
    campaign_id: str,
    actor_id: str,
    model: str,
    _complete: Callable[[str], dict] | None = None,
) -> tuple[Campaign, list[CreativeAsset], list[Partner]]:
    """Витягує Campaign + CreativeAsset[] + Partner[] з сирого запису.

    _complete — інжектабельна LLM-функція (за замовчуванням _live_complete).
    """
    if _complete is None:
        _complete = _live_complete  # pragma: no cover
    prompt = build_campaign_prompt(raw, source)
    llm_obj = _complete(prompt)
    return parse_campaign_extraction(
        llm_obj, raw, source, model=model, campaign_id=campaign_id, actor_id=actor_id
    )
