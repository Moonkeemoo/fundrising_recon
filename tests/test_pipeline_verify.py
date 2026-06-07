"""End-to-end tests for pipeline_verify.verify_cases with injected judge."""

from __future__ import annotations

from fundrec import store
from fundrec.schema import Actor, Source, Case
from fundrec.pipeline_verify import verify_cases


def _setup_db(tmp_path):
    """Create an in-memory-ish sqlite DB seeded with actors/sources."""
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id="a1", name="Притула", type="foundation"))
    store.upsert_source(
        conn,
        Source(
            url="https://monobank.ua/jar/x",
            type="structured",
            tier=1,
            access="public",
            license="unknown",
            actor_id="a1",
        ),
    )
    return conn


def _insert_case(
    conn, id: str, amount_uah: float | None, tier: int = 1, url: str = "https://monobank.ua/jar/x"
) -> None:
    prov: dict = {}
    if amount_uah is not None:
        prov["amount_uah"] = {
            "source_url": url,
            "confidence": 0.95 if tier == 1 else 0.6,
            "tier": tier,
            "note": "",
        }
    case = Case(
        id=id,
        title="FPV збір",
        actor_id="a1",
        url=url,
        goal="military/fpv",
        amount_uah=amount_uah,
        provenance=prov,
        confidence_overall=prov["amount_uah"]["confidence"] if prov else 0.0,
    )
    store.upsert_case(conn, case)


def test_verify_single_case_auto_no_tier1(tmp_path):
    """Single case with tier-2 only → stays auto (judge irrelevant)."""
    conn = _setup_db(tmp_path)
    store.upsert_source(
        conn,
        Source(
            url="https://news.ua/art",
            type="news",
            tier=2,
            access="public",
            license="unknown",
            actor_id="a1",
        ),
    )
    _insert_case(conn, "c1", 1_000_000.0, tier=2, url="https://news.ua/art")

    def fake_judge(prompt):
        return {"supported": True, "confidence": 0.9, "reason": "ok"}

    summary = verify_cases(conn, _judge=fake_judge)
    cases = store.load_cases(conn)
    assert cases[0].verification_status == "auto"
    assert summary.get("auto", 0) == 1


def test_verify_single_case_tier1_cross_checked_then_verified(tmp_path):
    """Single case with tier-1 provenance → cross-checked, then judge upgrades → verified."""
    conn = _setup_db(tmp_path)
    _insert_case(conn, "c1", 1_000_000.0, tier=1)

    def fake_judge(prompt):
        return {"supported": True, "confidence": 0.9, "reason": "підтверджено"}

    summary = verify_cases(conn, _judge=fake_judge)
    cases = store.load_cases(conn)
    assert cases[0].verification_status == "verified"
    assert cases[0].verdict_reason == "підтверджено"
    assert summary.get("verified", 0) == 1


def test_verify_conflicting_cases_get_conflict_status(tmp_path):
    """Two cases with same dedup_key but amounts differ >10% → conflict."""
    conn = _setup_db(tmp_path)
    store.upsert_source(
        conn,
        Source(
            url="https://news.ua/art2",
            type="news",
            tier=2,
            access="public",
            license="unknown",
            actor_id="a1",
        ),
    )
    _insert_case(conn, "c1", 1_000_000.0, tier=1, url="https://monobank.ua/jar/x")
    # Second case with same URL but different amount — conflict
    case2 = Case(
        id="c2",
        title="FPV збір",
        actor_id="a1",
        url="https://monobank.ua/jar/x",  # same dedup_key
        goal="military/fpv",
        amount_uah=2_500_000.0,
        provenance={
            "amount_uah": {
                "source_url": "https://monobank.ua/jar/x",
                "confidence": 0.95,
                "tier": 1,
                "note": "",
            }
        },
        confidence_overall=0.95,
    )
    store.upsert_case(conn, case2)

    def fake_judge(prompt):
        return {"supported": True, "confidence": 0.9, "reason": "ok"}

    summary = verify_cases(conn, _judge=fake_judge)
    cases = store.load_cases(conn)
    statuses = {c.verification_status for c in cases}
    assert "conflict" in statuses
    assert summary.get("conflict", 0) >= 1


def test_verify_returns_summary_counts(tmp_path):
    """Summary dict counts cases by final status."""
    conn = _setup_db(tmp_path)
    _insert_case(conn, "c1", 1_000_000.0, tier=1)

    def fake_judge(prompt):
        return {"supported": True, "confidence": 0.95, "reason": "ok"}

    summary = verify_cases(conn, _judge=fake_judge)
    # Summary values are non-negative ints
    assert all(isinstance(v, int) and v >= 0 for v in summary.values())
    total = sum(summary.values())
    assert total == len(store.load_cases(conn))
