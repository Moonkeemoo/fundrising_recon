"""Тести для Unit 1: normalize_title, title_similarity, fuzzy_merge_groups (dedup.py).

TDD: тести написані ДО реалізації — спочатку червоні, потім зелені.
"""
from __future__ import annotations

import pytest

from fundrec.dedup import fuzzy_merge_groups, normalize_title, title_similarity
from fundrec.schema import Campaign


# ---------------------------------------------------------------------------
# Хелпери
# ---------------------------------------------------------------------------


def _make_campaign(
    id: str,
    actor_id: str,
    title: str,
    goal: str = "military",
    provenance: dict | None = None,
    amount_uah: float | None = None,
) -> Campaign:
    return Campaign(
        id=id,
        actor_id=actor_id,
        title=title,
        goal=goal,
        type="jar",
        provenance=provenance or {},
        amount_uah=amount_uah,
    )


def _jar_prov(jar_id: str, amount: float = 1_000_000.0) -> dict:
    return {
        "amount_uah": {
            "source_url": f"https://send.monobank.ua/jar/{jar_id}",
            "confidence": 0.95,
            "tier": 1,
            "note": "jar",
        }
    }


# ---------------------------------------------------------------------------
# normalize_title
# ---------------------------------------------------------------------------


def test_normalize_title_lowercase():
    assert normalize_title("ЗБІР НА ДРОНИ") == "збір на дрони"


def test_normalize_title_strips_emojis():
    result = normalize_title("🔥 Збір на дрони 🚁")
    assert "🔥" not in result
    assert "🚁" not in result
    assert "збір" in result
    assert "дрони" in result


def test_normalize_title_strips_punctuation():
    result = normalize_title("Збір! На — дрони...")
    assert "!" not in result
    assert "—" not in result
    assert "." not in result


def test_normalize_title_strips_currency_digits():
    """Числа та символи валюти видаляються (шумові токени)."""
    result = normalize_title("Збір 1 000 000 ₴ на дрони")
    assert "₴" not in result
    assert "000" not in result
    assert "збір" in result
    assert "дрони" in result


def test_normalize_title_collapses_whitespace():
    result = normalize_title("Збір   на    дрони")
    assert "  " not in result


def test_normalize_title_empty_returns_empty():
    assert normalize_title("") == ""


def test_normalize_title_strips_million_abbrev():
    """Скорочення 'млн' та цифри не впливають на суттєві слова."""
    result = normalize_title("Збір 1 млн грн на комплектуючі")
    # млн/грн — числові шумові токени; суттєві слова лишаються
    assert "комплектуючі" in result


# ---------------------------------------------------------------------------
# title_similarity
# ---------------------------------------------------------------------------


def test_title_similarity_identical_returns_one():
    t = "Збір на дрони підрозділу"
    assert title_similarity(t, t) == pytest.approx(1.0)


def test_title_similarity_empty_strings_returns_zero():
    assert title_similarity("", "") == pytest.approx(0.0)


def test_title_similarity_one_empty_returns_zero():
    assert title_similarity("Збір на дрони", "") == pytest.approx(0.0)


def test_title_similarity_feniksdpsu_real_example():
    """Реальний приклад: feniksdpsu /1997 vs /1994 → схожість ≥ 0.6."""
    t1 = "Збір 1 000 000 ₴ на комплектуючі для дронів підрозділу"
    t2 = "Збір 1 млн грн на комплектуючі для дронів — підрозділ…"
    sim = title_similarity(t1, t2)
    assert sim >= 0.6, f"Очікувана схожість ≥ 0.6, отримано {sim:.3f}"


def test_title_similarity_different_topics_low():
    """Різні збори того самого актора → схожість < 0.6."""
    t1 = "Збір на авто для бойового підрозділу"
    t2 = "Збір на дрони FPV для штурму"
    sim = title_similarity(t1, t2)
    assert sim < 0.6, f"Очікувана схожість < 0.6, отримано {sim:.3f}"


def test_title_similarity_symmetric():
    t1 = "Збір на дрони підрозділу"
    t2 = "Збір на комплектуючі для дронів"
    assert title_similarity(t1, t2) == pytest.approx(title_similarity(t2, t1))


def test_title_similarity_partial_overlap():
    """Часткове перекриття → значення між 0 і 1."""
    t1 = "Збір на дрони для бригади"
    t2 = "Збір на дрони та броню для штурму"
    sim = title_similarity(t1, t2)
    assert 0.0 < sim < 1.0


