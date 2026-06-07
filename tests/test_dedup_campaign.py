"""Тести для fundrec.dedup — campaign_dedup_key + merge_campaigns (F3).

Campaign не має поля url; dedup-ключ базується на actor_id + title
(slug-нормалізований). Кампанії з однаковим actor_id+title → один slug-ключ.
"""
from __future__ import annotations

from fundrec.dedup import campaign_dedup_key, merge_campaigns
from fundrec.schema import Campaign


def _make_campaign(
    id: str,
    title: str = "FPV кампанія",
    actor_id: str = "a1",
    channels: list[str] | None = None,
    tone: list[str] | None = None,
    form_factor: list[str] | None = None,
    amount_uah: float | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    provenance: dict | None = None,
    confidence_overall: float = 0.0,
) -> Campaign:
    return Campaign(
        id=id,
        actor_id=actor_id,
        title=title,
        goal="military",
        type="online_ad",
        channels=channels or [],
        tone=tone or [],
        form_factor=form_factor or [],
        amount_uah=amount_uah,
        date_start=date_start,
        date_end=date_end,
        provenance=provenance or {},
        confidence_overall=confidence_overall,
    )


# --- campaign_dedup_key ---


def test_campaign_dedup_key_nonempty():
    """Ключ — непорожній рядок."""
    c = _make_campaign("c1", actor_id="a1", title="FPV кампанія")
    key = campaign_dedup_key(c)
    assert key


def test_campaign_dedup_key_same_actor_and_title_same_key():
    """Однаковий actor_id + title → однаковий ключ."""
    c1 = _make_campaign("c1", actor_id="act1", title="Назва кампанії")
    c2 = _make_campaign("c2", actor_id="act1", title="Назва кампанії")
    assert campaign_dedup_key(c1) == campaign_dedup_key(c2)


def test_campaign_dedup_key_different_titles_differ():
    """Різні назви → різні ключі."""
    c1 = _make_campaign("c1", actor_id="act1", title="Кампанія А")
    c2 = _make_campaign("c2", actor_id="act1", title="Кампанія Б")
    assert campaign_dedup_key(c1) != campaign_dedup_key(c2)


def test_campaign_dedup_key_different_actors_differ():
    """Різний actor_id → різні ключі (навіть при однаковому title)."""
    c1 = _make_campaign("c1", actor_id="act1", title="Кампанія")
    c2 = _make_campaign("c2", actor_id="act2", title="Кампанія")
    assert campaign_dedup_key(c1) != campaign_dedup_key(c2)


def test_campaign_dedup_key_contains_actor_or_title_fragment():
    """Ключ містить частину actor_id або title."""
    c = _make_campaign("c1", actor_id="act1", title="Великий збір")
    key = campaign_dedup_key(c)
    assert "act1" in key or "velyk" in key.lower()


# --- merge_campaigns ---


def test_merge_campaigns_empty_list():
    assert merge_campaigns([]) == []


def test_merge_campaigns_single_passthrough():
    c = _make_campaign("c1", amount_uah=1000.0)
    result = merge_campaigns([c])
    assert len(result) == 1
    assert result[0].id == "c1"


def test_merge_campaigns_different_keys_no_merge():
    """Кампанії з різними actor+title — не зливаються."""
    c1 = _make_campaign("c1", actor_id="a1", title="Кампанія А", amount_uah=1000.0)
    c2 = _make_campaign("c2", actor_id="a1", title="Кампанія Б", amount_uah=2000.0)
    result = merge_campaigns([c1, c2])
    assert len(result) == 2


def test_merge_campaigns_tier1_beats_tier2_amount():
    """Tier-1 провенанс для amount_uah перемагає tier-2."""
    prov_tier2 = {"amount_uah": {"source_url": "https://news.ua/art1", "confidence": 0.6, "tier": 2}}
    prov_tier1 = {"amount_uah": {"source_url": "https://monobank.ua/jar/123", "confidence": 0.95, "tier": 1}}

    c_tier2 = _make_campaign(
        "c1",
        actor_id="a1", title="FPV кампанія",
        amount_uah=9_000_000.0,
        provenance=prov_tier2,
        confidence_overall=0.6,
    )
    c_tier1 = _make_campaign(
        "c2",
        actor_id="a1", title="FPV кампанія",
        amount_uah=12_500_000.0,
        provenance=prov_tier1,
        confidence_overall=0.95,
    )

    result = merge_campaigns([c_tier2, c_tier1])
    assert len(result) == 1
    merged = result[0]
    assert merged.amount_uah == 12_500_000.0
    assert merged.provenance["amount_uah"]["tier"] == 1
    assert merged.provenance["amount_uah"]["confidence"] == 0.95


