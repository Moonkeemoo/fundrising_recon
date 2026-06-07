from fundrec import schema
from fundrec.schema import Actor, Source, Case

def test_vocabularies_present():
    assert "military" in schema.GOAL_CATEGORIES
    assert "monobank_jar" in schema.METHOD_TAGS
    assert "gamification" in schema.STYLE_TAGS
    assert "foundation" in schema.ACTOR_TYPES
    assert schema.VERIFICATION == {"auto", "cross-checked", "verified", "conflict"}

def test_case_roundtrips_through_dict():
    c = Case(
        id="c1", title="FPV для бригади", actor_id="a1",
        url="https://send.monobank.ua/jar/abc",
        goal="military/fpv", style=["urgency"], method=["monobank_jar"],
        year=2026, amount_uah=1000000.0,
        provenance={"amount_uah": {"source_url": "https://send.monobank.ua/jar/abc",
                                   "confidence": 0.95, "tier": 1, "note": "jar json"}},
    )
    d = schema.case_to_dict(c)
    assert d["style"] == ["urgency"]
    c2 = schema.case_from_dict(d)
    assert c2 == c

def test_actor_and_source_construct():
    a = Actor(id="a1", name="Сергій Притула", type="foundation")
    s = Source(url="https://prytulafoundation.org", type="structured", tier=1,
               access="public", license="unknown", actor_id="a1")
    assert a.links == []
    assert s.tier == 1
