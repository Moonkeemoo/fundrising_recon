"""Тести аналітики кампаній: campaign_crosstab + campaign_axis_summary.

Чисті функції над списками Campaign. Дисципліна: honest null (None-метрики
пропускаються, не як 0); кожна клітинка несе N; мульти-теги вносять внесок
у кожен тег.
"""
from __future__ import annotations

import pytest

from fundrec.analyze import campaign_axis_summary, campaign_crosstab
from fundrec.schema import Campaign


def _camp(
    id: str = "k1",
    *,
    type: str = "online_ad",
    cta_type: str | None = "donate_link",
    face: str | None = "soldier",
    cadence: str | None = "one_off",
    goal: str = "military",
    channels: list[str] | None = None,
    form_factor: list[str] | None = None,
    tone: list[str] | None = None,
    amount_uah: float | None = None,
    reach: float | None = None,
    engagement: float | None = None,
) -> Campaign:
    return Campaign(
        id=id,
        actor_id="a1",
        title=f"camp {id}",
        goal=goal,
        type=type,
        channels=channels or [],
        form_factor=form_factor or [],
        tone=tone or [],
        cta_type=cta_type,
        face=face,
        cadence=cadence,
        amount_uah=amount_uah,
        reach=reach,
        engagement=engagement,
    )


# ── campaign_crosstab: shape ─────────────────────────────────────────────────


def test_crosstab_shape_cells():
    camps = [_camp("k1", channels=["facebook"], tone=["urgency"], amount_uah=1000.0)]
    cells = campaign_crosstab(camps, axis_a="channels", axis_b="tone", metric="amount_uah")
    assert isinstance(cells, list)
    for cell in cells:
        assert set(cell) == {"a", "b", "value", "n"}


def test_crosstab_scalar_axes():
    camps = [
        _camp("k1", type="online_ad", cta_type="donate_link"),
        _camp("k2", type="online_ad", cta_type="jar"),
    ]
    cells = campaign_crosstab(camps, axis_a="type", axis_b="cta_type", metric="count")
    keys = {(c["a"], c["b"]) for c in cells}
    assert ("online_ad", "donate_link") in keys
    assert ("online_ad", "jar") in keys


def test_crosstab_goal_category_axis():
    camps = [_camp("k1", goal="military/fpv", channels=["telegram"])]
    cells = campaign_crosstab(camps, axis_a="goal_category", axis_b="channels", metric="count")
    assert cells[0]["a"] == "military"


# ── multi-valued contribution ────────────────────────────────────────────────


def test_crosstab_multivalued_contributes_each_tag():
    """channels=[facebook,instagram] → campaign feeds both cells."""
    camps = [_camp("k1", channels=["facebook", "instagram"], tone=["urgency"], amount_uah=500.0)]
    cells = campaign_crosstab(camps, axis_a="channels", axis_b="tone", metric="amount_uah")
    fb = next(c for c in cells if c["a"] == "facebook" and c["b"] == "urgency")
    ig = next(c for c in cells if c["a"] == "instagram" and c["b"] == "urgency")
    assert fb["n"] == 1
    assert ig["n"] == 1
    assert fb["value"] == pytest.approx(500.0)
    assert ig["value"] == pytest.approx(500.0)


def test_crosstab_both_axes_multivalued():
    camps = [
        _camp("k1", channels=["facebook", "instagram"], tone=["urgency", "humor"]),
    ]
    cells = campaign_crosstab(camps, axis_a="channels", axis_b="tone", metric="count")
    # 2 channels × 2 tones = 4 cells, each n=1
    assert len(cells) == 4
    assert all(c["n"] == 1 for c in cells)


# ── n correctness ────────────────────────────────────────────────────────────


def test_crosstab_n_counts_campaigns_behind_cell():
    camps = [
        _camp("k1", channels=["telegram"], tone=["urgency"]),
        _camp("k2", channels=["telegram"], tone=["urgency"]),
        _camp("k3", channels=["telegram"], tone=["humor"]),
    ]
    cells = campaign_crosstab(camps, axis_a="channels", axis_b="tone", metric="count")
    tg_urg = next(c for c in cells if c["a"] == "telegram" and c["b"] == "urgency")
    assert tg_urg["n"] == 2
    assert tg_urg["value"] == pytest.approx(2.0)


# ── honest null handling ─────────────────────────────────────────────────────


