"""Unit 4 — radar блок у build_analytics; engagement_rate/rel_resonance в export.

Тести:
- build_analytics додає radar блок із what_works_now і momentum
- radar.now = max parse_campaign_date (детермінований)
- radar.what_works_now: ключі channel/tone/form_factor/goal
- radar.momentum: ключі goal/channel/tone
- export_cases збагачує кампанії engagement_rate та rel_resonance
- backward-compat: існуючі ключі не зруйновані
"""
from __future__ import annotations

import json

import pytest

from fundrec import store
from fundrec.export import export_cases
from fundrec.pipeline_analyze import build_analytics
from fundrec.schema import Actor, Campaign, Post


def _actor(id: str = "a1") -> Actor:
    return Actor(id=id, name="Test Actor", type="individual")


def _camp(
    id: str,
    *,
    actor_id: str = "a1",
    date_start: str | None = None,
    channels: list[str] | None = None,
    tone: list[str] | None = None,
    goal: str = "military",
    reach: float | None = None,
    engagement: float | None = None,
    handle: str | None = None,
) -> Campaign:
    prov = {}
    if handle is not None:
        prov["reach"] = {"source_url": f"https://t.me/{handle}/1"}
    return Campaign(
        id=id,
        actor_id=actor_id,
        title=f"camp {id}",
        goal=goal,
        type="online_ad",
        date_start=date_start,
        channels=channels or ["telegram"],
        tone=tone or ["urgency"],
        form_factor=["video"],
        reach=reach,
        engagement=engagement,
        provenance=prov,
    )


def _seed_baseline(conn, handle: str, median: float):
    """Створює 3 пости каналу `handle` з views=median → channel_baselines дає median."""
    for i in range(3):
        store.upsert_post(conn, Post(
            id=f"p_{handle}_{i}", channel=handle, views=int(median),
            source_url=f"https://t.me/{handle}/{i}",
        ))


def _setup(tmp_path):
    conn = store.connect(tmp_path / "test.sqlite")
    store.init_db(conn)
    store.upsert_actor(conn, _actor())
    return conn


# ── radar блок присутній ──────────────────────────────────────────────────────


def test_build_analytics_has_radar_block(tmp_path):
    conn = _setup(tmp_path)
    result = build_analytics(conn)
    assert "radar" in result


def test_radar_block_shape_no_campaigns(tmp_path):
    """При порожній БД radar присутній (порожні списки)."""
    conn = _setup(tmp_path)
    radar = build_analytics(conn)["radar"]
    assert "what_works_now" in radar
    assert "momentum" in radar


def test_radar_what_works_now_has_expected_axes(tmp_path):
    conn = _setup(tmp_path)
    store.upsert_campaign(conn, _camp("k1", date_start="2024-02-10",
                                      reach=1000.0, engagement=200.0))
    store.upsert_campaign(conn, _camp("k2", date_start="2024-02-08",
                                      reach=1000.0, engagement=200.0))
    radar = build_analytics(conn)["radar"]
    wwn = radar["what_works_now"]
    for axis in ("channel", "tone", "form_factor", "goal"):
        assert axis in wwn, f"missing axis {axis} in what_works_now"


def test_radar_momentum_has_expected_axes(tmp_path):
    conn = _setup(tmp_path)
    radar = build_analytics(conn)["radar"]
    mom = radar["momentum"]
    for axis in ("goal", "channel", "tone"):
        assert axis in mom, f"missing axis {axis} in momentum"


def test_radar_now_is_max_campaign_date(tmp_path):
    """radar.now = max parse_campaign_date серед кампаній."""
    conn = _setup(tmp_path)
    store.upsert_campaign(conn, _camp("k1", date_start="2024-01-10"))
    store.upsert_campaign(conn, _camp("k2", date_start="2024-03-20"))
    store.upsert_campaign(conn, _camp("k3", date_start="2024-02-15"))
    radar = build_analytics(conn)["radar"]
    assert radar["now"] == "2024-03-20"


