from fundrec import extract
from fundrec.schema import Source

SRC = Source(url="https://send.monobank.ua/jar/abc", type="structured",
             tier=1, access="public", license="unknown", actor_id="a1")
RAW = {"jar_id": "abc", "url": "https://send.monobank.ua/jar/abc",
       "title": "FPV для бригади", "amount_uah": 1250000.0,
       "goal_amount": 2000000.0, "currency_raw": "UAH"}

def test_build_prompt_includes_raw_and_vocab():
    p = extract.build_prompt(RAW, SRC)
    assert "FPV для бригади" in p
    assert "military" in p          # словник цілей у промпті
    assert "monobank_jar" in p

def test_parse_extraction_attaches_provenance_by_tier():
    llm_obj = {
        "title": "FPV для бригади", "goal": "military/fpv",
        "style": ["urgency"], "method": ["monobank_jar"], "year": 2026,
        "amount_uah": 1250000.0, "goal_amount": 2000000.0, "currency_raw": "UAH",
    }
    case = extract.parse_extraction(llm_obj, RAW, SRC, model="claude-opus-4-8", case_id="c1", actor_id="a1")
    assert case.id == "c1"
    assert case.goal == "military/fpv"
    assert case.amount_uah == 1250000.0
    # provenance автоматично на кожне непорожнє число, tier із джерела
    assert case.provenance["amount_uah"]["source_url"] == SRC.url
    assert case.provenance["amount_uah"]["tier"] == 1
    assert case.provenance["amount_uah"]["confidence"] == 0.95   # tier1 -> 0.95
    assert case.extracted_by_model == "claude-opus-4-8"
    assert case.verification_status == "auto"

def test_parse_extraction_null_number_gets_no_provenance():
    llm_obj = {"title": "X", "goal": "military", "style": [], "method": ["monobank_jar"],
               "amount_uah": None}
    case = extract.parse_extraction(llm_obj, RAW, SRC, model="m", case_id="c2", actor_id="a1")
    assert case.amount_uah is None
    assert "amount_uah" not in case.provenance

def test_extract_case_uses_injected_complete():
    def fake_complete(prompt: str) -> dict:
        return {"title": "FPV для бригади", "goal": "military/fpv",
                "style": ["urgency"], "method": ["monobank_jar"], "year": 2026,
                "amount_uah": 1250000.0}
    case = extract.extract_case(RAW, SRC, case_id="c1", actor_id="a1",
                                model="m", _complete=fake_complete)
    assert case.goal == "military/fpv"
    assert case.provenance["amount_uah"]["tier"] == 1