def test_crosstab_skips_none_metric_not_zero():
    """A None amount_uah must NOT be treated as 0; value reflects only non-null."""
    camps = [
        _camp("k1", channels=["web"], tone=["urgency"], amount_uah=1000.0),
        _camp("k2", channels=["web"], tone=["urgency"], amount_uah=None),
    ]
    cells = campaign_crosstab(camps, axis_a="channels", axis_b="tone", metric="amount_uah")
    cell = next(c for c in cells if c["a"] == "web" and c["b"] == "urgency")
    # n counts campaigns in cell (2), but value sums only the non-null one
    assert cell["n"] == 2
    assert cell["value"] == pytest.approx(1000.0)


def test_crosstab_all_none_metric_gives_null_value():
    camps = [
        _camp("k1", channels=["web"], tone=["urgency"], amount_uah=None),
        _camp("k2", channels=["web"], tone=["urgency"], amount_uah=None),
    ]
    cells = campaign_crosstab(camps, axis_a="channels", axis_b="tone", metric="amount_uah")
    cell = next(c for c in cells if c["a"] == "web" and c["b"] == "urgency")
    assert cell["value"] is None
    assert cell["n"] == 2


def test_crosstab_reach_and_engagement_metrics():
    camps = [
        _camp("k1", channels=["youtube"], tone=["heroism"], reach=10000.0, engagement=500.0),
    ]
    cells_r = campaign_crosstab(camps, axis_a="channels", axis_b="tone", metric="reach")
    cells_e = campaign_crosstab(camps, axis_a="channels", axis_b="tone", metric="engagement")
    assert cells_r[0]["value"] == pytest.approx(10000.0)
    assert cells_e[0]["value"] == pytest.approx(500.0)


def test_crosstab_empty_input():
    assert campaign_crosstab([], axis_a="channels", axis_b="tone", metric="count") == []


# ── campaign_axis_summary ────────────────────────────────────────────────────


def test_axis_summary_shape():
    camps = [_camp("k1", tone=["urgency"], amount_uah=1000.0)]
    rows = campaign_axis_summary(camps, axis="tone", metric="amount_uah")
    for r in rows:
        assert set(r) == {"key", "value", "n"}


def test_axis_summary_median_amount():
    """tone→median amount_uah for the style bars."""
    camps = [
        _camp("k1", tone=["urgency"], amount_uah=100.0),
        _camp("k2", tone=["urgency"], amount_uah=300.0),
        _camp("k3", tone=["urgency"], amount_uah=200.0),
    ]
    rows = campaign_axis_summary(camps, axis="tone", metric="amount_uah")
    urg = next(r for r in rows if r["key"] == "urgency")
    assert urg["value"] == pytest.approx(200.0)  # median of 100,200,300
    assert urg["n"] == 3


def test_axis_summary_multivalued_axis():
    camps = [_camp("k1", tone=["urgency", "humor"], amount_uah=400.0)]
    rows = campaign_axis_summary(camps, axis="tone", metric="amount_uah")
    keys = {r["key"] for r in rows}
    assert "urgency" in keys
    assert "humor" in keys


def test_axis_summary_count_metric():
    camps = [
        _camp("k1", channels=["facebook"]),
        _camp("k2", channels=["facebook"]),
    ]
    rows = campaign_axis_summary(camps, axis="channels", metric="count")
    fb = next(r for r in rows if r["key"] == "facebook")
    assert fb["value"] == pytest.approx(2.0)
    assert fb["n"] == 2


def test_axis_summary_honest_null():
    """None metric values excluded from median; n still counts campaigns."""
    camps = [
        _camp("k1", face="soldier", amount_uah=1000.0),
        _camp("k2", face="soldier", amount_uah=None),
    ]
    rows = campaign_axis_summary(camps, axis="face", metric="amount_uah")
    sol = next(r for r in rows if r["key"] == "soldier")
    assert sol["value"] == pytest.approx(1000.0)  # only the non-null
    assert sol["n"] == 2


def test_axis_summary_all_null_value_none():
    camps = [
        _camp("k1", face="soldier", amount_uah=None),
        _camp("k2", face="soldier", amount_uah=None),
    ]
    rows = campaign_axis_summary(camps, axis="face", metric="amount_uah")
    sol = next(r for r in rows if r["key"] == "soldier")
    assert sol["value"] is None
    assert sol["n"] == 2


def test_axis_summary_scalar_none_key_skipped():
    """Campaign with face=None contributes to no face key."""
    camps = [
        _camp("k1", face="soldier", amount_uah=1000.0),
        _camp("k2", face=None, amount_uah=2000.0),
    ]
    rows = campaign_axis_summary(camps, axis="face", metric="amount_uah")
    keys = {r["key"] for r in rows}
    assert keys == {"soldier"}


def test_axis_summary_empty():
    assert campaign_axis_summary([], axis="tone", metric="amount_uah") == []
