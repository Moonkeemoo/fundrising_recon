"""Tests for fundrec.critic — prompt/parse/critique with injected judge."""

from __future__ import annotations

from fundrec.schema import Case
from fundrec.critic import build_critic_prompt, parse_verdict, critique_case


def _case(
    id: str = "c1",
    amount_uah: float | None = 1_000_000.0,
    goal_amount: float | None = 2_000_000.0,
    goal: str = "military/fpv",
    style: list[str] | None = None,
    method: list[str] | None = None,
    provenance: dict | None = None,
    verification_status: str = "auto",
) -> Case:
    return Case(
        id=id,
        title="FPV збір",
        actor_id="a1",
        url="https://monobank.ua/jar/x",
        goal=goal,
        style=style or ["urgency"],
        method=method or ["monobank_jar"],
        amount_uah=amount_uah,
        goal_amount=goal_amount,
        provenance=provenance
        or {
            "amount_uah": {
                "source_url": "https://monobank.ua/jar/x",
                "confidence": 0.95,
                "tier": 1,
                "note": "",
            },
        },
        verification_status=verification_status,
    )


# --- build_critic_prompt ---


def test_build_critic_prompt_includes_amounts():
    c = _case(amount_uah=1_000_000.0, goal_amount=2_000_000.0)
    prompt = build_critic_prompt(c)
    assert "1000000" in prompt or "1_000_000" in prompt or "1000000.0" in prompt


def test_build_critic_prompt_includes_source_url():
    c = _case()
    prompt = build_critic_prompt(c)
    assert "monobank.ua" in prompt


def test_build_critic_prompt_includes_goal_style_method():
    c = _case(goal="military/fpv", style=["urgency"], method=["monobank_jar"])
    prompt = build_critic_prompt(c)
    assert "military" in prompt
    assert "urgency" in prompt
    assert "monobank_jar" in prompt


def test_build_critic_prompt_requests_json():
    c = _case()
    prompt = build_critic_prompt(c)
    assert "JSON" in prompt
    assert "supported" in prompt
    assert "confidence" in prompt
    assert "reason" in prompt


# --- parse_verdict ---


def test_parse_verdict_valid_input():
    obj = {"supported": True, "confidence": 0.85, "reason": "підтверджено"}
    result = parse_verdict(obj)
    assert result == {"supported": True, "confidence": 0.85, "reason": "підтверджено"}


def test_parse_verdict_clamps_confidence_above_1():
    obj = {"supported": True, "confidence": 1.5, "reason": "ok"}
    result = parse_verdict(obj)
    assert result["confidence"] == 1.0


def test_parse_verdict_clamps_confidence_below_0():
    obj = {"supported": False, "confidence": -0.2, "reason": "ні"}
    result = parse_verdict(obj)
    assert result["confidence"] == 0.0


def test_parse_verdict_missing_supported_defaults_false():
    obj = {"confidence": 0.5, "reason": "немає supported"}
    result = parse_verdict(obj)
    assert result["supported"] is False


def test_parse_verdict_missing_reason_defaults_empty():
    obj = {"supported": True, "confidence": 0.9}
    result = parse_verdict(obj)
    assert result["reason"] == ""


def test_parse_verdict_missing_confidence_defaults_zero():
    obj = {"supported": True, "reason": "ok"}
    result = parse_verdict(obj)
    assert result["confidence"] == 0.0


def test_parse_verdict_coerces_confidence_to_float():
    obj = {"supported": True, "confidence": "0.8", "reason": "ok"}
    result = parse_verdict(obj)
    assert result["confidence"] == 0.8


# --- critique_case ---


def _make_judge(supported: bool, confidence: float, reason: str = "тест"):
    """Returns a fake _judge callable that returns fixed verdict."""

    def _judge(prompt: str) -> dict:
        return {"supported": supported, "confidence": confidence, "reason": reason}

    return _judge


def test_critique_case_upgrades_cross_checked_to_verified():
    """Supported + high confidence upgrades cross-checked → verified."""
    c = _case(verification_status="cross-checked")
    status, reason = critique_case(c, base_status="cross-checked", _judge=_make_judge(True, 0.8))
    assert status == "verified"
    assert reason  # non-empty


def test_critique_case_does_not_upgrade_below_threshold():
    """Supported but low confidence (< 0.7) — stays cross-checked."""
    c = _case(verification_status="cross-checked")
    status, reason = critique_case(c, base_status="cross-checked", _judge=_make_judge(True, 0.65))
    assert status == "cross-checked"


def test_critique_case_unsupported_keeps_base_status():
    """Unsupported verdict: keeps base_status, reason explains doubt."""
    c = _case(verification_status="cross-checked")
    status, reason = critique_case(
        c, base_status="cross-checked", _judge=_make_judge(False, 0.4, "джерело не підтверджує")
    )
    assert status == "cross-checked"
    assert "не підтверджує" in reason or reason  # reason populated


def test_critique_case_conflict_stays_conflict():
    """conflict is never downgraded — judge does not affect it."""
    c = _case(verification_status="conflict")
    status, reason = critique_case(c, base_status="conflict", _judge=_make_judge(True, 0.95))
    assert status == "conflict"


def test_critique_case_auto_passes_through():
    """auto base_status: judge cannot upgrade to verified (only cross-checked can)."""
    c = _case(verification_status="auto")
    status, reason = critique_case(c, base_status="auto", _judge=_make_judge(True, 0.95))
    assert status == "auto"
