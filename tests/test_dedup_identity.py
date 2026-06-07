"""Тести для Unit 1: content_hash, campaign_jar_id, campaign_identity (dedup.py).

TDD: ці тести написані ДО реалізації — спочатку червоні, потім зелені.
"""
from __future__ import annotations

from fundrec.dedup import campaign_identity, campaign_jar_id, content_hash
from fundrec.schema import Campaign


# ---------------------------------------------------------------------------
# Хелпер
# ---------------------------------------------------------------------------


def _make_campaign(
    id: str = "c1",
    actor_id: str = "a1",
    title: str = "Великий збір",
    provenance: dict | None = None,
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
    )


# ---------------------------------------------------------------------------
# content_hash
# ---------------------------------------------------------------------------


def test_content_hash_none_input_returns_none():
    assert content_hash(None) is None


def test_content_hash_empty_string_returns_none():
    assert content_hash("") is None


def test_content_hash_whitespace_only_returns_none():
    assert content_hash("   \n\t  ") is None


def test_content_hash_returns_16_hex_chars():
    h = content_hash("Допоможіть купити FPV дрони!")
    assert h is not None
    assert len(h) == 16
    assert all(c in "0123456789abcdef" for c in h)


def test_content_hash_stable_same_input():
    """Однаковий вхід → однаковий хеш (стабільний)."""
    t = "Збираємо на броньований автомобіль для ЗСУ. Потрібно 500 000 грн."
    assert content_hash(t) == content_hash(t)


def test_content_hash_case_insensitive():
    """Регістр не впливає на хеш."""
    assert content_hash("ДРОНИ ЗСУ") == content_hash("дрони зсу")


def test_content_hash_strips_urls():
    """URL видаляються перед хешуванням → однаковий хеш."""
    t1 = "Збираємо на дрони https://send.monobank.ua/jar/ABC123 для ЗСУ"
    t2 = "Збираємо на дрони для ЗСУ"
    assert content_hash(t1) == content_hash(t2)


def test_content_hash_strips_punctuation():
    """Пунктуація видаляється → однаковий хеш."""
    assert content_hash("Дрони, дрони!!!") == content_hash("Дрони  дрони")


def test_content_hash_different_texts_differ():
    """Різний контент → різний хеш."""
    assert content_hash("Збираємо на FPV дрони") != content_hash("Збираємо на броню")


def test_content_hash_uses_first_300_chars():
    """Хеш обчислюється по перших ~300 нормалізованих символах.

    Два тексти однакові в перших 300 знаках, але різні далі → однаковий хеш.
    """
    base = "а" * 300
    t1 = base + "ХХХ"
    t2 = base + "ЯЯЯ"
    assert content_hash(t1) == content_hash(t2)


# ---------------------------------------------------------------------------
# campaign_jar_id
# ---------------------------------------------------------------------------


def test_campaign_jar_id_none_when_no_provenance():
    c = _make_campaign(provenance={})
    assert campaign_jar_id(c) is None


def test_campaign_jar_id_extracts_from_provenance_source_url():
    """Провенанс із source_url банки → повертає jar_id."""
    prov = {
        "amount_uah": {
            "source_url": "https://send.monobank.ua/jar/ABC123xyz",
            "confidence": 0.95,
            "tier": 1,
        }
    }
    c = _make_campaign(provenance=prov)
    assert campaign_jar_id(c) == "ABC123xyz"


def test_campaign_jar_id_finds_any_field_with_jar_url():
    """Будь-яке поле провенансу з jar-url → jar_id."""
    prov = {
        "goal_amount": {
            "source_url": "https://send.monobank.ua/jar/JARXXX",
            "confidence": 0.8,
            "tier": 1,
        }
    }
    c = _make_campaign(provenance=prov)
    assert campaign_jar_id(c) == "JARXXX"


def test_campaign_jar_id_none_for_non_jar_url():
    prov = {
        "amount_uah": {
            "source_url": "https://news.example.com/article",
            "confidence": 0.7,
            "tier": 2,
        }
    }
    c = _make_campaign(provenance=prov)
    assert campaign_jar_id(c) is None


def test_campaign_jar_id_none_when_source_url_missing():
    prov = {"amount_uah": {"confidence": 0.7, "tier": 2}}
    c = _make_campaign(provenance=prov)
    assert campaign_jar_id(c) is None


