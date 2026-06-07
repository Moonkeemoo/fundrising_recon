"""Unit 1 — parse_tme_html захоплює ВСІ href всередині повідомлення.

Перевіряємо, що jar-посилання ПОЗА .tgme_widget_message_text (у footer/button)
також потрапляють до `links`.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Фікстура: jar <a> знаходиться поза .tgme_widget_message_text
# ---------------------------------------------------------------------------

_HTML_JAR_IN_FOOTER = """
<html><body>
<div class="tgme_widget_message" data-post="dignitas_fund/200">
  <div class="tgme_widget_message_text">
    Збираємо на FPV дрони для 3 ОШБр. Деталі нижче.
  </div>
  <!-- Jar-кнопка ПОЗА текстовим блоком -->
  <a href="https://send.monobank.ua/jar/ABC123XYZ">Задонатити в банку</a>
  <span class="tgme_widget_message_views">7.5K</span>
  <a class="tgme_widget_message_date" href="https://t.me/dignitas_fund/200">
    <time datetime="2024-05-01T12:00:00+00:00">1 May</time>
  </a>
</div>
</body></html>
"""

_HTML_JAR_IN_TEXT_AND_FOOTER = """
<html><body>
<div class="tgme_widget_message" data-post="dignitas_fund/201">
  <div class="tgme_widget_message_text">
    Текст із посиланням: <a href="https://send.monobank.ua/jar/TEXTJAR">банка</a>
  </div>
  <!-- Ще одна банка у footer -->
  <a href="https://send.monobank.ua/jar/FOOTERJAR">Задонатити</a>
  <a class="tgme_widget_message_date" href="https://t.me/dignitas_fund/201">
    <time datetime="2024-05-02T12:00:00+00:00">2 May</time>
  </a>
</div>
</body></html>
"""

_HTML_SHORTENER_IN_FOOTER = """
<html><body>
<div class="tgme_widget_message" data-post="dignitas_fund/202">
  <div class="tgme_widget_message_text">
    Підтримайте збір.
  </div>
  <a href="https://surl.li/abcde">Скорочений лінк</a>
  <a class="tgme_widget_message_date" href="https://t.me/dignitas_fund/202">
    <time datetime="2024-05-03T12:00:00+00:00">3 May</time>
  </a>
</div>
</body></html>
"""

_HTML_DATE_LINK_EXCLUDED = """
<html><body>
<div class="tgme_widget_message" data-post="dignitas_fund/203">
  <div class="tgme_widget_message_text">
    Звичайний текст без посилань.
  </div>
  <a class="tgme_widget_message_date" href="https://t.me/dignitas_fund/203">
    <time datetime="2024-05-04T12:00:00+00:00">4 May</time>
  </a>
</div>
</body></html>
"""


def test_jar_link_outside_text_block_captured():
    """Jar <a> ПОЗА .tgme_widget_message_text потрапляє до links."""
    from fundrec.collect.telegram_web import parse_tme_html

    posts = parse_tme_html("dignitas_fund", _HTML_JAR_IN_FOOTER)
    assert len(posts) == 1
    links = posts[0]["links"]
    assert "https://send.monobank.ua/jar/ABC123XYZ" in links


def test_jar_link_outside_text_deduped_if_same():
    """Якщо той самий href є і в тексті, і у footer — дедуп."""
    from fundrec.collect.telegram_web import parse_tme_html

    html = """
    <html><body>
    <div class="tgme_widget_message" data-post="ch/10">
      <div class="tgme_widget_message_text">
        <a href="https://send.monobank.ua/jar/DUP1">банка</a>
      </div>
      <a href="https://send.monobank.ua/jar/DUP1">Задонатити</a>
      <a class="tgme_widget_message_date" href="https://t.me/ch/10">
        <time datetime="2024-01-01T00:00:00+00:00">1 Jan</time>
      </a>
    </div>
    </body></html>
    """
    posts = parse_tme_html("ch", html)
    links = posts[0]["links"]
    assert links.count("https://send.monobank.ua/jar/DUP1") == 1


def test_text_and_footer_jars_both_captured():
    """Jar у тексті І jar у footer — обидва у links."""
    from fundrec.collect.telegram_web import parse_tme_html

    posts = parse_tme_html("dignitas_fund", _HTML_JAR_IN_TEXT_AND_FOOTER)
    assert len(posts) == 1
    links = posts[0]["links"]
    assert "https://send.monobank.ua/jar/TEXTJAR" in links
    assert "https://send.monobank.ua/jar/FOOTERJAR" in links


def test_shortener_in_footer_captured():
    """Скорочений lінк (surl.li) ПОЗА текстом потрапляє до links."""
    from fundrec.collect.telegram_web import parse_tme_html

    posts = parse_tme_html("dignitas_fund", _HTML_SHORTENER_IN_FOOTER)
    assert len(posts) == 1
    links = posts[0]["links"]
    assert "https://surl.li/abcde" in links


def test_date_permalink_excluded_from_links():
    """tgme_widget_message_date href НЕ потрапляє до links."""
    from fundrec.collect.telegram_web import parse_tme_html

    posts = parse_tme_html("dignitas_fund", _HTML_DATE_LINK_EXCLUDED)
    assert len(posts) == 1
    links = posts[0]["links"]
    # Посилання на сам пост (дата-пермалінк) НЕ має бути в links
    assert "https://t.me/dignitas_fund/203" not in links


def test_source_url_still_set_correctly():
    """source_url поста досі встановлюється з tgme_widget_message_date."""
    from fundrec.collect.telegram_web import parse_tme_html

    posts = parse_tme_html("dignitas_fund", _HTML_JAR_IN_FOOTER)
    assert posts[0]["source_url"] == "https://t.me/dignitas_fund/200"


def test_existing_fixture_still_passes():
    """Регресія: існуюча фікстура tme_channel.html досі повертає 3 пости."""
    from pathlib import Path

    from fundrec.collect.telegram_web import parse_tme_html

    html = (Path(__file__).parent / "fixtures" / "tme_channel.html").read_text(
        encoding="utf-8"
    )
    posts = parse_tme_html("prytulafoundation", html)
    assert len(posts) == 3
    # Всі пости мають source_url
    for post in posts:
        assert post["source_url"] is not None
        assert post["source_url"].startswith("https://t.me/")