# ---------------------------------------------------------------------------
# fuzzy_merge_groups
# ---------------------------------------------------------------------------


def test_fuzzy_merge_groups_same_actor_similar_title_same_group():
    """Один актор + схожі назви → одна спільна група."""
    t1 = "Збір 1 000 000 ₴ на комплектуючі для дронів підрозділу"
    t2 = "Збір 1 млн грн на комплектуючі для дронів — підрозділ…"
    c1 = _make_campaign("c1", actor_id="feniksdpsu", title=t1, goal="military")
    c2 = _make_campaign("c2", actor_id="feniksdpsu", title=t2, goal="military")

    groups = fuzzy_merge_groups([c1, c2])
    assert len(groups) == 1
    assert len(groups[0]) == 2


def test_fuzzy_merge_groups_same_actor_dissimilar_titles_separate():
    """Один актор + різні збори → окремі групи."""
    c1 = _make_campaign("c1", actor_id="actor1", title="Збір на авто для бойового підрозділу")
    c2 = _make_campaign("c2", actor_id="actor1", title="Збір на дрони FPV для штурму")

    groups = fuzzy_merge_groups([c1, c2])
    assert len(groups) == 2
    # кожен як окремий singleton
    for g in groups:
        assert len(g) == 1


def test_fuzzy_merge_groups_different_actors_never_grouped():
    """Різні актори → ніколи не об'єднуються навіть з однаковою назвою."""
    title = "Збір на комплектуючі для дронів підрозділу"
    c1 = _make_campaign("c1", actor_id="actor_a", title=title)
    c2 = _make_campaign("c2", actor_id="actor_b", title=title)

    groups = fuzzy_merge_groups([c1, c2])
    # Мають бути в окремих групах (різні актори)
    assert len(groups) == 2


def test_fuzzy_merge_groups_different_goal_category_not_grouped():
    """Однаковий актор, але різні goal_category → не групуються."""
    c1 = _make_campaign("c1", actor_id="actor1", title="Збір на дрони для бригади", goal="military")
    c2 = _make_campaign("c2", actor_id="actor1", title="Збір на дрони для бригади", goal="medical")

    groups = fuzzy_merge_groups([c1, c2])
    # Різні goal_category — мають лишитися окремими
    assert len(groups) == 2


def test_fuzzy_merge_groups_singleton_stays_singleton():
    """Один кейс → одна група з одного елемента."""
    c1 = _make_campaign("c1", actor_id="actor1", title="Збір на дрони")
    groups = fuzzy_merge_groups([c1])
    assert len(groups) == 1
    assert len(groups[0]) == 1


def test_fuzzy_merge_groups_empty_list_returns_empty():
    assert fuzzy_merge_groups([]) == []


def test_fuzzy_merge_groups_three_campaigns_two_similar_one_different():
    """3 кампанії: 2 схожі + 1 відмінна → [група з 2, singleton]."""
    t1 = "Збір 1 000 000 ₴ на комплектуючі для дронів підрозділу"
    t2 = "Збір 1 млн грн на комплектуючі для дронів — підрозділ…"
    t3 = "Збір на броньований автомобіль для десантників"
    c1 = _make_campaign("c1", actor_id="actor1", title=t1)
    c2 = _make_campaign("c2", actor_id="actor1", title=t2)
    c3 = _make_campaign("c3", actor_id="actor1", title=t3)

    groups = fuzzy_merge_groups([c1, c2, c3])
    sizes = sorted(len(g) for g in groups)
    assert sizes == [1, 2]


def test_fuzzy_merge_groups_custom_min_sim():
    """min_sim=0.0 → всі кампанії одного актора+goal зливаються разом."""
    c1 = _make_campaign("c1", actor_id="actor1", title="Авто для бригади")
    c2 = _make_campaign("c2", actor_id="actor1", title="Дрони FPV для штурму")

    groups = fuzzy_merge_groups([c1, c2], min_sim=0.0)
    assert len(groups) == 1


def test_fuzzy_merge_groups_high_min_sim_all_singletons():
    """min_sim=1.0 → тільки ідентичні назви групуються (решта singletons)."""
    t1 = "Збір на дрони підрозділу"
    t2 = "Збір на комплектуючі для дронів"
    c1 = _make_campaign("c1", actor_id="actor1", title=t1)
    c2 = _make_campaign("c2", actor_id="actor1", title=t2)

    groups = fuzzy_merge_groups([c1, c2], min_sim=1.0)
    assert len(groups) == 2
