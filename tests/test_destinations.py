"""Unit 1 — destinations.py: extract_privat_ids + extract_destinations.

Зборо-центрична база: одиниця = призначення донату (jar / privat-конверт).
Всі мережеві виклики ін'єктовані через fake _client (offline-safe).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Fake HTTP client (для shortener-резолву)
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, final_url: str, status_code: int = 200):
        self.url = final_url
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeRedirectClient:
    def __init__(self, redirect_map: dict[str, str]):
        self._map = redirect_map

    def head(self, url: str, *, timeout: int = 10):
        return _FakeResp(self._map.get(url, url))

    def get(self, url: str, *, timeout: int = 10):
        return _FakeResp(self._map.get(url, url))


# ---------------------------------------------------------------------------
# extract_privat_ids
# ---------------------------------------------------------------------------


def test_privat_send_link():
    from fundrec.destinations import extract_privat_ids

    ids = extract_privat_ids("Донат: https://www.privat24.ua/send/abc123")
    assert ids == ["abc123"]


def test_privat_next_link():
    from fundrec.destinations import extract_privat_ids

    ids = extract_privat_ids("https://next.privat24.ua/send/xyz789")
    assert ids == ["xyz789"]


def test_privat_send_qr_link():
    from fundrec.destinations import extract_privat_ids

    ids = extract_privat_ids("https://www.privat24.ua/rd/send_qr/QR55")
    assert ids == ["QR55"]


def test_privat_link_privatbank():
    from fundrec.destinations import extract_privat_ids

    ids = extract_privat_ids("https://link.privatbank.ua/Pay99")
    assert ids == ["Pay99"]


def test_privat_dedup_same_envelope():
    from fundrec.destinations import extract_privat_ids

    text = (
        "https://www.privat24.ua/send/abc123 "
        "та ще раз https://www.privat24.ua/send/abc123"
    )
    assert extract_privat_ids(text) == ["abc123"]


def test_privat_no_match_returns_empty():
    from fundrec.destinations import extract_privat_ids

    assert extract_privat_ids("просто текст без посилань") == []


def test_privat_fallback_hash_when_no_segment():
    """privatbank.ua без зрозумілого сегмента → стабільний sha1-fallback."""
    from fundrec.destinations import extract_privat_ids

    ids = extract_privat_ids("https://privatbank.ua/?id=777&utm=x")
    assert len(ids) == 1
    # детермінований і стабільний між викликами
    assert extract_privat_ids("https://privatbank.ua/?id=777&utm=x") == ids


# ---------------------------------------------------------------------------
# extract_destinations
# ---------------------------------------------------------------------------


def test_destinations_monobank_jar():
    from fundrec.destinations import extract_destinations

    raw = {"text": "Банка: https://send.monobank.ua/jar/JAR111"}
    assert extract_destinations(raw) == ["jar:JAR111"]


def test_destinations_privat_send():
    from fundrec.destinations import extract_destinations

    raw = {"text": "https://www.privat24.ua/send/env42"}
    assert extract_destinations(raw) == ["priv:env42"]


def test_destinations_both_jar_and_privat():
    from fundrec.destinations import extract_destinations

    raw = {
        "text": "send.monobank.ua/jar/JJ і www.privat24.ua/send/PP",
    }
    dest = extract_destinations(raw)
    assert "jar:JJ" in dest
    assert "priv:PP" in dest
    assert len(dest) == 2


def test_destinations_privat_in_links_and_description():
    from fundrec.destinations import extract_destinations

    raw = {
        "text": "",
        "links": ["https://next.privat24.ua/send/inlink"],
        "description": "https://www.privat24.ua/send/indesc",
    }
    dest = extract_destinations(raw)
    assert "priv:inlink" in dest
    assert "priv:indesc" in dest


def test_destinations_shortener_resolves_to_jar():
    from fundrec.destinations import extract_destinations

    client = _FakeRedirectClient(
        {"https://bit.ly/short1": "https://send.monobank.ua/jar/RESOLVED"}
    )
    raw = {"text": "", "links": ["https://bit.ly/short1"]}
    dest = extract_destinations(raw, _client=client)
    assert dest == ["jar:RESOLVED"]


def test_destinations_none():
    from fundrec.destinations import extract_destinations

    raw = {"text": "просто пост без донату", "links": [], "description": ""}
    assert extract_destinations(raw) == []


def test_destinations_unique_ordered():
    from fundrec.destinations import extract_destinations

    raw = {
        "text": "send.monobank.ua/jar/AAA",
        "links": ["https://send.monobank.ua/jar/AAA", "https://www.privat24.ua/send/BBB"],
    }
    dest = extract_destinations(raw)
    assert dest == ["jar:AAA", "priv:BBB"]


def test_destinations_reads_raw_text_field():
    """raw_text (а не лише text) теж сканується на privat."""
    from fundrec.destinations import extract_destinations

    raw = {"raw_text": "https://www.privat24.ua/send/fromrawtext"}
    assert "priv:fromrawtext" in extract_destinations(raw)
