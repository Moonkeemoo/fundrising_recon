"""Unit 1 — dedup merge preserves is_campaign / goal_reached / verdict_reason.

TDD: написано ДО виправлення. Тестує що _campaign_merge_two та merge_campaigns
зберігають поля is_campaign, goal_reached, verdict_reason (coalesce: canonical first,
якщо None — береться значення іншого).
"""
from __future__ import annotations

import pytest
from fundrec.dedup import _campaign_merge_two, merge_campaigns
from fundrec.schema import Campaign


def _camp(
    id: str,
    *,
    actor_id: str = "a1",
    title: str = "Збір на дрони",
    is_campaign: bool | None = None,
    goal_reached: bool | None = None,
    verdict_reason: str | None = None,
    amount_uah: float | None = None,
    provenance: dict | None = None,
    channels: list[str] | None = None,
) -> Campaign:
    return Campaign(
        id=id,
        actor_id=actor_id,
        title=title,
        goal="military",
        type="jar",
        is_campaign=is_campaign,
        goal_reached=goal_reached,
        verdict_reason=verdict_reason,
        amount_uah=amount_uah,
        provenance=provenance or {},
        channels=channels or [],
    )


# ---------------------------------------------------------------------------
# _campaign_merge_two: is_campaign
# ---------------------------------------------------------------------------


def test_merge_two_is_campaign_coalesce_none_takes_b():
    """a.is_campaign=None, b.is_campaign=True → merged True."""
    a = _camp("c1", is_campaign=None)
    b = _camp("c2", is_campaign=True)
    merged = _campaign_merge_two(a, b)
    assert merged.is_campaign is True


def test_merge_two_is_campaign_canonical_wins_if_set():
    """a.is_campaign=True, b.is_campaign=None → merged True (canonical preserved)."""
    a = _camp("c1", is_campaign=True)
    b = _camp("c2", is_campaign=None)
    merged = _campaign_merge_two(a, b)
    assert merged.is_campaign is True


def test_merge_two_is_campaign_false_preserved_if_b_none():
    """a.is_campaign=False, b.is_campaign=None → merged False."""
    a = _camp("c1", is_campaign=False)
    b = _camp("c2", is_campaign=None)
    merged = _campaign_merge_two(a, b)
    assert merged.is_campaign is False


def test_merge_two_is_campaign_both_none_stays_none():
    """a.is_campaign=None, b.is_campaign=None → merged None."""
    a = _camp("c1", is_campaign=None)
    b = _camp("c2", is_campaign=None)
    merged = _campaign_merge_two(a, b)
    assert merged.is_campaign is None


def test_merge_two_is_campaign_a_wins_over_b_false():
    """a.is_campaign=True, b.is_campaign=False → canonical (a) wins → True."""
    a = _camp("c1", is_campaign=True)
    b = _camp("c2", is_campaign=False)
    merged = _campaign_merge_two(a, b)
    assert merged.is_campaign is True


# ---------------------------------------------------------------------------
# _campaign_merge_two: goal_reached
# ---------------------------------------------------------------------------


def test_merge_two_goal_reached_coalesce_none_takes_b():
    """a.goal_reached=None, b.goal_reached=True → merged True."""
    a = _camp("c1", goal_reached=None)
    b = _camp("c2", goal_reached=True)
    merged = _campaign_merge_two(a, b)
    assert merged.goal_reached is True


def test_merge_two_goal_reached_canonical_wins_if_set():
    """a.goal_reached=True, b.goal_reached=None → merged True."""
    a = _camp("c1", goal_reached=True)
    b = _camp("c2", goal_reached=None)
    merged = _campaign_merge_two(a, b)
    assert merged.goal_reached is True


def test_merge_two_goal_reached_false_preserved():
    """a.goal_reached=False, b.goal_reached=None → merged False."""
    a = _camp("c1", goal_reached=False)
    b = _camp("c2", goal_reached=None)
    merged = _campaign_merge_two(a, b)
    assert merged.goal_reached is False


