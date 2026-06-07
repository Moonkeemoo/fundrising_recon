"""Unit 2 — classify_campaign: двоетапний класифікатор релевантності.

TDD: тести написані ДО реалізації. Жодного реального LLM — judge ін'єктується.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# build_relevance_prompt
# ---------------------------------------------------------------------------

def test_build_relevance_prompt_contains_title_and_text():
    from fundrec.relevance import build_relevance_prompt
    prompt = build_relevance_prompt("Збір на дрони", "Допоможіть нам зібрати кошти")
    assert "Збір на дрони" in prompt
    assert "Допоможіть нам зібрати кошти" in prompt


def test_build_relevance_prompt_requests_json():
    from fundrec.relevance import build_relevance_prompt
    prompt = build_relevance_prompt("test", "text")
    # Повинен містити інструкцію повернути JSON з is_campaign
    assert "is_campaign" in prompt
    assert "true" in prompt.lower() or "false" in prompt.lower()


def test_build_relevance_prompt_truncates_long_text():
    from fundrec.relevance import build_relevance_prompt
    long_text = "x" * 2000
    prompt = build_relevance_prompt("title", long_text)
    # Текст усічений до ~800 символів
    assert len(prompt) < 2500  # prompt сам по собі не надто довгий


# ---------------------------------------------------------------------------
# parse_relevance_verdict
# ---------------------------------------------------------------------------

def test_parse_relevance_verdict_true():
    from fundrec.relevance import parse_relevance_verdict
    assert parse_relevance_verdict({"is_campaign": True}) is True


def test_parse_relevance_verdict_false():
    from fundrec.relevance import parse_relevance_verdict
    assert parse_relevance_verdict({"is_campaign": False}) is False


def test_parse_relevance_verdict_missing_key_returns_false():
    from fundrec.relevance import parse_relevance_verdict
    assert parse_relevance_verdict({}) is False


def test_parse_relevance_verdict_garbage_value_returns_false():
    from fundrec.relevance import parse_relevance_verdict
    assert parse_relevance_verdict({"is_campaign": "yes"}) is False


def test_parse_relevance_verdict_null_returns_false():
    from fundrec.relevance import parse_relevance_verdict
    assert parse_relevance_verdict({"is_campaign": None}) is False


# ---------------------------------------------------------------------------
# classify_campaign: deterministic path
# ---------------------------------------------------------------------------

def _jar_raw():
    return {
        "title": "Збір на дрони",
        "text": "Банка: send.monobank.ua/jar/ABC123",
    }


def _topical_raw():
    return {
        "title": "Навчальний відео TCCC",
        "text": "Огляд тактичної аптечки для бійців. Стандарт MARCH.",
    }


def test_classify_campaign_is_fundraising_true_skips_judge():
    """Якщо is_fundraising(raw) -> True, judge НЕ викликається, повертає True."""
    from fundrec.relevance import classify_campaign
    from fundrec.schema import Campaign

    judge_called = {"n": 0}

    def judge(prompt):
        judge_called["n"] += 1
        return {"is_campaign": False}

    c = Campaign(id="c1", actor_id="a1", title="Збір", goal="military", type="mixed")
    result = classify_campaign(c, _jar_raw(), judge=judge)
    assert result is True
    assert judge_called["n"] == 0, "judge не повинен викликатись для is_fundraising=True"


def test_classify_campaign_ambiguous_judge_returns_false():
    """Топічний raw -> judge False -> classify повертає False."""
    from fundrec.relevance import classify_campaign
    from fundrec.schema import Campaign

    def judge(prompt):
        return {"is_campaign": False}

    c = Campaign(id="c1", actor_id="a1", title="TCCC відео", goal="military", type="mixed")
    result = classify_campaign(c, _topical_raw(), judge=judge)
    assert result is False


def test_classify_campaign_ambiguous_judge_returns_true():
    """Топічний raw -> judge True -> classify повертає True."""
    from fundrec.relevance import classify_campaign
    from fundrec.schema import Campaign

    def judge(prompt):
        return {"is_campaign": True}

    c = Campaign(id="c1", actor_id="a1", title="Збір на планшети", goal="military", type="mixed")
    result = classify_campaign(c, _topical_raw(), judge=judge)
    assert result is True


def test_classify_campaign_judge_called_once_for_ambiguous():
    """Judge викликається рівно 1 раз для ambiguous raw."""
    from fundrec.relevance import classify_campaign
    from fundrec.schema import Campaign

    calls = {"n": 0}

    def judge(prompt):
        calls["n"] += 1
        return {"is_campaign": False}

    c = Campaign(id="c1", actor_id="a1", title="тест", goal="military", type="mixed")
    classify_campaign(c, _topical_raw(), judge=judge)
    assert calls["n"] == 1