def test_radar_now_fallback_when_no_dates(tmp_path):
    """Якщо жодної дати — radar.now встановлюється (рядок, не відсутній)."""
    conn = _setup(tmp_path)
    # camp without date
    store.upsert_campaign(conn, Campaign(
        id="k1", actor_id="a1", title="camp", goal="military", type="online_ad",
    ))
    radar = build_analytics(conn)["radar"]
    assert "now" in radar
    assert isinstance(radar["now"], str)


# ── backward-compat ───────────────────────────────────────────────────────────


def test_build_analytics_existing_keys_intact(tmp_path):
    conn = _setup(tmp_path)
    result = build_analytics(conn)
    for key in ("kpis", "trends", "crosstabs", "generated_for_counts", "campaign_analytics"):
        assert key in result, f"missing key {key}"


# ── export: engagement_rate та rel_resonance в кампаніях ──────────────────────


def test_export_campaigns_have_engagement_rate(tmp_path):
    conn = _setup(tmp_path)
    store.upsert_campaign(conn, _camp("k1", reach=1000.0, engagement=200.0))
    out = tmp_path / "cases.json"
    export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    camp = data["campaigns"][0]
    assert "engagement_rate" in camp
    assert camp["engagement_rate"] == pytest.approx(0.2)


def test_export_campaigns_have_rel_resonance(tmp_path):
    """rel_resonance = reach / медіана каналу (з постів)."""
    conn = _setup(tmp_path)
    _seed_baseline(conn, "chA", 1000.0)
    store.upsert_campaign(conn, _camp("k1", reach=1000.0, handle="chA"))
    out = tmp_path / "cases.json"
    export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    camp = data["campaigns"][0]
    assert "rel_resonance" in camp
    assert camp["rel_resonance"] == pytest.approx(1.0)
    # явний alias reach_resonance дублює rel_resonance
    assert camp["reach_resonance"] == pytest.approx(1.0)


def test_export_campaigns_engagement_rate_none_when_no_reach(tmp_path):
    conn = _setup(tmp_path)
    store.upsert_campaign(conn, _camp("k1", reach=None, engagement=200.0))
    out = tmp_path / "cases.json"
    export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    camp = data["campaigns"][0]
    assert camp["engagement_rate"] is None


def test_export_campaigns_rel_resonance_none_when_no_baseline(tmp_path):
    """Немає бази каналу (немає постів) → rel_resonance=None (honest null)."""
    conn = _setup(tmp_path)
    store.upsert_campaign(conn, _camp("k1", reach=1000.0, handle="chMissing"))
    out = tmp_path / "cases.json"
    export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    camp = data["campaigns"][0]
    assert camp["rel_resonance"] is None


def test_export_campaigns_rel_resonance_above_one(tmp_path):
    """Кампанія з reach > медіани каналу → rel > 1."""
    conn = _setup(tmp_path)
    _seed_baseline(conn, "chA", 1000.0)
    store.upsert_campaign(conn, _camp("k1", reach=500.0, handle="chA"))   # 0.5
    store.upsert_campaign(conn, _camp("k2", reach=1500.0, handle="chA"))  # 1.5
    out = tmp_path / "cases.json"
    export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    camps_by_id = {c["id"]: c for c in data["campaigns"]}
    assert camps_by_id["k2"]["rel_resonance"] == pytest.approx(1.5)
    assert camps_by_id["k1"]["rel_resonance"] == pytest.approx(0.5)


def test_export_has_radar_in_analytics(tmp_path):
    """export включає radar блок у analytics."""
    conn = _setup(tmp_path)
    store.upsert_campaign(conn, _camp("k1", date_start="2024-02-10",
                                      reach=1000.0, engagement=200.0))
    out = tmp_path / "cases.json"
    export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "radar" in data["analytics"]


def test_export_backward_compat_keys(tmp_path):
    """Існуючі ключі export не зруйновані."""
    conn = _setup(tmp_path)
    out = tmp_path / "cases.json"
    export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    for key in ("count", "cases", "analytics", "campaigns", "creatives", "partners"):
        assert key in data