def test_merge_two_goal_reached_both_none():
    """Both None → stays None."""
    a = _camp("c1", goal_reached=None)
    b = _camp("c2", goal_reached=None)
    merged = _campaign_merge_two(a, b)
    assert merged.goal_reached is None


# ---------------------------------------------------------------------------
# _campaign_merge_two: verdict_reason
# ---------------------------------------------------------------------------


def test_merge_two_verdict_reason_coalesce_none_takes_b():
    """a.verdict_reason=None, b.verdict_reason='збір' → merged 'збір'."""
    a = _camp("c1", verdict_reason=None)
    b = _camp("c2", verdict_reason="збір")
    merged = _campaign_merge_two(a, b)
    assert merged.verdict_reason == "збір"


def test_merge_two_verdict_reason_canonical_wins():
    """a.verdict_reason='canonical', b.verdict_reason='other' → 'canonical'."""
    a = _camp("c1", verdict_reason="canonical reason")
    b = _camp("c2", verdict_reason="other reason")
    merged = _campaign_merge_two(a, b)
    assert merged.verdict_reason == "canonical reason"


def test_merge_two_verdict_reason_a_none_b_set():
    """a.verdict_reason=None, b has value → coalesced to b's value."""
    a = _camp("c1", verdict_reason=None)
    b = _camp("c2", verdict_reason="llm said yes")
    merged = _campaign_merge_two(a, b)
    assert merged.verdict_reason == "llm said yes"


def test_merge_two_verdict_reason_both_none():
    a = _camp("c1", verdict_reason=None)
    b = _camp("c2", verdict_reason=None)
    merged = _campaign_merge_two(a, b)
    assert merged.verdict_reason is None


# ---------------------------------------------------------------------------
# merge_campaigns: end-to-end via public API
# ---------------------------------------------------------------------------


def test_merge_campaigns_preserves_is_campaign_from_b():
    """merge_campaigns: один None + один True → True."""
    c1 = _camp("c1", is_campaign=None, channels=["telegram"])
    c2 = _camp("c2", is_campaign=True, channels=["facebook"])
    result = merge_campaigns([c1, c2])
    assert len(result) == 1
    assert result[0].is_campaign is True


def test_merge_campaigns_preserves_goal_reached_from_a():
    """merge_campaigns: canonical (a) має goal_reached=True — зберігається."""
    c1 = _camp("c1", goal_reached=True, channels=["telegram"])
    c2 = _camp("c2", goal_reached=None, channels=["facebook"])
    result = merge_campaigns([c1, c2])
    assert len(result) == 1
    assert result[0].goal_reached is True


def test_merge_campaigns_existing_channels_still_unioned():
    """Existing merge behavior (channels union) is not regressed."""
    c1 = _camp("c1", is_campaign=True, channels=["telegram"])
    c2 = _camp("c2", is_campaign=True, channels=["facebook"])
    result = merge_campaigns([c1, c2])
    assert len(result) == 1
    assert set(result[0].channels) == {"telegram", "facebook"}


def test_merge_campaigns_existing_amount_provenance_not_regressed():
    """Existing amount/provenance merge behavior not regressed."""
    prov_tier1 = {"amount_uah": {"source_url": "https://monobank.ua/jar/123", "confidence": 0.95, "tier": 1}}
    prov_tier2 = {"amount_uah": {"source_url": "https://news.ua", "confidence": 0.6, "tier": 2}}
    c1 = _camp("c1", amount_uah=9000.0, provenance=prov_tier2, is_campaign=None)
    c2 = _camp("c2", amount_uah=12500.0, provenance=prov_tier1, is_campaign=True)
    result = merge_campaigns([c1, c2])
    assert len(result) == 1
    assert result[0].amount_uah == 12500.0
    assert result[0].provenance["amount_uah"]["tier"] == 1
    # is_campaign coalesced from b
    assert result[0].is_campaign is True
