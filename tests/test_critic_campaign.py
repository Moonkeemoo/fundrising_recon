"""Тести для fundrec.critic — build_campaign_critic_prompt + critique_campaign (F3)."""
from __future__ import annotations

from fundrec.critic import build_campaign_critic_prompt, critique_campaign
from fundrec.schema import Campaign


def _make_campaign(
    id: str = "camp1",
    verification_status: str = "auto",
    amount_uah: float | None = 850000.0,
    reach: float | None = 250000.0,
    tone: list[str] | None = None,
    provenance: dict | None = None,
) -> Campaign:
    return Campaign(
        id=id,
        actor_id="a1",
        title="FPV-квадри для батальйону",
        goal="military/fpv",
        type="online_ad",
        channels=["facebook", "instagram"],
        tone=tone or ["emotional", "urgency"],
        amount_uah=amount_uah,
        reach=reach,
        provenance=provenance or {
            "amount_uah": {
                "source_url": "https://fb.com/ads/library/12345",
                "confidence": 0.6,
                "tier": 2,
                "note": "",
            },
            "reach": {
                "source_url": "https://fb.com/ads/library/12345",
                "confidence": 0.6,
                "tier": 2,
                "note": "",
            },
        },
        verification_status=verification_status,
        confidence_overall=0.6,
    )


# --- build_campaign_critic_prompt ---


def test_build_campaign_critic_prompt_includes_title():
    c = _make_campaign()
    p = build_campaign_critic_prompt(c)
    assert "FPV-квадри для батальйону" in p


def test_build_campaign_critic_prompt_includes_metrics():
    c = _make_campaign(amount_uah=850000.0, reach=250000.0)
    p = build_campaign_critic_prompt(c)
    assert "850000" in p or "850000.0" in p
    assert "250000" in p or "250000.0" in p


def test_build_campaign_critic_prompt_includes_source_urls():
    c = _make_campaign()
    p = build_campaign_critic_prompt(c)
    assert "fb.com" in p or "facebook" in p


def test_build_campaign_critic_prompt_includes_type_and_tone():
    c = _make_campaign()
    p = build_campaign_critic_prompt(c)
    assert "online_ad" in p
    assert "emotional" in p or "urgency" in p


def test_build_campaign_critic_prompt_requests_json():
    c = _make_campaign()
    p = build_campaign_critic_prompt(c)
    assert "JSON" in p
    assert "supported" in p
    assert "confidence" in p
    assert "reason" in p


# --- critique_campaign ---


def _make_judge(supported: bool, confidence: float, reason: str = "тест"):
    def _judge(prompt: str) -> dict:
        return {"supported": supported, "confidence": confidence, "reason": reason}
    return _judge


def test_critique_campaign_upgrades_cross_checked_to_verified():
    """cross-checked + підтримано з confidence>=0.7 → verified."""
    c = _make_campaign(verification_status="cross-checked")
    status, reason = critique_campaign(
        c, base_status="cross-checked", _judge=_make_judge(True, 0.8, "підтверджено")
    )
    assert status == "verified"
    assert reason


def test_critique_campaign_below_threshold_keeps_cross_checked():
    """cross-checked + підтримано, але confidence < 0.7 → залишається cross-checked."""
    c = _make_campaign(verification_status="cross-checked")
    status, reason = critique_campaign(
        c, base_status="cross-checked", _judge=_make_judge(True, 0.65)
    )
    assert status == "cross-checked"


def test_critique_campaign_unsupported_keeps_cross_checked():
    """cross-checked + НЕ підтримано → залишається cross-checked."""
    c = _make_campaign(verification_status="cross-checked")
    status, reason = critique_campaign(
        c,
        base_status="cross-checked",
        _judge=_make_judge(False, 0.4, "джерело не підтверджує метрики"),
    )
    assert status == "cross-checked"
    assert reason  # причина пояснює сумнів


def test_critique_campaign_conflict_stays_conflict():
    """conflict ніколи не знижується."""
    c = _make_campaign(verification_status="conflict")
    status, reason = critique_campaign(
        c, base_status="conflict", _judge=_make_judge(True, 0.99)
    )
    assert status == "conflict"


def test_critique_campaign_auto_passthrough():
    """auto: суддя не може підняти до verified — залишається auto."""
    c = _make_campaign(verification_status="auto")
    status, reason = critique_campaign(
        c, base_status="auto", _judge=_make_judge(True, 0.95)
    )
    assert status == "auto"