def test_merge_campaigns_channels_unioned():
    """Канали з обох кампаній об'єднуються."""
    c1 = _make_campaign("c1", actor_id="a1", title="FPV кампанія", channels=["facebook", "instagram"])
    c2 = _make_campaign("c2", actor_id="a1", title="FPV кампанія", channels=["telegram", "facebook"])
    result = merge_campaigns([c1, c2])
    assert len(result) == 1
    merged_channels = set(result[0].channels)
    assert "facebook" in merged_channels
    assert "instagram" in merged_channels
    assert "telegram" in merged_channels


def test_merge_campaigns_tone_unioned():
    """Тони з обох кампаній об'єднуються."""
    c1 = _make_campaign("c1", actor_id="a1", title="FPV кампанія", tone=["emotional", "urgency"])
    c2 = _make_campaign("c2", actor_id="a1", title="FPV кампанія", tone=["heroism", "emotional"])
    result = merge_campaigns([c1, c2])
    assert len(result) == 1
    merged_tone = set(result[0].tone)
    assert "emotional" in merged_tone
    assert "urgency" in merged_tone
    assert "heroism" in merged_tone


def test_merge_campaigns_form_factor_unioned():
    """form_factor з обох кампаній об'єднується."""
    c1 = _make_campaign("c1", actor_id="a1", title="FPV кампанія", form_factor=["video"])
    c2 = _make_campaign("c2", actor_id="a1", title="FPV кампанія", form_factor=["image", "video"])
    result = merge_campaigns([c1, c2])
    assert len(result) == 1
    merged_ff = set(result[0].form_factor)
    assert "video" in merged_ff
    assert "image" in merged_ff


def test_merge_campaigns_keeps_earliest_date_start():
    c1 = _make_campaign("c1", actor_id="a1", title="FPV кампанія", date_start="2024-03-15")
    c2 = _make_campaign("c2", actor_id="a1", title="FPV кампанія", date_start="2024-01-01")
    result = merge_campaigns([c1, c2])
    assert result[0].date_start == "2024-01-01"


def test_merge_campaigns_keeps_latest_date_end():
    c1 = _make_campaign("c1", actor_id="a1", title="FPV кампанія", date_end="2024-06-30")
    c2 = _make_campaign("c2", actor_id="a1", title="FPV кампанія", date_end="2024-12-31")
    result = merge_campaigns([c1, c2])
    assert result[0].date_end == "2024-12-31"


def test_merge_campaigns_confidence_overall_from_best_provenance():
    """confidence_overall = max confidence збережених полів."""
    prov1 = {"amount_uah": {"confidence": 0.6, "tier": 2, "source_url": "http://a"}}
    prov2 = {"amount_uah": {"confidence": 0.9, "tier": 1, "source_url": "http://b"}}
    c1 = _make_campaign("c1", actor_id="a1", title="FPV кампанія", amount_uah=1000.0, provenance=prov1)
    c2 = _make_campaign("c2", actor_id="a1", title="FPV кампанія", amount_uah=2000.0, provenance=prov2)
    result = merge_campaigns([c1, c2])
    assert result[0].confidence_overall == 0.9


def test_merge_campaigns_surviving_id_deterministic():
    """ID виживаючої кампанії детермінований (менший за алфавітом)."""
    c1 = _make_campaign("camp-a", actor_id="a1", title="FPV кампанія")
    c2 = _make_campaign("camp-b", actor_id="a1", title="FPV кампанія")
    result = merge_campaigns([c1, c2])
    assert result[0].id == "camp-a"


def test_merge_campaigns_date_none_handled():
    """Один кейс без дат — дата береться з іншого."""
    c1 = _make_campaign("c1", actor_id="a1", title="FPV кампанія", date_start=None, date_end=None)
    c2 = _make_campaign("c2", actor_id="a1", title="FPV кампанія", date_start="2024-01-01", date_end="2024-06-01")
    result = merge_campaigns([c1, c2])
    assert result[0].date_start == "2024-01-01"
    assert result[0].date_end == "2024-06-01"
