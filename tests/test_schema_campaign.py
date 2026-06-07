"""Тести для нових словників і дата-класів кампаній (F1)."""
from __future__ import annotations

from fundrec import schema
from fundrec.schema import (
    Campaign,
    CreativeAsset,
    Partner,
    campaign_from_dict,
    campaign_to_dict,
    creative_from_dict,
    creative_to_dict,
    partner_from_dict,
    partner_to_dict,
)


# --- словники ---


def test_campaign_types_vocab():
    assert schema.CAMPAIGN_TYPES == {
        "online_ad",
        "organic_social",
        "telethon",
        "event_irl",
        "platform",
        "jar",
        "mixed",
    }


def test_channels_vocab():
    expected = {"facebook", "instagram", "threads", "youtube", "telegram", "tiktok", "web", "irl"}
    assert schema.CHANNELS == expected


def test_form_factors_vocab():
    assert schema.FORM_FACTORS == {"video", "carousel", "banner", "longread", "stream", "image", "text"}


def test_cta_types_vocab():
    assert schema.CTA_TYPES == {"donate_link", "jar", "qr", "auction", "subscription", "merch"}


def test_tones_vocab():
    assert schema.TONES == {"emotional", "urgency", "humor", "data_transparent", "heroism", "gratitude"}


def test_face_types_vocab():
    assert schema.FACE_TYPES == {"soldier", "blogger", "celebrity", "brand", "official", "anonymous"}


def test_cadence_vocab():
    assert schema.CADENCE == {"one_off", "series", "ongoing"}


def test_partner_roles_vocab():
    assert schema.PARTNER_ROLES == {"sponsor", "organizer", "celebrity", "brand", "partner"}


def test_creative_formats_vocab():
    assert schema.CREATIVE_FORMATS == {"image", "video", "carousel", "text", "stream"}


# --- Campaign ---


def _make_campaign(**override) -> Campaign:
    base: dict = dict(
        id="camp1",
        actor_id="a1",
        title="Тест-кампанія",
        goal="military/fpv",
        type="online_ad",
        channels=["facebook", "instagram"],
        form_factor=["video", "carousel"],
        tone=["emotional"],
        partner_ids=["p1"],
        provenance={"amount_uah": {"source_url": "https://x", "confidence": 0.9, "tier": 1, "note": ""}},
    )
    base.update(override)
    return Campaign(**base)


def test_campaign_defaults():
    c = Campaign(
        id="camp1",
        actor_id="a1",
        title="T",
        goal="military",
        type="jar",
    )
    assert c.channels == []
    assert c.form_factor == []
    assert c.tone == []
    assert c.partner_ids == []
    assert c.provenance == {}
    assert c.confidence_overall == 0.0
    assert c.verification_status == "auto"
    assert c.amount_uah is None
    assert c.case_id is None


def test_campaign_roundtrip():
    c = _make_campaign(
        year=2024,
        date_start="2024-01-01",
        amount_uah=500000.0,
        reach=100000.0,
        cta_type="jar",
        face="soldier",
        cadence="one_off",
        playbook_note="Тест нотатка",
        confidence_overall=0.85,
        verification_status="cross-checked",
        extracted_at="2026-06-07T00:00:00",
        extracted_by_model="claude-3",
    )
    d = campaign_to_dict(c)
    # list fields preserved
    assert d["channels"] == ["facebook", "instagram"]
    assert d["tone"] == ["emotional"]
    assert d["partner_ids"] == ["p1"]
    # provenance dict preserved
    assert isinstance(d["provenance"], dict)
    c2 = campaign_from_dict(d)
    assert c2 == c


def test_campaign_nullable_metrics_default_none():
    c = Campaign(id="c", actor_id="a", title="T", goal="military", type="jar")
    for f in ("amount_uah", "amount_usd", "reach", "engagement", "spend", "assets_count"):
        assert getattr(c, f) is None, f"{f} should default to None"


# --- CreativeAsset ---


def _make_creative(**override) -> CreativeAsset:
    base: dict = dict(
        id="cr1",
        campaign_id="camp1",
        platform="facebook",
        format="video",
        provenance={"views": {"source_url": "https://x", "confidence": 0.8, "tier": 2, "note": ""}},
    )
    base.update(override)
    return CreativeAsset(**base)


def test_creative_defaults():
    a = CreativeAsset(id="cr1", campaign_id="c1", platform="facebook", format="video")
    assert a.copy_text is None
    assert a.views is None
    assert a.provenance == {}


def test_creative_roundtrip():
    a = _make_creative(
        copy_text="Допоможи!",
        hook="Зупини ворога",
        cta="Донатити",
        media_url="https://cdn.example.com/img.jpg",
        published="2024-03-01",
        impressions_range="1000-5000",
        spend_range="10-50 USD",
        views=3200.0,
        likes=150.0,
    )
    d = creative_to_dict(a)
    assert isinstance(d["provenance"], dict)
    a2 = creative_from_dict(d)
    assert a2 == a


# --- Partner ---


def test_partner_defaults():
    p = Partner(id="p1", name="Brave1", role="sponsor")
    assert p.links == []


def test_partner_roundtrip():
    p = Partner(id="p1", name="Brave1", role="sponsor", links=["https://brave1.org"])
    d = partner_to_dict(p)
    assert d["links"] == ["https://brave1.org"]
    p2 = partner_from_dict(d)
    assert p2 == p
