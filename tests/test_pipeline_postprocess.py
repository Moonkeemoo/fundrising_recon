"""Unit 2 — pipeline.run_postprocess: інтеграційний тест пайплайну.

TDD: написано ДО реалізації pipeline.py.
Герметичний: tmp SQLite + tmp raw_dir + ін'єктовані judge/render/complete.
Реальна БД data/fundrec.sqlite не торкається ніколи.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path


from fundrec import store
from fundrec.schema import Actor, Campaign


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    store.init_db(conn)
    return conn


def _actor(id: str = "a1") -> Actor:
    return Actor(id=id, name=f"Actor {id}", type="foundation")


def _campaign(
    id: str,
    title: str = "Збір на дрони",
    actor_id: str = "a1",
    provenance: dict | None = None,
    is_campaign: bool | None = None,
    channels: list[str] | None = None,
) -> Campaign:
    return Campaign(
        id=id,
        actor_id=actor_id,
        title=title,
        goal="military",
        type="jar",
        channels=channels or [],
        provenance=provenance or {},
        is_campaign=is_campaign,
    )


def _raw_file(raw_dir: Path, source_url: str, text: str = "", jar_id: str | None = None) -> None:
    """Записує raw JSON файл — ключ = sha256[:16] source_url."""
    import hashlib
    file_id = hashlib.sha256(source_url.encode()).hexdigest()[:16]
    links = [f"https://send.monobank.ua/jar/{jar_id}"] if jar_id else []
    data = {"source_url": source_url, "text": text, "links": links, "title": "тест"}
    (raw_dir / f"{file_id}.json").write_text(json.dumps(data), encoding="utf-8")


def _fake_judge(is_campaign: bool):
    def judge(prompt: str) -> dict:
        return {"is_campaign": is_campaign}
    return judge


def _fake_render(amount: float | None = 100_000.0):
    def render(jar_id: str) -> dict | None:
        if amount is None:
            return None
        return {"amount_uah": amount, "title": f"jar {jar_id}"}
    return render


def _fake_complete(exported: list):
    def complete(conn, out_path) -> int:
        exported.append(out_path)
        return 1
    return complete


# ---------------------------------------------------------------------------
# Import check
# ---------------------------------------------------------------------------


def test_pipeline_module_importable():
    from fundrec import pipeline  # noqa: F401


def test_run_postprocess_importable():
    from fundrec.pipeline import run_postprocess  # noqa: F401


# ---------------------------------------------------------------------------
# run_postprocess: summary keys present
# ---------------------------------------------------------------------------


def test_run_postprocess_returns_summary_keys():
    """run_postprocess повертає dict зі всіма очікуваними ключами."""
    from fundrec.pipeline import run_postprocess

    conn = _init_conn()
    store.upsert_actor(conn, _actor("a1"))
    store.upsert_campaign(conn, _campaign("c1"))

    with tempfile.TemporaryDirectory() as raw_tmp:
        result = run_postprocess(
            conn,
            Path(raw_tmp),
            judge=_fake_judge(True),
            render=_fake_render(None),
            complete=_fake_complete([]),
        )

    assert "classify" in result
    assert "enrich_text" in result
    assert "enrich_jars" in result
    assert "dedup" in result


# ---------------------------------------------------------------------------
# run_postprocess: classify sets is_campaign
# ---------------------------------------------------------------------------


def test_run_postprocess_classify_sets_is_campaign():
    """classify_relevance_db викликається і встановлює is_campaign=True."""
    from fundrec.pipeline import run_postprocess

    conn = _init_conn()
    store.upsert_actor(conn, _actor("a1"))
    # Кампанія з is_campaign=None; raw має сильний сигнал збору
    prov = {"campaign": {"source_url": "https://example.com/post1"}}
    c = _campaign("c1", provenance=prov, is_campaign=None)
    store.upsert_campaign(conn, c)

    with tempfile.TemporaryDirectory() as raw_tmp:
        raw_dir = Path(raw_tmp)
        _raw_file(raw_dir, "https://example.com/post1", text="задонат на ЗСУ")

        run_postprocess(
            conn,
            raw_dir,
            judge=_fake_judge(True),
            render=_fake_render(None),
            complete=_fake_complete([]),
        )

    campaigns = store.load_campaigns(conn)
    assert campaigns[0].is_campaign is True


# ---------------------------------------------------------------------------
# run_postprocess: dedup merges duplicates AND preserves is_campaign
# ---------------------------------------------------------------------------


def test_run_postprocess_dedup_merges_and_preserves_is_campaign():
    """Ключова регресія: dedup зливає дублікати і is_campaign зберігається."""
    from fundrec.pipeline import run_postprocess

    conn = _init_conn()
    store.upsert_actor(conn, _actor("a1"))

    # Два дублікати — спільний jar_id → зіллються
    jar_prov = {
        "amount_uah": {
            "source_url": "https://send.monobank.ua/jar/TESTJAR999",
            "confidence": 0.95,
            "tier": 1,
            "note": "jar",
        }
    }
    c1 = _campaign("c1", provenance=jar_prov, is_campaign=True, channels=["telegram"])
    c2 = _campaign("c2", provenance=jar_prov, is_campaign=None, channels=["facebook"])
    store.upsert_campaign(conn, c1)
    store.upsert_campaign(conn, c2)

    with tempfile.TemporaryDirectory() as raw_tmp:
        run_postprocess(
            conn,
            Path(raw_tmp),
            judge=_fake_judge(True),
            render=_fake_render(None),
            complete=_fake_complete([]),
        )

    remaining = store.load_campaigns(conn)
    assert len(remaining) == 1, f"Expected 1 campaign after dedup, got {len(remaining)}"
    # Ключова регресія: is_campaign зберігається після dedup
    assert remaining[0].is_campaign is True, (
        f"is_campaign should be True after dedup merge, got {remaining[0].is_campaign}"
    )


# ---------------------------------------------------------------------------
# run_postprocess: order — classify BEFORE dedup (is_campaign присутній у survivor)
# ---------------------------------------------------------------------------


def test_run_postprocess_classify_before_dedup_survivor_has_flag():
    """classify відбувається ДО dedup: survivor кампанія має is_campaign встановлений classify."""
    from fundrec.pipeline import run_postprocess

    conn = _init_conn()
    store.upsert_actor(conn, _actor("a1"))

    # Один raw файл для c1; c2 не має raw → is_campaign залишається None після classify
    prov_shared_jar = {
        "amount_uah": {
            "source_url": "https://send.monobank.ua/jar/SHARED_ORDER_JAR",
            "confidence": 0.95,
            "tier": 1,
        },
        "campaign": {"source_url": "https://example.com/post_c1"},
    }
    c1 = _campaign("c1", provenance=prov_shared_jar, is_campaign=None)
    c2 = _campaign("c2", provenance={
        "amount_uah": prov_shared_jar["amount_uah"],
    }, is_campaign=None)
    store.upsert_campaign(conn, c1)
    store.upsert_campaign(conn, c2)

    with tempfile.TemporaryDirectory() as raw_tmp:
        raw_dir = Path(raw_tmp)
        # Тільки c1 має raw (з сигналом збору)
        _raw_file(raw_dir, "https://example.com/post_c1", text="збір коштів на ЗСУ реквізити")

        run_postprocess(
            conn,
            raw_dir,
            judge=_fake_judge(True),
            render=_fake_render(None),
            complete=_fake_complete([]),
        )

    remaining = store.load_campaigns(conn)
    # Після dedup — один survivor; has is_campaign=True (з c1 через classify)
    assert len(remaining) == 1
    assert remaining[0].is_campaign is True


# ---------------------------------------------------------------------------
# run_postprocess: --no-classify flag
# ---------------------------------------------------------------------------


def test_run_postprocess_no_classify_skips_classification():
    """do_classify=False → classify не змінює is_campaign."""
    from fundrec.pipeline import run_postprocess

    conn = _init_conn()
    store.upsert_actor(conn, _actor("a1"))
    prov = {"campaign": {"source_url": "https://example.com/post99"}}
    c = _campaign("c1", provenance=prov, is_campaign=None)
    store.upsert_campaign(conn, c)

    with tempfile.TemporaryDirectory() as raw_tmp:
        raw_dir = Path(raw_tmp)
        _raw_file(raw_dir, "https://example.com/post99", text="задонат на ЗСУ")

        run_postprocess(
            conn,
            raw_dir,
            judge=_fake_judge(True),
            render=_fake_render(None),
            complete=_fake_complete([]),
            do_classify=False,
        )

    campaigns = store.load_campaigns(conn)
    # is_campaign залишається None — classify пропущено
    assert campaigns[0].is_campaign is None


# ---------------------------------------------------------------------------
# run_postprocess: complete callback called
# ---------------------------------------------------------------------------


def test_run_postprocess_calls_complete():
    """complete callback викликається наприкінці."""
    from fundrec.pipeline import run_postprocess

    conn = _init_conn()
    store.upsert_actor(conn, _actor("a1"))
    store.upsert_campaign(conn, _campaign("c1"))

    called = []

    def _complete(conn_, out_path):
        called.append(out_path)
        return 0

    with tempfile.TemporaryDirectory() as raw_tmp:
        run_postprocess(
            conn,
            Path(raw_tmp),
            judge=_fake_judge(True),
            render=_fake_render(None),
            complete=_complete,
        )

    assert len(called) == 1


# ---------------------------------------------------------------------------
# CLI: python -m fundrec.pipeline --help smoke test
# ---------------------------------------------------------------------------


def test_pipeline_cli_help():
    """python -m fundrec.pipeline --help не падає."""
    import subprocess
    import sys
    result = subprocess.run(
        [sys.executable, "-m", "fundrec.pipeline", "--help"],
        capture_output=True,
        timeout=10,
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 0
    output = result.stdout.decode("utf-8", errors="replace")
    assert "--db" in output or "pipeline" in output
