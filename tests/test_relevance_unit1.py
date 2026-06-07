"""Unit 1 — is_fundraising(raw) -> bool: детермінований гейт релевантності.

TDD: тести написані ДО реалізації. Запускати з .venv.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Допоміжна функція для побудови raw-словника
# ---------------------------------------------------------------------------

def _raw(
    text: str = "",
    title: str = "",
    description: str = "",
    links: list[str] | None = None,
) -> dict:
    return {
        "text": text,
        "title": title,
        "description": description,
        "links": links or [],
    }


# ---------------------------------------------------------------------------
# Jar-link → True
# ---------------------------------------------------------------------------

def test_jar_link_in_text_is_fundraising():
    """Тільки посилання на jar → True (безумовно)."""
    from fundrec.relevance import is_fundraising
    raw = _raw(text="Підтримайте збір: send.monobank.ua/jar/ABC123")
    assert is_fundraising(raw) is True


def test_jar_link_in_links_is_fundraising():
    """Jar-id у полі links → True."""
    from fundrec.relevance import is_fundraising
    raw = _raw(links=["https://send.monobank.ua/jar/XYZ789"])
    assert is_fundraising(raw) is True


def test_jar_link_in_description_is_fundraising():
    """Jar-id у description → True."""
    from fundrec.relevance import is_fundraising
    raw = _raw(description="Банка тут: base.monobank.ua/jar/TEST1")
    assert is_fundraising(raw) is True


def test_jar_link_with_full_fundraising_text_is_fundraising():
    """Jar-link + повний збір-текст → True."""
    from fundrec.relevance import is_fundraising
    raw = _raw(text="Збір на дрони! Реквізити: send.monobank.ua/jar/ABC")
    assert is_fundraising(raw) is True


# ---------------------------------------------------------------------------
# Картка / IBAN → True
# ---------------------------------------------------------------------------

def test_card_number_compact_is_fundraising():
    """16-цифрова картка без пробілів → True."""
    from fundrec.relevance import is_fundraising
    raw = _raw(text="Картка 5375414112345678 для допомоги")
    assert is_fundraising(raw) is True


def test_card_number_spaced_is_fundraising():
    """16-цифрова картка з пробілами (5375 4141 1234 5678) → True."""
    from fundrec.relevance import is_fundraising
    raw = _raw(text="Картка: 5375 4141 1234 5678 — переказуйте")
    assert is_fundraising(raw) is True


def test_card_number_grouped_dashes_is_fundraising():
    """16-цифрова картка з тире → True."""
    from fundrec.relevance import is_fundraising
    raw = _raw(text="Номер карти: 5375-4141-1234-5678")
    assert is_fundraising(raw) is True


def test_iban_in_text_is_fundraising():
    """IBAN UA + 27 цифр у тексті → True."""
    from fundrec.relevance import is_fundraising
    raw = _raw(text="IBAN: UA213223130000026007233566001 — перекажіть")
    assert is_fundraising(raw) is True


def test_iban_in_description_is_fundraising():
    """IBAN у description → True."""
    from fundrec.relevance import is_fundraising
    raw = _raw(description="Реквізити: UA213223130000026007233566001")
    assert is_fundraising(raw) is True


# ---------------------------------------------------------------------------
# Донат-ключове слово + число/URL → True
# ---------------------------------------------------------------------------

def test_zadonat_with_url_is_fundraising():
    """'задонатити' + URL → True."""
    from fundrec.relevance import is_fundraising
    raw = _raw(text="Задонатити можна тут: https://example.com/help")
    assert is_fundraising(raw) is True


def test_donat_keyword_with_goal_amount_is_fundraising():
    """'донат' + сума (parse_amounts_from_text → non-None) → True."""
    from fundrec.relevance import is_fundraising
    raw = _raw(text="Наш донат: збираємо на 500 000 грн для ЗСУ")
    assert is_fundraising(raw) is True


def test_pidtrymaty_zbir_with_url_is_fundraising():
    """'підтримати збір' + URL → True."""
    from fundrec.relevance import is_fundraising
    raw = _raw(
        text="Підтримати збір можна за посиланням https://send.monobank.ua/jar/XYZ"
    )
    assert is_fundraising(raw) is True


def test_rekvizity_with_amount_is_fundraising():
    """'реквізити' + сума → True."""
    from fundrec.relevance import is_fundraising
    raw = _raw(text="Реквізити для переказу. Ціль: 1 млн грн.")
    assert is_fundraising(raw) is True


def test_zbyraemo_na_with_amount_is_fundraising():
    """'збираємо на' + сума → True."""
    from fundrec.relevance import is_fundraising
    raw = _raw(text="Збираємо на FPV дрони: потрібно 2 млн грн!")
    assert is_fundraising(raw) is True


def test_na_kartku_with_amount_is_fundraising():
    """'на картку' + сума → True."""
    from fundrec.relevance import is_fundraising
    raw = _raw(text="Переказуйте на картку. Ціль 100 000 грн.")
    assert is_fundraising(raw) is True


def test_perekazhtʼ_with_url_is_fundraising():
    """'перекажіть' + URL → True."""
    from fundrec.relevance import is_fundraising
    raw = _raw(text="Перекажіть будь-яку суму: https://bank.example/donate")
    assert is_fundraising(raw) is True


def test_monobank_keyword_with_amount_is_fundraising():
    """'монобанк' + сума → True."""
    from fundrec.relevance import is_fundraising
    raw = _raw(text="Монобанк збір: ціль 300 тис грн.")
    assert is_fundraising(raw) is True


# ---------------------------------------------------------------------------
# Топічний контент (без механізму збору) → False
# ---------------------------------------------------------------------------

def test_topical_tccc_video_is_not_fundraising():
    """Навчальний відеоролик TCCC — no jar/card/ask → False."""
    from fundrec.relevance import is_fundraising
    raw = _raw(
        title="ТАКТИЧНА АПТЕЧКА TCCC для військових по системі MARCH",
        text=(
            "У цьому відео ми розглядаємо комплектацію тактичної аптечки "
            "за стандартом TCCC та системою MARCH для підготовки військових."
        ),
        description="Навчальний контент про медицину на полі бою.",
    )
    assert is_fundraising(raw) is False


def test_news_article_about_collection_is_fundraising():
    """Текст із явною фразою 'збір коштів' → True (посилається на реальний збір)."""
    from fundrec.relevance import is_fundraising
    raw = _raw(
        title="Волонтери зібрали кошти на дрони",
        text=(
            "Волонтерська організація оголосила, що завершила збір коштів "
            "на придбання 50 дронів для ЗСУ. Деталі в репортажі."
        ),
    )
    assert is_fundraising(raw) is True


def test_educational_article_no_ask_is_not_fundraising():
    """Освітній текст про тактику без реквізитів → False."""
    from fundrec.relevance import is_fundraising
    raw = _raw(
        title="Як правильно надавати першу допомогу",
        text="Стаття про медичну підготовку. Протоколи TCCC та MARCH.",
    )
    assert is_fundraising(raw) is False


def test_donat_keyword_alone_no_number_no_url_is_not_fundraising():
    """'донат' без числа та без URL → False."""
    from fundrec.relevance import is_fundraising
    raw = _raw(text="Дякуємо всім за донат і підтримку!")
    assert is_fundraising(raw) is False


def test_mention_of_bank_no_ask_is_not_fundraising():
    """Згадка банку без конкретного запиту → False."""
    from fundrec.relevance import is_fundraising
    raw = _raw(text="Монобанк — найзручніший банк для українців.")
    assert is_fundraising(raw) is False


def test_empty_raw_is_not_fundraising():
    """Порожній raw → False."""
    from fundrec.relevance import is_fundraising
    assert is_fundraising({}) is False


def test_raw_with_explicit_fundraising_title_is_fundraising():
    """raw з явною назвою-збором ('збір на ...') → True навіть без механізму у сніпеті."""
    from fundrec.relevance import is_fundraising
    raw = _raw(title="Збір на броньовик для 3-ї бригади")
    assert is_fundraising(raw) is True


# ---------------------------------------------------------------------------
# Граничні випадки
# ---------------------------------------------------------------------------

def test_donat_with_http_url_is_fundraising():
    """'донат' + http:// URL → True."""
    from fundrec.relevance import is_fundraising
    raw = _raw(text="Задонатити: http://example.com/pay")
    assert is_fundraising(raw) is True


def test_dopomohty_zboru_with_amount_is_fundraising():
    """'допомогти збору' + сума → True."""
    from fundrec.relevance import is_fundraising
    raw = _raw(text="Допомогти збору: збираємо на 200 тис грн.")
    assert is_fundraising(raw) is True


def test_banka_keyword_with_amount_is_fundraising():
    """'банка' + сума → True."""
    from fundrec.relevance import is_fundraising
    raw = _raw(text="Наша банка на дрони: ціль 1 млн грн!")
    assert is_fundraising(raw) is True


def test_card_number_in_links_is_fundraising():
    """16-цифрова картка у links (як текст) → True (links сканується)."""
    from fundrec.relevance import is_fundraising
    raw = _raw(links=["5375414112345678"])
    assert is_fundraising(raw) is True
