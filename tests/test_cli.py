import json
from pathlib import Path

from fundrec import cli, store

FIXTURE = {"title": "На FPV для 3-ї бригади", "amount": 125000000,
           "goal": 200000000, "currency": "UAH"}

def test_run_pipeline_end_to_end(tmp_path):
    seed = [{"case_id": "c1", "actor_id": "a1", "actor_name": "Банка",
             "actor_type": "individual", "jar_id": "abc123", "goal_hint": "military"}]
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")
    db_path = tmp_path / "t.sqlite"
    out_path = tmp_path / "cases.json"

    def fake_fetch(jar_id, **_):
        from fundrec.collect import monobank
        return monobank.parse_jar(jar_id, FIXTURE)

    def fake_complete(prompt):
        return {"title": "На FPV для 3-ї бригади", "goal": "military/fpv",
                "style": ["urgency"], "method": ["monobank_jar"], "year": 2026,
                "amount_uah": 1250000.0, "goal_amount": 2000000.0, "currency_raw": "UAH"}

    result = cli.run_pipeline(seed_path, db_path=db_path, out_path=out_path,
                              _fetch=fake_fetch, _complete=fake_complete)
    assert result["stored"] == 1
    assert result["problems"] == {}

    conn = store.connect(db_path)
    cases = store.load_cases(conn)
    assert len(cases) == 1
    assert cases[0].amount_uah == 1250000.0
    assert cases[0].provenance["amount_uah"]["tier"] == 1
    assert json.loads(out_path.read_text(encoding="utf-8"))["count"] == 1
