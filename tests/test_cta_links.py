"""CTA-anchor лінк-захоплення: парсер anchors + донат-лендінги як призначення.

Покриває:
  - парсер telegram_web: захоплення anchors (href+inner-text) + backward-compat links;
  - destinations.donation_candidate_urls: CTA-текст / донат-хост / виключення нав/соц;
  - destinations.extract_destinations: url:-лендінг id + стабільний хеш;
  - jars.jar_from_landing: краул вшитої банки (fake _client, offline);
  - audit.fill_resolve_links: лендінг→банка / лендінг-призначення / ідемпотентність.

Усі мережеві ефекти ІНʼЄКТУЮТЬСЯ (fake _client) — жодного реального I/O/мережі/БД.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fundrec import audit, store
from fundrec.schema import Actor, Campaign


# ═════════════════════════════════════════════════════════════════════════════
# 1) Парсер telegram_web: anchors (href + inner-text) + backward-compat links
# ═════════════════════════════════════════════════════════════════════════════


_CTA_HTML = """
<html><body>
<div class="tgme_widget_message" data-post="k_2_54/777">
  <div class="tgme_widget_message_text">
    Підтримай нас:
    <a href="https://send.monobank.ua/jar/ABC">Донать на шахедоріз</a>
    або через лендінг
    <a href="https://k-2.army/help-us">підтримати</a>
  </div>
  <a class="tgme_widget_message_date" href="https://t.me/k_2_54/777">
    <time datetime="2024-05-01T10:00:00+00:00">1 May</time>
  </a>
