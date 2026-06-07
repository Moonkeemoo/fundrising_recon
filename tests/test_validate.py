from fundrec.schema import Case
from fundrec import validate

def _valid_case(**over):
    base = dict(
        id="c1", title="FPV", actor_id="a1", url="https://x",
        goal="military/fpv", style=["urgency"], method=["monobank_jar"],
        year=2026, amount_uah=500000.0,
        provenance={"amount_uah": {"source_url": "https://x", "confidence": 0.9,
                                   "tier": 1, "note": ""}},
    )
    base.update(over)
    return Case(**base)

def test_clean_case_has_no_problems():
    assert validate.validate_case(_valid_case()) == []

def test_amount_without_provenance_flagged():
    c = _valid_case(provenance={})
    problems = validate.validate_case(c)
    assert any("provenance" in p for p in problems)

def test_year_out_of_range_flagged():
    assert any("year" in p for p in validate.validate_case(_valid_case(year=2019)))

def test_negative_amount_flagged():
    assert any("amount_uah" in p for p in validate.validate_case(_valid_case(amount_uah=-5.0)))

def test_unknown_goal_category_flagged():
    assert any("goal" in p for p in validate.validate_case(_valid_case(goal="weapons/x")))

def test_unknown_style_tag_flagged():
    assert any("style" in p for p in validate.validate_case(_valid_case(style=["funny"])))
