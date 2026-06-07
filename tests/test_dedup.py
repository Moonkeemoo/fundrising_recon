"""Тести для fundrec.dedup — dedup_key + merge_cases."""
from __future__ import annotations

from fundrec.dedup import dedup_key, merge_cases
from fundrec.schema import Case

# --- Фікстури ---

def _make_case(
    id: str,
    url: str = "https://example.com/case",
    title: str = "Тест",
    actor_id: str = "actor1",
    goal: str = "military",
    style: list[str] | None = None,
    method: list[str] | None = None,
    amount_uah: float | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    provenance: dict | None = None,
    confidence_overall: float = 0.0,
) -> Case:
    return Case(
        id=id,
        title=title,
        actor_id=actor_id,
        url=url,
        goal=goal,
        style=style or [],
        method=method or [],
        amount_uah=amount_uah,
        date_start=date_start,
        date_end=date_end,
        provenance=provenance or {},
        confidence_overall=confidence_overall,
    )


# --- dedup_key тести ---

def test_dedup_key_uses_url_host_path():
    """Ключ базується на host + path URL."""
    c = _make_case("id1", url="https://send.monobank.ua/jar/abc123/extra")
    key = dedup_key(c)
    assert "monobank.ua" in key
    assert "abc123" in key


def test_dedup_key_normalizes_trailing_slash():
    c1 = _make_case("id1", url="https://example.com/case/")
    c2 = _make_case("id2", url="https://example.com/case")
    assert dedup_key(c1) == dedup_key(c2)


def test_dedup_key_different_urls_differ():
    c1 = _make_case("id1", url="https://example.com/case/1")
    c2 = _make_case("id2", url="https://example.com/case/2")
    assert dedup_key(c1) != dedup_key(c2)


def test_dedup_key_fallback_slug_when_no_url():
    """Якщо URL не парситься або порожній — slug з actor_id + title."""
    c = _make_case("id1", url="", title="Великий збір", actor_id="act1")
    key = dedup_key(c)
    assert key  # непорожній
    assert "act1" in key or "збір" in key.lower() or "velyk" in key.lower()


# --- merge_cases тести ---

def test_merge_empty_list():
    assert merge_cases([]) == []


def test_merge_single_case_passthrough():
    c = _make_case("id1", amount_uah=1000.0)
    result = merge_cases([c])
    assert len(result) == 1
    assert result[0].id == "id1"


def test_merge_different_keys_no_merge():
    """Кейси з різними URL → не зливаються."""
    c1 = _make_case("id1", url="https://example.com/1", amount_uah=1000.0)
    c2 = _make_case("id2", url="https://example.com/2", amount_uah=2000.0)
    result = merge_cases([c1, c2])
    assert len(result) == 2


def test_merge_tier1_beats_tier2_amount():
    """Tier-1 провенанс для amount_uah перемагає tier-2."""
    prov_tier2 = {"amount_uah": {"source_url": "https://news.ua/art1", "confidence": 0.7, "tier": 2}}
    prov_tier1 = {"amount_uah": {"source_url": "https://monobank.ua/jar/123", "confidence": 0.95, "tier": 1}}

    c_tier2 = _make_case(
        "id1",
        url="https://example.com/case",
        amount_uah=9_000_000.0,
        provenance=prov_tier2,
        confidence_overall=0.7,
    )
    c_tier1 = _make_case(
        "id2",
        url="https://example.com/case",
        amount_uah=12_500_000.0,
        provenance=prov_tier1,
        confidence_overall=0.95,
    )

    result = merge_cases([c_tier2, c_tier1])
    assert len(result) == 1
    merged = result[0]
    assert merged.amount_uah == 12_500_000.0
    assert merged.provenance["amount_uah"]["tier"] == 1
    assert merged.provenance["amount_uah"]["confidence"] == 0.95


def test_merge_styles_unioned():
    """Стилі з обох кейсів об'єднуються."""
    c1 = _make_case("id1", url="https://example.com/case", style=["emotional_personal", "urgency"])
    c2 = _make_case("id2", url="https://example.com/case", style=["gamification", "urgency"])
    result = merge_cases([c1, c2])
    assert len(result) == 1
    merged_styles = set(result[0].style)
    assert "emotional_personal" in merged_styles
    assert "gamification" in merged_styles
    assert "urgency" in merged_styles


def test_merge_methods_unioned():
    """Способи з обох кейсів об'єднуються."""
    c1 = _make_case("id1", url="https://example.com/case", method=["monobank_jar"])
    c2 = _make_case("id2", url="https://example.com/case", method=["bank_transfer", "monobank_jar"])
    result = merge_cases([c1, c2])
    assert len(result) == 1
    merged_methods = set(result[0].method)
    assert "monobank_jar" in merged_methods
    assert "bank_transfer" in merged_methods


def test_merge_keeps_earliest_date_start():
    c1 = _make_case("id1", url="https://example.com/case", date_start="2024-03-15")
    c2 = _make_case("id2", url="https://example.com/case", date_start="2024-01-01")
    result = merge_cases([c1, c2])
    assert result[0].date_start == "2024-01-01"


def test_merge_keeps_latest_date_end():
    c1 = _make_case("id1", url="https://example.com/case", date_end="2024-06-30")
    c2 = _make_case("id2", url="https://example.com/case", date_end="2024-12-31")
    result = merge_cases([c1, c2])
    assert result[0].date_end == "2024-12-31"


def test_merge_confidence_overall_max_of_kept():
    """confidence_overall = max confidence серед збережених полів."""
    prov1 = {"amount_uah": {"confidence": 0.6, "tier": 2, "source_url": "http://a"}}
    prov2 = {"amount_uah": {"confidence": 0.9, "tier": 1, "source_url": "http://b"}}
    c1 = _make_case("id1", url="https://example.com/case", amount_uah=1000.0, provenance=prov1)
    c2 = _make_case("id2", url="https://example.com/case", amount_uah=2000.0, provenance=prov2)
    result = merge_cases([c1, c2])
    assert result[0].confidence_overall == 0.9


def test_merge_date_none_handled():
    """Один кейс без дат — дата береться з іншого."""
    c1 = _make_case("id1", url="https://example.com/case", date_start=None, date_end=None)
    c2 = _make_case("id2", url="https://example.com/case", date_start="2024-01-01", date_end="2024-06-01")
    result = merge_cases([c1, c2])
    assert result[0].date_start == "2024-01-01"
    assert result[0].date_end == "2024-06-01"