</div>
</body></html>
"""


def test_parser_captures_anchor_text_and_keeps_links():
    from fundrec.collect.telegram_web import parse_tme_html

    posts = parse_tme_html("k_2_54", _CTA_HTML)
    assert len(posts) == 1
    post = posts[0]

    # anchors присутні з коректним текстом
    anchors = post["anchors"]
    by_href = {a["href"]: a["text"] for a in anchors}
    assert by_href["https://send.monobank.ua/jar/ABC"] == "Донать на шахедоріз"
    assert by_href["https://k-2.army/help-us"] == "підтримати"

    # links зберігає обидва href (backward-compat — list[str])
    assert "https://send.monobank.ua/jar/ABC" in post["links"]
    assert "https://k-2.army/help-us" in post["links"]
    assert all(isinstance(x, str) for x in post["links"])


def test_parser_anchors_key_always_present():
    from fundrec.collect.telegram_web import parse_tme_html

    html = (
        '<div class="tgme_widget_message" data-post="ch/1">'
        '<div class="tgme_widget_message_text">Текст без посилань</div>'
        "</div>"
    )
    posts = parse_tme_html("ch", html)
    assert posts[0]["anchors"] == []


def test_parser_anchors_dedup_by_href_text():
    from fundrec.collect.telegram_web import parse_tme_html

    html = (
        '<div class="tgme_widget_message" data-post="ch/2">'
        '<div class="tgme_widget_message_text">'
        '<a href="https://k-2.army/help">тиць</a> '
        '<a href="https://k-2.army/help">тиць</a>'
        "</div></div>"
    )
    posts = parse_tme_html("ch", html)
    anchors = posts[0]["anchors"]
    assert anchors == [{"href": "https://k-2.army/help", "text": "тиць"}]


# ═════════════════════════════════════════════════════════════════════════════
# 2) donation_candidate_urls
# ═════════════════════════════════════════════════════════════════════════════


def test_candidate_cta_text_non_obvious_host_included():
    from fundrec.destinations import donation_candidate_urls

    raw = {"anchors": [{"href": "https://vitatv.com.ua/x", "text": "Донать сюди"}]}
    assert donation_candidate_urls(raw) == ["https://vitatv.com.ua/x"]


def test_candidate_landing_help_path_included():
    from fundrec.destinations import donation_candidate_urls

    # текст не CTA, але href містить /help-us → донат-хост
    raw = {"anchors": [{"href": "https://k-2.army/help-us", "text": "тиць"}]}
    assert donation_candidate_urls(raw) == ["https://k-2.army/help-us"]


def test_candidate_plain_tme_channel_excluded():
    from fundrec.destinations import donation_candidate_urls

    raw = {"anchors": [{"href": "https://t.me/k_2_54", "text": "наш канал"}]}
    assert donation_candidate_urls(raw) == []


def test_candidate_tme_post_link_excluded():
    from fundrec.destinations import donation_candidate_urls

    raw = {"anchors": [{"href": "https://t.me/k_2_54/123", "text": "дивись пост"}]}
    assert donation_candidate_urls(raw) == []


def test_candidate_cta_text_on_tme_link_included():
    from fundrec.destinations import donation_candidate_urls

    # сильний CTA-текст «переважує» виключення t.me
    raw = {"anchors": [{"href": "https://t.me/some_jar_bot", "text": "Задонатити"}]}
    assert donation_candidate_urls(raw) == ["https://t.me/some_jar_bot"]


def test_candidate_social_excluded_unless_cta():
    from fundrec.destinations import donation_candidate_urls

    raw = {"anchors": [{"href": "https://facebook.com/page", "text": "ми у фб"}]}
    assert donation_candidate_urls(raw) == []


def test_candidate_falls_back_to_links():
    from fundrec.destinations import donation_candidate_urls

    raw = {"links": ["https://send.monobank.ua/jar/Z", "https://example.com/news"]}
    # jar-хост — кандидат; example.com/news без CTA-тексту — ні
    assert donation_candidate_urls(raw) == ["https://send.monobank.ua/jar/Z"]


def test_candidate_dedup_and_order():
    from fundrec.destinations import donation_candidate_urls

    raw = {
        "anchors": [
            {"href": "https://k-2.army/help", "text": "донат"},
            {"href": "https://k-2.army/help", "text": "донат"},
            {"href": "https://vita.ua/support", "text": "ще"},
        ]
    }
    assert donation_candidate_urls(raw) == [
        "https://k-2.army/help",
        "https://vita.ua/support",
    ]


# ═════════════════════════════════════════════════════════════════════════════
# 3) extract_destinations — url:-лендінг id
# ═════════════════════════════════════════════════════════════════════════════


def test_destinations_landing_only_returns_url_hash():
    from fundrec.destinations import extract_destinations

    raw = {"anchors": [{"href": "https://k-2.army/help-us", "text": "підтримати"}]}
    dest = extract_destinations(raw)
    assert len(dest) == 1
    assert dest[0].startswith("url:")


def test_destinations_direct_jar_no_url_dup():
    from fundrec.destinations import extract_destinations

    raw = {
        "text": "Банка https://send.monobank.ua/jar/JARX",
        "anchors": [{"href": "https://send.monobank.ua/jar/JARX", "text": "донат"}],
    }
    dest = extract_destinations(raw)
    assert dest == ["jar:JARX"]


def test_destinations_url_hash_stable_across_utm():
    from fundrec.destinations import extract_destinations

    raw1 = {"anchors": [{"href": "https://k-2.army/help-us?utm_source=tg", "text": "донат"}]}
    raw2 = {"anchors": [{"href": "https://k-2.army/help-us/?utm_source=fb#frag", "text": "донат"}]}
    d1 = extract_destinations(raw1)
    d2 = extract_destinations(raw2)
    assert d1 == d2
    assert d1[0].startswith("url:")


# ═════════════════════════════════════════════════════════════════════════════
# 4) jar_from_landing — краул вшитої банки (fake _client)
# ═════════════════════════════════════════════════════════════════════════════


class _FakeLandingResp:
    def __init__(self, text: str, final_url: str | None = None):
        self.text = text
        self.url = final_url


class _FakeLandingClient:
    def __init__(self, text: str = "", final_url: str | None = None, raise_exc: bool = False):
        self._text = text
        self._final_url = final_url
        self._raise = raise_exc
        self.calls: list[str] = []

    def get(self, url, timeout=10):  # noqa: ARG002
        self.calls.append(url)
        if self._raise:
            raise ConnectionError("network down")
        return _FakeLandingResp(self._text, self._final_url or url)


def test_jar_from_landing_extracts_embedded_jar():
    from fundrec.jars import jar_from_landing

    html = '<html><body><a href="https://send.monobank.ua/jar/XYZ">банка</a></body></html>'
    client = _FakeLandingClient(text=html)
    assert jar_from_landing("https://k-2.army/help-us", _client=client) == "XYZ"


def test_jar_from_landing_no_jar_returns_none():
    from fundrec.jars import jar_from_landing

    client = _FakeLandingClient(text="<html><body>Просто текст</body></html>")
    assert jar_from_landing("https://k-2.army/help-us", _client=client) is None


def test_jar_from_landing_non_http_returns_none():
    from fundrec.jars import jar_from_landing

    client = _FakeLandingClient(text="send.monobank.ua/jar/NOPE")
    # не http(s) — навіть не фетчимо
    assert jar_from_landing("mailto:foo@bar.com", _client=client) is None
    assert client.calls == []


def test_jar_from_landing_network_error_returns_none():
    from fundrec.jars import jar_from_landing

    client = _FakeLandingClient(raise_exc=True)
    assert jar_from_landing("https://k-2.army/help-us", _client=client) is None


def test_jar_from_landing_depth_guard():
    from fundrec.jars import jar_from_landing

    client = _FakeLandingClient(text="send.monobank.ua/jar/DEEP")
    assert jar_from_landing("https://k-2.army/help", _client=client, _depth=1) is None


def test_jar_from_landing_via_redirect_url():
    from fundrec.jars import jar_from_landing

    # тіло без банки, але фінальний URL (після редиректу) — банка
    client = _FakeLandingClient(
        text="<html></html>", final_url="https://send.monobank.ua/jar/REDIR"
    )
    assert jar_from_landing("https://cutt.ly/x", _client=client) == "REDIR"


# ═════════════════════════════════════════════════════════════════════════════
# 5) fill_resolve_links — лендінг→банка / лендінг-призначення / ідемпотентність
# ═════════════════════════════════════════════════════════════════════════════


def _seed_db(tmp_path: Path):
    db_path = tmp_path / "test.sqlite"
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    conn = store.connect(db_path)
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id="a1", name="Тест-актор", type="unknown"))
    return conn, raw_dir


def _camp(source_url: str, **kw) -> Campaign:
    prov = kw.pop("provenance", {})
    prov.setdefault("campaign", {"source_url": source_url, "tier": 2})
    cid = "camp-" + hashlib.sha256(source_url.encode()).hexdigest()[:12]
    base = dict(id=cid, actor_id="a1", title="Тестовий збір", goal="military",
                type="organic_social")
    base.update(kw)
    return Campaign(provenance=prov, **base)


class _LandingClient:
    """Fake httpx: HEAD/GET для скорочувача + GET лендінгу повертає HTML."""

    def __init__(self, get_map: dict[str, str]):
        self._get_map = get_map  # url -> html

    def head(self, url, timeout=10):  # noqa: ARG002
        return type("R", (), {"url": url})()

    def get(self, url, timeout=10):  # noqa: ARG002
        html = self._get_map.get(url, "")
        return type("R", (), {"text": html, "url": url})()


def test_fill_resolve_links_crawls_landing_for_jar(tmp_path):
    conn, _raw = _seed_db(tmp_path)
    src = "https://t.me/ch/1"
    raw = {
        "source_url": src,
        "anchors": [{"href": "https://k-2.army/help-us", "text": "Донать"}],
        "links": ["https://k-2.army/help-us"],
    }
    c = _camp(src)
    store.upsert_campaign(conn, c)
    assert audit.campaign_jar_id(c) is None

    client = _LandingClient({
        "https://k-2.army/help-us":
            '<a href="https://send.monobank.ua/jar/LANDJAR">банка</a>',
    })
    ok = audit.fill_resolve_links(conn, c, raw, _client=client)
    assert ok is True
    reloaded = store.get_campaign(conn, c.id)
    assert audit.campaign_jar_id(reloaded) == "LANDJAR"


def test_fill_resolve_links_attaches_landing_when_no_jar(tmp_path):
    conn, _raw = _seed_db(tmp_path)
    src = "https://t.me/ch/2"
    raw = {
        "source_url": src,
        "anchors": [{"href": "https://vitatv.com.ua/help", "text": "Підтримати збір"}],
        "links": ["https://vitatv.com.ua/help"],
    }
    c = _camp(src)
    store.upsert_campaign(conn, c)

    # лендінг без вшитої банки
    client = _LandingClient({"https://vitatv.com.ua/help": "<html>Дякуємо</html>"})
    ok = audit.fill_resolve_links(conn, c, raw, _client=client)
    assert ok is True
    reloaded = store.get_campaign(conn, c.id)
    # банки нема, але призначення (лендінг) є → has_destination True
    assert audit.campaign_jar_id(reloaded) is None
    assert audit._has_destination(reloaded, raw) is True

    # ідемпотентність: повторний запуск нічого не додає
    ok2 = audit.fill_resolve_links(conn, reloaded, raw, _client=client)
    assert ok2 is False


def test_fill_resolve_links_no_donation_links_returns_false(tmp_path):
    conn, _raw = _seed_db(tmp_path)
    src = "https://t.me/ch/3"
    raw = {
        "source_url": src,
        "anchors": [{"href": "https://t.me/ch", "text": "наш канал"}],
        "links": ["https://t.me/ch"],
    }
    c = _camp(src)
    store.upsert_campaign(conn, c)
    ok = audit.fill_resolve_links(conn, c, raw, _client=_LandingClient({}))
    assert ok is False


def test_fill_resolve_links_shortener_jar_still_works(tmp_path):
    conn, _raw = _seed_db(tmp_path)
    src = "https://t.me/ch/4"
    raw = {"source_url": src, "text": "Донат", "links": ["https://cutt.ly/abc"],
           "anchors": [{"href": "https://cutt.ly/abc", "text": "Донать"}]}
    c = _camp(src)
    store.upsert_campaign(conn, c)

    client = _LandingClient({})
    # cutt.ly — відомий скорочувач; HEAD повертає сам url, тож резолв jar
    # відбувається через сам href тільки якщо це jar. Тут перевіряємо, що
    # лендінг-гілка спрацьовує: cutt.ly не jar-хост, не social → кандидат,
    # краул GET повертає порожньо → лендінг-призначення.
    ok = audit.fill_resolve_links(conn, c, raw, _client=client)
    assert ok is True
