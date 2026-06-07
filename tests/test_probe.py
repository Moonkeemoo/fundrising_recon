"""Тести для fundrec.probe — probe_access(url, *, _client=None) -> str."""
from __future__ import annotations

from fundrec.probe import probe_access


class _FakeResp:
    """Мінімальна підробка httpx.Response."""

    def __init__(self, status_code: int, text: str = "", url: str = "http://example.com"):
        self.status_code = status_code
        self.text = text
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise _FakeHTTPError(self.status_code)


class _FakeHTTPError(Exception):
    def __init__(self, status_code: int):
        self.response = _FakeResp(status_code)
        super().__init__(f"HTTP {status_code}")


class _FakeConnError(Exception):
    """Підробка httpx.ConnectError."""
    pass


class _FakeClient:
    """Підробка httpx-клієнта з заданою відповіддю."""

    def __init__(self, status_code: int, text: str = "", raise_conn_error: bool = False):
        self._status_code = status_code
        self._text = text
        self._raise_conn_error = raise_conn_error

    def get(self, url: str, **kwargs):
        if self._raise_conn_error:
            raise _FakeConnError("connection refused")
        return _FakeResp(self._status_code, self._text, url)


def test_probe_200_public():
    client = _FakeClient(200)
    assert probe_access("http://example.com", _client=client) == "public"


def test_probe_401_auth():
    client = _FakeClient(401)
    assert probe_access("http://example.com", _client=client) == "auth"


def test_probe_403_auth():
    client = _FakeClient(403)
    assert probe_access("http://example.com", _client=client) == "auth"


def test_probe_402_paywalled():
    client = _FakeClient(402)
    assert probe_access("http://example.com", _client=client) == "paywalled"


def test_probe_paywall_marker_in_body():
    """200, але тіло містить маркер paywall — вважаємо paywalled."""
    client = _FakeClient(200, text="Subscribe to read this article. paywall")
    assert probe_access("http://example.com", _client=client) == "paywalled"


def test_probe_404_dead():
    client = _FakeClient(404)
    assert probe_access("http://example.com", _client=client) == "dead"


def test_probe_500_dead():
    client = _FakeClient(500)
    assert probe_access("http://example.com", _client=client) == "dead"


def test_probe_connection_error_dead():
    """ConnectError → dead."""
    client = _FakeClient(0, raise_conn_error=True)
    assert probe_access("http://example.com", _client=client) == "dead"


def test_probe_requires_injected_client_interface():
    """probe_access повертає рядок зі словника."""
    client = _FakeClient(200)
    result = probe_access("http://test.example.com", _client=client)
    assert result in {"public", "paywalled", "auth", "dead"}
