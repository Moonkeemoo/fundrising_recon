"""LLM-критик на прямому Anthropic API (окрема модель, temp=0).

Тестована поверхня: build_critic_prompt / parse_verdict / critique_case /
build_campaign_critic_prompt / critique_campaign.
Мережевий виклик ізольовано у _live_judge (# pragma: no cover).
"""

from __future__ import annotations

from typing import Callable

from . import config
from .schema import Campaign, Case


def build_critic_prompt(case: Case) -> str:
    """Будує промпт для судді-критика.

    Просить суддю оцінити, чи джерела у провенансі кейсу правдоподібно
    підтверджують amount_uah / goal_amount і типізацію (goal/style/method).
    Вимагає СТРОГИЙ JSON: {"supported": bool, "confidence": 0..1, "reason": "..."}.
    """
    source_urls = sorted(
        {
            entry["source_url"]
            for entry in case.provenance.values()
            if isinstance(entry, dict) and entry.get("source_url")
        }
    )
    return (
        "Ти — незалежний критик-валідатор кейсів фандрайзингу.\n"
        "Оціни, чи цитовані джерела реально підтверджують вказану суму і типізацію кейсу.\n\n"
        f"Заголовок: {case.title}\n"
        f"Ціль (goal): {case.goal}\n"
        f"Стилі: {case.style}\n"
        f"Методи: {case.method}\n"
        f"amount_uah: {case.amount_uah}\n"
        f"goal_amount: {case.goal_amount}\n"
        f"Джерела провенансу: {source_urls}\n\n"
        "Поверни СТРОГО JSON (без зайвого тексту):\n"
        '{"supported": true|false, "confidence": 0.0..1.0, "reason": "<коротко українською>"}\n'
    )


def parse_verdict(obj: dict) -> dict:
    """Нормалізує відповідь судді → {"supported": bool, "confidence": float, "reason": str}."""
    supported = bool(obj.get("supported", False))
    try:
        confidence = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    reason = str(obj.get("reason", ""))
    return {"supported": supported, "confidence": confidence, "reason": reason}


def critique_case(
    case: Case,
    *,
    base_status: str,
    _judge: Callable[[str], dict] | None = None,
) -> tuple[str, str]:
    """Запускає суддю і повертає (verification_status, reason).

    Upgrade rules:
    - base_status == "conflict" → always stays "conflict" (never downgrade).
    - base_status == "cross-checked" AND supported AND confidence >= 0.7 → "verified".
    - base_status == "cross-checked" AND NOT supported → keep "cross-checked", reason explains doubt.
    - base_status == "auto" → judge cannot upgrade (only cross-checked eligible); pass through.
    """
    if _judge is None:
        _judge = _live_judge  # pragma: no cover

    if base_status == "conflict":
        return "conflict", ""

    prompt = build_critic_prompt(case)
    raw = _judge(prompt)
    verdict = parse_verdict(raw)

    if base_status == "cross-checked":
        if verdict["supported"] and verdict["confidence"] >= 0.7:
            return "verified", verdict["reason"]
        # unsupported or low confidence: keep base, note the doubt
        reason = verdict["reason"] if verdict["reason"] else "суддя не підтвердив"
        return base_status, reason

    # auto (or any other unrecognized base): pass through unchanged
    return base_status, verdict["reason"]


def _live_judge(prompt: str) -> dict:  # pragma: no cover
    """Живий виклик Anthropic API (Sonnet, temp=0). Не тестується."""
    import anthropic

    client = anthropic.Anthropic(api_key=config.CRITIC_API_KEY)
    message = client.messages.create(
        model=config.JUDGE_MODEL,
        max_tokens=256,
        temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    text = message.content[0].text
    from .extract import _json_from_text
    return _json_from_text(text)


# ---------------------------------------------------------------------------
# Critic on campaigns (F3)
# ---------------------------------------------------------------------------


def build_campaign_critic_prompt(campaign: Campaign) -> str:
    """Будує промпт для критика-судді кампанії.

    Просить суддю оцінити, чи провенанс підтверджує метрики і типізацію
    (type / tone / channels) кампанії.
    Вимагає СТРОГИЙ JSON: {"supported": bool, "confidence": 0..1, "reason": "..."}.
    """
    source_urls = sorted(
        {
            entry["source_url"]
            for entry in campaign.provenance.values()
            if isinstance(entry, dict) and entry.get("source_url")
        }
    )
    return (
        "Ти — незалежний критик-валідатор кампаній фандрайзингу.\n"
        "Оціни, чи цитовані джерела реально підтверджують вказані метрики і "
        "типізацію кампанії.\n\n"
        f"Заголовок: {campaign.title}\n"
        f"Ціль (goal): {campaign.goal}\n"
        f"Тип: {campaign.type}\n"
        f"Канали: {campaign.channels}\n"
        f"Тон: {campaign.tone}\n"
        f"amount_uah: {campaign.amount_uah}\n"
        f"reach: {campaign.reach}\n"
        f"spend: {campaign.spend}\n"
        f"Джерела провенансу: {source_urls}\n\n"
        "Поверни СТРОГО JSON (без зайвого тексту):\n"
        '{"supported": true|false, "confidence": 0.0..1.0, "reason": "<коротко українською>"}\n'
    )


def critique_campaign(
    campaign: Campaign,
    *,
    base_status: str,
    _judge: Callable[[str], dict] | None = None,
) -> tuple[str, str]:
    """Запускає суддю для кампанії і повертає (verification_status, reason).

    Upgrade rules (ідентичні critique_case):
    - base_status == "conflict" → завжди залишається "conflict".
    - base_status == "cross-checked" AND supported AND confidence >= 0.7 → "verified".
    - base_status == "cross-checked" AND NOT supported → зберігає "cross-checked".
    - base_status == "auto" → суддя не може підняти; pass through.
    """
    if _judge is None:
        _judge = _live_judge  # pragma: no cover

    if base_status == "conflict":
        return "conflict", ""

    prompt = build_campaign_critic_prompt(campaign)
    raw = _judge(prompt)
    verdict = parse_verdict(raw)

    if base_status == "cross-checked":
        if verdict["supported"] and verdict["confidence"] >= 0.7:
            return "verified", verdict["reason"]
        reason = verdict["reason"] if verdict["reason"] else "суддя не підтвердив"
        return base_status, reason

    # auto або інший: pass through
    return base_status, verdict["reason"]
