"""Тести validate_campaign і validate_creative (F1)."""
from __future__ import annotations

from fundrec.schema import Campaign, CreativeAsset
from fundrec import validate


# --- допоміжники ---


def _valid_campaign(**override) -> Campaign:
    base: dict = dict(
        id="camp1",
        actor_id="a1",
        title="Тест",
        goal="military/fpv",
        type="online_ad",
        channels=["facebook"],
        form_factor=["video"],
        tone=["emotional"],
        cta_type="jar",
        face="soldier",
        cadence="one_off",
        year=2024,
        amount_uah=500000.0,
        reach=100000.0,
        provenance={
            "amount_uah": {"source_url": "https://x", "confidence": 0.9, "tier": 1, "note": ""},
            "reach": {"source_url": "https://x", "confidence": 0.8, "tier": 2, "note": ""},
        },
        verification_status="auto",
    )
    base.update(override)
    return Campaign(**base)


def _valid_creative(**override) -> CreativeAsset:
    base: dict = dict(
        id="cr1",
        campaign_id="camp1",
        platform="facebook",
        format="video",
        views=1000.0,
        provenance={"views": {"source_url": "https://x", "confidence": 0.8, "tier": 2, "note": ""}},
    )
    base.update(override)
    return CreativeAsset(**base)


# --- validate_campaign: чистий випадок ---


def test_clean_campaign_no_problems():
    assert validate.validate_campaign(_valid_campaign()) == []


# --- числові метрики: provenance + невідʼємність ---


def test_campaign_amount_uah_without_provenance():
    c = _valid_campaign(provenance={})
    probs = validate.validate_campaign(c)
    assert any("provenance" in p for p in probs)


def test_campaign_reach_without_provenance():
    c = _valid_campaign(
        provenance={"amount_uah": {"source_url": "x", "confidence": 0.9, "tier": 1, "note": ""}}
    )
    probs = validate.validate_campaign(c)
    assert any("reach" in p for p in probs)


def test_campaign_negative_amount_uah():
    c = _valid_campaign(amount_uah=-1.0)
    probs = validate.validate_campaign(c)
    assert any("amount_uah" in p for p in probs)


def test_campaign_negative_reach():
    c = _valid_campaign(reach=-500.0)
    probs = validate.validate_campaign(c)
    assert any("reach" in p for p in probs)


def test_campaign_null_metrics_ok():
    """None-метрики не потребують provenance (honest null)."""
    c = _valid_campaign(reach=None, amount_uah=None, provenance={})
    assert validate.validate_campaign(c) == []


# --- type ---


def test_campaign_unknown_type():
    c = _valid_campaign(type="unknown_type")
    probs = validate.validate_campaign(c)
    assert any("type" in p for p in probs)


# --- channels ---


def test_campaign_unknown_channel():
    c = _valid_campaign(channels=["facebook", "myspace"])
    probs = validate.validate_campaign(c)
    assert any("channel" in p for p in probs)


# --- form_factor ---


def test_campaign_unknown_form_factor():
    c = _valid_campaign(form_factor=["hologram"])
    probs = validate.validate_campaign(c)
    assert any("form_factor" in p for p in probs)


# --- cta_type ---


def test_campaign_unknown_cta_type():
    c = _valid_campaign(cta_type="magic_link")
    probs = validate.validate_campaign(c)
    assert any("cta_type" in p for p in probs)


def test_campaign_none_cta_type_ok():
    c = _valid_campaign(cta_type=None)
    assert validate.validate_campaign(c) == []


# --- tone ---


def test_campaign_unknown_tone():
    c = _valid_campaign(tone=["funny"])
    probs = validate.validate_campaign(c)
    assert any("tone" in p for p in probs)


# --- face ---


def test_campaign_unknown_face():
    c = _valid_campaign(face="alien")
    probs = validate.validate_campaign(c)
    assert any("face" in p for p in probs)


def test_campaign_none_face_ok():
    c = _valid_campaign(face=None)
    assert validate.validate_campaign(c) == []


# --- cadence ---


def test_campaign_unknown_cadence():
    c = _valid_campaign(cadence="whenever")
    probs = validate.validate_campaign(c)
    assert any("cadence" in p for p in probs)


def test_campaign_none_cadence_ok():
    c = _valid_campaign(cadence=None)
    assert validate.validate_campaign(c) == []


# --- goal category ---


def test_campaign_unknown_goal_category():
    c = _valid_campaign(goal="weapons/x")
    probs = validate.validate_campaign(c)
    assert any("goal" in p for p in probs)


# --- verification_status ---


def test_campaign_unknown_verification_status():
    c = _valid_campaign(verification_status="maybe")
    probs = validate.validate_campaign(c)
    assert any("verification_status" in p for p in probs)


# --- year ---


def test_campaign_year_out_of_range():
    c = _valid_campaign(year=2019)
    probs = validate.validate_campaign(c)
    assert any("year" in p for p in probs)


def test_campaign_none_year_ok():
    c = _valid_campaign(year=None)
    assert validate.validate_campaign(c) == []


# === validate_creative ===


def test_clean_creative_no_problems():
    assert validate.validate_creative(_valid_creative()) == []


def test_creative_unknown_format():
    a = _valid_creative(format="hologram")
    probs = validate.validate_creative(a)
    assert any("format" in p for p in probs)


def test_creative_unknown_platform():
    a = _valid_creative(platform="myspace")
    probs = validate.validate_creative(a)
    assert any("platform" in p for p in probs)


def test_creative_views_without_provenance():
    a = _valid_creative(views=500.0, provenance={})
    probs = validate.validate_creative(a)
    assert any("provenance" in p for p in probs)


def test_creative_likes_without_provenance():
    a = _valid_creative(views=None, likes=100.0, provenance={})
    probs = validate.validate_creative(a)
    assert any("provenance" in p for p in probs)


def test_creative_negative_views():
    a = _valid_creative(views=-1.0)
    probs = validate.validate_creative(a)
    assert any("views" in p for p in probs)


def test_creative_negative_likes():
    a = _valid_creative(likes=-5.0)
    probs = validate.validate_creative(a)
    assert any("likes" in p for p in probs)


def test_creative_null_metrics_ok():
    a = _valid_creative(views=None, likes=None, provenance={})
    assert validate.validate_creative(a) == []
