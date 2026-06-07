from fundrec import store
from fundrec.schema import Actor, Source, Case

def _seed(conn):
    store.upsert_actor(conn, Actor(id="a1", name="Притула", type="foundation"))
    store.upsert_source(conn, Source(url="https://x", type="structured",
                                     tier=1, access="public", license="unknown", actor_id="a1"))

def test_init_and_upsert_case_roundtrip(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    _seed(conn)
    c = Case(id="c1", title="FPV", actor_id="a1", url="https://x",
             goal="military/fpv", style=["urgency"], method=["monobank_jar"],
             year=2026, amount_uah=500000.0,
             provenance={"amount_uah": {"source_url": "https://x", "confidence": 0.9,
                                        "tier": 1, "note": ""}})
    store.upsert_case(conn, c)
    loaded = store.load_cases(conn)
    assert len(loaded) == 1
    assert loaded[0] == c

def test_upsert_is_idempotent(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    _seed(conn)
    c = Case(id="c1", title="FPV", actor_id="a1", url="https://x", goal="military")
    store.upsert_case(conn, c)
    c.title = "FPV (оновлено)"
    store.upsert_case(conn, c)
    loaded = store.load_cases(conn)
    assert len(loaded) == 1
    assert loaded[0].title == "FPV (оновлено)"