# ---------------------------------------------------------------------------
# campaign_identity
# ---------------------------------------------------------------------------


def test_campaign_identity_jar_present_returns_jar_key():
    """Jar в провенансі → ключ починається з 'jar:'."""
    prov = {
        "amount_uah": {
            "source_url": "https://send.monobank.ua/jar/MYJAR1",
            "confidence": 0.95,
            "tier": 1,
        }
    }
    c = _make_campaign(provenance=prov)
    key = campaign_identity(c)
    assert key == "jar:MYJAR1"


def test_campaign_identity_same_jar_same_key():
    """Дві кампанії з однаковим jar → однаковий identity."""
    prov = {
        "amount_uah": {
            "source_url": "https://send.monobank.ua/jar/SHARED_JAR",
            "confidence": 0.9,
            "tier": 1,
        }
    }
    c1 = _make_campaign("c1", title="Збір 1", provenance=prov)
    c2 = _make_campaign("c2", title="Збір 2 — інша назва", provenance=prov)
    assert campaign_identity(c1) == campaign_identity(c2)


def test_campaign_identity_different_jars_differ():
    """Різні jar → різний identity."""
    p1 = {"amount_uah": {"source_url": "https://send.monobank.ua/jar/JAR_A", "confidence": 0.9, "tier": 1}}
    p2 = {"amount_uah": {"source_url": "https://send.monobank.ua/jar/JAR_B", "confidence": 0.9, "tier": 1}}
    c1 = _make_campaign("c1", provenance=p1)
    c2 = _make_campaign("c2", provenance=p2)
    assert campaign_identity(c1) != campaign_identity(c2)


def test_campaign_identity_no_jar_same_text_returns_content_key():
    """Без jar, однаковий текст → ключ 'content:...' однаковий."""
    text = "Збираємо на FPV дрони для ЗСУ"
    c1 = _make_campaign("c1", actor_id="a1", title="Збір А")
    c2 = _make_campaign("c2", actor_id="a1", title="Збір Б")
    k1 = campaign_identity(c1, text=text)
    k2 = campaign_identity(c2, text=text)
    assert k1.startswith("content:")
    assert k1 == k2


def test_campaign_identity_no_jar_same_title_returns_content_key():
    """Без jar, title використовується як text якщо text=None."""
    same_title = "Збираємо на дрони ЗСУ"
    c1 = _make_campaign("c1", title=same_title)
    c2 = _make_campaign("c2", title=same_title)
    k1 = campaign_identity(c1)
    k2 = campaign_identity(c2)
    assert k1.startswith("content:")
    assert k1 == k2


def test_campaign_identity_no_jar_diff_text_differ():
    """Без jar, різний text → різний identity (різні пости не зливаються)."""
    c1 = _make_campaign("c1", actor_id="act1", title="Збір А")
    c2 = _make_campaign("c2", actor_id="act1", title="Збір А")
    k1 = campaign_identity(c1, text="Абсолютно інший текст першого поста")
    k2 = campaign_identity(c2, text="Зовсім відмінний контент другого поста")
    # content_hash різний → різні content: ключі
    assert k1.startswith("content:")
    assert k2.startswith("content:")
    assert k1 != k2


def test_campaign_identity_no_text_no_jar_falls_back_to_actor_key():
    """Без jar і без text → actor-fallback, однаковий actor+title дають однаковий ключ."""
    # Щоб досягти actor-fallback, треба щоб title хешувався в None.
    # Найпростіше: title = None або порожній рядок.
    c1 = Campaign(id="c1", actor_id="act1", title="", goal="military", type="jar")
    c2 = Campaign(id="c2", actor_id="act1", title="", goal="military", type="jar")
    k1 = campaign_identity(c1)
    k2 = campaign_identity(c2)
    assert k1.startswith("actor:")
    assert k1 == k2


def test_campaign_identity_distinct_campaigns_have_distinct_keys():
    """Різний actor+title без jar → різний identity."""
    c1 = _make_campaign("c1", actor_id="a1", title="Кампанія А")
    c2 = _make_campaign("c2", actor_id="a2", title="Кампанія Б")
    assert campaign_identity(c1) != campaign_identity(c2)
