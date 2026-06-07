"""Тести блоку campaign_analytics у build_analytics (F5).

Перевіряємо, що build_analytics додає campaign_analytics зі своїми
KPI / крос-табами / осьовими підсумками, не ламаючи наявну аналітику.
"""
from __future__ import annotations

from fundrec import store
from fundrec.pipeline_analyze import build_analytics
from fundrec.schema import Actor, Campaign, CreativeAsset, Partner


def _setup(tmp_path):
    conn = store.connect(tmp_path / "ca.sqlite")
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id="a1", name="Притула", type="foundation"))
    return conn


def _camp(id, **kw):
    base = dict(
        id=id, actor_id="a1", title=f"camp {id}", goal="military", type="online_ad",
        channels=["facebook"], form_factor=["video"], tone=["urgency"],
        cta_type="donate_link", face="soldier", cadence="one_off",
    )
    base.update(kw)
    return Campaign(**base)


def test_build_analytics_keeps_existing_keys(tmp_path):
    conn = _setup(tmp_path)
    result = build_analytics(conn)
    # backward-compat: existing top-level analytics keys remain
    assert "kpis" in result
    assert "trends" in result
    assert "crosstabs" in result
    assert "generated_for_counts" in result


def test_campaign_analytics_block_present(tmp_path):
    conn = _setup(tmp_path)
    result = build_analytics(conn)
    assert "campaign_analytics" in result
    ca = result["campaign_analytics"]
    assert "kpis" in ca
    assert "crosstabs" in ca
    assert "axis_summaries" in ca


def test_campaign_analytics_kpis_shape(tmp_path):
    conn = _setup(tmp_path)
    store.upsert_partner(conn, Partner(id="p1", name="Спонсор", role="sponsor"))
    store.upsert_campaign(conn, _camp("k1", amount_uah=1000.0, spend=500.0))
    store.upsert_campaign(conn, _camp("k2", amount_uah=None))
    store.upsert_creative(conn, CreativeAsset(id="cr1", campaign_id="k1",
                                              platform="facebook", format="video"))
    result = build_analytics(conn)
    k = result["campaign_analytics"]["kpis"]
    assert k["n_campaigns"] == 2
    assert k["n_creatives"] == 1
    assert k["n_partners"] == 1
    assert "total_spend" in k


def test_campaign_analytics_total_spend_honest_null(tmp_path):
    """total_spend sums only non-null spend; None when none present."""
    conn = _setup(tmp_path)
    store.upsert_campaign(conn, _camp("k1", spend=None))
    store.upsert_campaign(conn, _camp("k2", spend=None))
    result = build_analytics(conn)
    assert result["campaign_analytics"]["kpis"]["total_spend"] is None


def test_campaign_analytics_crosstabs_keys(tmp_path):
    conn = _setup(tmp_path)
    store.upsert_campaign(conn, _camp("k1", amount_uah=1000.0,
                                      reach=10000.0, engagement=500.0))
    result = build_analytics(conn)
    ct = result["campaign_analytics"]["crosstabs"]
    for key in ("channel_volume", "format_engagement", "tone_virality",
                "face_volume", "goal_channel"):
        assert key in ct, f"missing crosstab {key}"
        for cell in ct[key]:
            assert "a" in cell and "b" in cell and "n" in cell


def test_campaign_analytics_axis_summaries_keys(tmp_path):
    conn = _setup(tmp_path)
    store.upsert_campaign(conn, _camp("k1", amount_uah=1000.0))
    result = build_analytics(conn)
    axs = result["campaign_analytics"]["axis_summaries"]
    for key in ("tone_amount", "cta_amount", "face_amount", "channel_amount"):
        assert key in axs, f"missing axis summary {key}"
        for row in axs[key]:
            assert "key" in row and "value" in row and "n" in row


def test_campaign_analytics_empty_safe(tmp_path):
    """No campaigns → block still well-formed."""
    conn = _setup(tmp_path)
    ca = build_analytics(conn)["campaign_analytics"]
    assert ca["kpis"]["n_campaigns"] == 0
    assert ca["crosstabs"]["channel_volume"] == []
    assert ca["axis_summaries"]["tone_amount"] == []
