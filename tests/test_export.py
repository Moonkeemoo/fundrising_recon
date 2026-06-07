import json

from fundrec import export, store
from fundrec.schema import Actor, Case, Source

def test_export_writes_cases_json(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id="a1", name="Притула", type="foundation"))
    store.upsert_source(conn, Source(url="https://x", type="structured", tier=1,
                                     access="public", license="unknown", actor_id="a1"))
    store.upsert_case(conn, Case(id="c1", title="FPV", actor_id="a1", url="https://x",
                                 goal="military", style=["urgency"], method=["monobank_jar"]))
    out = tmp_path / "cases.json"
    n = export.export_cases(conn, out)
    assert n == 1
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["count"] == 1
    assert data["cases"][0]["id"] == "c1"
    assert data["cases"][0]["style"] == ["urgency"]
