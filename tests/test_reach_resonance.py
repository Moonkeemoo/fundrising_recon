"""Unit — reach-резонанс: campaign_handle, channel_baselines, reach_resonance.

Дисципліна: None≠0; reach_resonance = reach / медіана каналу; honest null
де даних немає (handle відсутній / канал без бази / reach відсутній).
"""
from __future__ import annotations

import pytest

from fundrec.analyze import (
    campaign_handle,
    channel_baselines,
    reach_resonance,
    reach_resonance_axis_summary,
)
from fundrec.schema import Campaign, Post


def _camp(
    id: str = "k1",
    *,
    reach: float | None = None,
    reach_url: str | None = None,
    eng_url: str | None = None,
) -> Campaign:
    prov: dict = {}
    if reach_url is not None:
        prov["reach"] = {"source_url": reach_url}
    if eng_url is not None:
        prov["engagement"] = {"source_url": eng_url}
    return Campaign(
        id=id, actor_id="a1", title="c", goal="military", type="online_ad",
        reach=reach, provenance=prov,
    )


def _post(channel: str | None, views: int | None, id: str = "p") -> Post:
    return Post(id=id, channel=channel, views=views)


# ── campaign_handle ──────────────────────────────────────────────────────────


def test_handle_from_reach_provenance():
    c = _camp(reach_url="https://t.me/prytulafoundation/123")
    assert campaign_handle(c) == "prytulafoundation"


def test_handle_from_s_url():
    c = _camp(reach_url="https://t.me/s/ssternenko/45")
    assert campaign_handle(c) == "ssternenko"


def test_handle_falls_back_to_engagement_provenance():
    c = _camp(eng_url="https://t.me/dignitas_fund/7")
    assert campaign_handle(c) == "dignitas_fund"


def test_handle_reach_takes_priority():
    c = _camp(reach_url="https://t.me/first/1", eng_url="https://t.me/second/2")
    assert campaign_handle(c) == "first"


def test_handle_none_when_no_provenance():
    assert campaign_handle(_camp()) is None


def test_handle_none_when_not_telegram_url():
    c = _camp(reach_url="https://youtube.com/watch?v=abc")
    assert campaign_handle(c) is None


# ── channel_baselines ────────────────────────────────────────────────────────


def test_baselines_median_per_channel():
    posts = [
        _post("chA", 100, "1"),
        _post("chA", 300, "2"),
        _post("chA", 200, "3"),
    ]
    b = channel_baselines(posts)
    assert b["chA"] == pytest.approx(200.0)  # median(100,200,300)


def test_baselines_skips_channels_below_min_posts():
    posts = [
        _post("chA", 100, "1"),
        _post("chA", 200, "2"),  # only 2 → below default min_posts=3
        _post("chB", 50, "3"),
        _post("chB", 60, "4"),
        _post("chB", 70, "5"),
    ]
    b = channel_baselines(posts)
    assert "chA" not in b
    assert "chB" in b


def test_baselines_ignores_null_views():
    posts = [
        _post("chA", None, "1"),
        _post("chA", 100, "2"),
        _post("chA", 200, "3"),
        _post("chA", 300, "4"),
    ]
    b = channel_baselines(posts)
    # лише 3 non-null views → median(100,200,300)=200
    assert b["chA"] == pytest.approx(200.0)


def test_baselines_custom_min_posts():
    posts = [_post("chA", 100, "1"), _post("chA", 200, "2")]
    b = channel_baselines(posts, min_posts=2)
    assert b["chA"] == pytest.approx(150.0)


def test_baselines_ignores_null_channel():
    posts = [_post(None, 100, "1"), _post(None, 200, "2"), _post(None, 300, "3")]
    assert channel_baselines(posts) == {}


# ── reach_resonance ──────────────────────────────────────────────────────────


def test_reach_resonance_basic():
    c = _camp(reach=2000.0, reach_url="https://t.me/chA/1")
    assert reach_resonance(c, {"chA": 1000.0}) == pytest.approx(2.0)


def test_reach_resonance_below_one():
    c = _camp(reach=500.0, reach_url="https://t.me/chA/1")
    assert reach_resonance(c, {"chA": 1000.0}) == pytest.approx(0.5)


def test_reach_resonance_none_when_reach_none():
    c = _camp(reach=None, reach_url="https://t.me/chA/1")
    assert reach_resonance(c, {"chA": 1000.0}) is None


def test_reach_resonance_none_when_reach_zero():
    c = _camp(reach=0.0, reach_url="https://t.me/chA/1")
    assert reach_resonance(c, {"chA": 1000.0}) is None


def test_reach_resonance_none_when_no_handle():
    c = _camp(reach=1000.0)
    assert reach_resonance(c, {"chA": 1000.0}) is None


def test_reach_resonance_none_when_handle_not_in_baselines():
    c = _camp(reach=1000.0, reach_url="https://t.me/chZ/1")
    assert reach_resonance(c, {"chA": 1000.0}) is None


def test_reach_resonance_none_when_baseline_zero():
    c = _camp(reach=1000.0, reach_url="https://t.me/chA/1")
    assert reach_resonance(c, {"chA": 0.0}) is None


# ── reach_resonance_axis_summary ─────────────────────────────────────────────


def _camp_axis(id, *, channels, reach, handle):
    return Campaign(
        id=id, actor_id="a1", title="c", goal="military", type="online_ad",
        channels=channels, reach=reach,
        provenance={"reach": {"source_url": f"https://t.me/{handle}/1"}},
    )


def test_axis_summary_median_resonance():
    baselines = {"chA": 1000.0}
    camps = [
        _camp_axis("k1", channels=["telegram"], reach=500.0, handle="chA"),   # 0.5
        _camp_axis("k2", channels=["telegram"], reach=1500.0, handle="chA"),  # 1.5
    ]
    rows = reach_resonance_axis_summary(camps, axis="channels", baselines=baselines)
    tg = next(r for r in rows if r["key"] == "telegram")
    assert tg["value"] == pytest.approx(1.0)  # median(0.5, 1.5)
    assert tg["n"] == 2


def test_axis_summary_none_when_no_signal():
    """Жодного reach_resonance під ключем → value=None (honest null), n рахує всіх."""
    camps = [
        Campaign(id="k1", actor_id="a1", title="c", goal="military",
                 type="online_ad", channels=["telegram"], reach=None),
    ]
    rows = reach_resonance_axis_summary(camps, axis="channels", baselines={"chA": 1000.0})
    tg = next(r for r in rows if r["key"] == "telegram")
    assert tg["value"] is None
    assert tg["n"] == 1
