"""Tests for fundrec.crosscheck — detect_conflict + assess_verification."""

from __future__ import annotations

from fundrec.schema import Case
from fundrec.crosscheck import detect_conflict, assess_verification


def _case(
    id: str,
    amount_uah: float | None = None,
    url: str = "https://example.com/case",
    provenance: dict | None = None,
    verification_status: str = "auto",
) -> Case:
    return Case(
        id=id,
        title="Test",
        actor_id="a1",
        url=url,
        goal="military",
        amount_uah=amount_uah,
        provenance=provenance or {},
        verification_status=verification_status,
    )


# --- detect_conflict ---


def test_no_conflict_within_tolerance():
    """Amounts within 10% tol → no conflict."""
    c1 = _case("c1", amount_uah=1_000_000.0)
    c2 = _case("c2", amount_uah=1_090_000.0)  # +9% — within tol
    assert detect_conflict([c1, c2]) is False


def test_conflict_beyond_tolerance():
    """Amounts differ >10% → conflict."""
    c1 = _case("c1", amount_uah=1_000_000.0)
    c2 = _case("c2", amount_uah=1_200_000.0)  # +20% — beyond tol
    assert detect_conflict([c1, c2]) is True


def test_no_conflict_exact_boundary():
    """Exactly at tol boundary (10%) → no conflict (not strictly greater)."""
    c1 = _case("c1", amount_uah=1_000_000.0)
    c2 = _case("c2", amount_uah=1_100_000.0)  # exactly +10%
    assert detect_conflict([c1, c2]) is False


def test_conflict_none_amounts_ignored():
    """None amounts are skipped — no conflict from absent data."""
    c1 = _case("c1", amount_uah=None)
    c2 = _case("c2", amount_uah=1_000_000.0)
    c3 = _case("c3", amount_uah=None)
    assert detect_conflict([c1, c2, c3]) is False


def test_conflict_all_none_no_conflict():
    """All None → no conflict."""
    c1 = _case("c1", amount_uah=None)
    c2 = _case("c2", amount_uah=None)
    assert detect_conflict([c1, c2]) is False


def test_single_case_no_conflict():
    """Single case list → never a conflict."""
    c = _case("c1", amount_uah=500_000.0)
    assert detect_conflict([c]) is False


def test_empty_list_no_conflict():
    assert detect_conflict([]) is False


def test_conflict_three_cases_one_outlier():
    """Three cases: two agree, one is far off → conflict."""
    c1 = _case("c1", amount_uah=1_000_000.0)
    c2 = _case("c2", amount_uah=1_050_000.0)
    c3 = _case("c3", amount_uah=2_000_000.0)  # 100% off the max
    assert detect_conflict([c1, c2, c3]) is True


# --- assess_verification ---


def test_assess_conflict_flag_returns_conflict():
    c = _case("c1", amount_uah=1_000_000.0)
    assert assess_verification(c, conflicting=True) == "conflict"


def test_assess_tier1_provenance_returns_cross_checked():
    prov = {
        "amount_uah": {
            "source_url": "https://monobank.ua/jar/x",
            "confidence": 0.95,
            "tier": 1,
            "note": "",
        }
    }
    c = _case("c1", amount_uah=1_000_000.0, provenance=prov)
    assert assess_verification(c, conflicting=False) == "cross-checked"


def test_assess_tier2_only_returns_auto():
    prov = {
        "amount_uah": {
            "source_url": "https://news.ua/art",
            "confidence": 0.6,
            "tier": 2,
            "note": "",
        }
    }
    c = _case("c1", amount_uah=500_000.0, provenance=prov)
    assert assess_verification(c, conflicting=False) == "auto"


def test_assess_no_provenance_returns_auto():
    c = _case("c1")
    assert assess_verification(c, conflicting=False) == "auto"


def test_assess_tier3_only_returns_auto():
    prov = {
        "amount_uah": {"source_url": "https://t.me/x", "confidence": 0.35, "tier": 3, "note": ""}
    }
    c = _case("c1", amount_uah=100_000.0, provenance=prov)
    assert assess_verification(c, conflicting=False) == "auto"


def test_assess_conflict_wins_over_tier1():
    """conflicting=True → conflict even if tier-1 present."""
    prov = {
        "amount_uah": {
            "source_url": "https://monobank.ua/jar/y",
            "confidence": 0.95,
            "tier": 1,
            "note": "",
        }
    }
    c = _case("c1", amount_uah=1_000_000.0, provenance=prov)
    assert assess_verification(c, conflicting=True) == "conflict"
