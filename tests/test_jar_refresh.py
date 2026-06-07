"""Тести fundrec.jar_refresh — collect_jar_ids_from_campaigns (testable logic).

Live render_jar_cached — # pragma: no cover; тестуємо лише логіку збору jar_id.
"""

from __future__ import annotations

from fundrec.jar_refresh import collect_jar_ids_from_campaigns
from fundrec.schema import Campaign


def _camp_with_jar(cid: str, jar_id: str) -> Campaign:
    return Campaign(
        id=cid,
        actor_id="a1",
        title=f"Збір {cid}",
        goal="military",
        type="jar",
        channels=["telegram"],
        provenance={
            "amount_uah": {
                "source_url": f"https://send.monobank.ua/jar/{jar_id}",
                "tier": 1,
                "confidence": 0.9,
            }
        },
    )


def _camp_no_jar(cid: str) -> Campaign:
    return Campaign(
        id=cid,
        actor_id="a1",
        title=f"Збір {cid}",
        goal="military",
        type="online_ad",
        channels=["facebook"],
        provenance={},
    )


# ---------------------------------------------------------------------------
# Тести
# ---------------------------------------------------------------------------


def test_collect_extracts_jar_ids():
    """Збирає jar_id з кампаній що мають jar у провенансі."""
    camps = [
        _camp_with_jar("k1", "JAR001"),
        _camp_with_jar("k2", "JAR002"),
    ]
    result = collect_jar_ids_from_campaigns(camps)
    assert result == ["JAR001", "JAR002"]


def test_collect_deduplicates():
    """Дублікати jar_id видаляються; порядок першої появи зберігається."""
    camps = [
        _camp_with_jar("k1", "JAR001"),
        _camp_with_jar("k2", "JAR001"),  # дублікат
        _camp_with_jar("k3", "JAR002"),
    ]
    result = collect_jar_ids_from_campaigns(camps)
    assert result == ["JAR001", "JAR002"]


def test_collect_skips_campaigns_without_jar():
    """Кампанії без jar-провенансу ігноруються."""
    camps = [
        _camp_no_jar("k1"),
        _camp_with_jar("k2", "JAR999"),
        _camp_no_jar("k3"),
    ]
    result = collect_jar_ids_from_campaigns(camps)
    assert result == ["JAR999"]


def test_collect_empty_campaigns():
    """Порожній список → порожній результат."""
    assert collect_jar_ids_from_campaigns([]) == []


def test_collect_all_no_jar():
    """Всі кампанії без jar → порожній результат."""
    result = collect_jar_ids_from_campaigns([_camp_no_jar("k1"), _camp_no_jar("k2")])
    assert result == []


def test_collect_preserves_first_occurrence_order():
    """Порядок — перша поява кожного jar_id."""
    camps = [
        _camp_with_jar("k1", "JAR_C"),
        _camp_with_jar("k2", "JAR_A"),
        _camp_with_jar("k3", "JAR_B"),
        _camp_with_jar("k4", "JAR_A"),  # дублікат A
    ]
    result = collect_jar_ids_from_campaigns(camps)
    assert result == ["JAR_C", "JAR_A", "JAR_B"]
