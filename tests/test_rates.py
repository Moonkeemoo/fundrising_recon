"""Tests for rates.py — UAH->USD normalization."""
from __future__ import annotations

import pytest

from fundrec.rates import usd_rate, to_usd, _FALLBACK_RATES


def test_fallback_rates_keys_cover_2022_to_2026():
    for year in range(2022, 2027):
        assert year in _FALLBACK_RATES
        assert _FALLBACK_RATES[year] > 0


def _no_network(url: str):
    """Fake client that always fails — forces fallback."""
    raise RuntimeError("no network in tests")


def test_usd_rate_fallback_2022():
    """With failing client, uses fallback table for 2022."""
    rate = usd_rate("2022-06-15", _client=_no_network)
    assert rate == pytest.approx(_FALLBACK_RATES[2022])


def test_usd_rate_fallback_2024():
    rate = usd_rate("2024-03-01", _client=_no_network)
    assert rate == pytest.approx(_FALLBACK_RATES[2024])


def test_usd_rate_with_fake_client_success():
    """Injectable client returns list with r030/rate fields."""
    def fake_client(url: str):
        return [{"r030": 840, "cc": "USD", "rate": 38.5, "exchangedate": "01.01.2023"}]

    rate = usd_rate("2023-01-01", _client=fake_client)
    assert rate == pytest.approx(38.5)


def test_usd_rate_with_client_failure_falls_back():
    """If client raises, fallback is used."""
    def bad_client(url: str):
        raise RuntimeError("network error")

    rate = usd_rate("2023-06-01", _client=bad_client)
    assert rate == pytest.approx(_FALLBACK_RATES[2023])


def test_usd_rate_with_client_empty_response_falls_back():
    """If client returns empty list, fallback is used."""
    def empty_client(url: str):
        return []

    rate = usd_rate("2025-01-01", _client=empty_client)
    assert rate == pytest.approx(_FALLBACK_RATES[2025])


def test_to_usd_none_amount_returns_none():
    assert to_usd(None, "2024-01-01") is None


def test_to_usd_none_date_returns_none():
    assert to_usd(100.0, None) is None


def test_to_usd_both_none_returns_none():
    assert to_usd(None, None) is None


def test_to_usd_converts_with_fallback():
    """amount_uah / rate = amount_usd."""
    uah = 39_000.0
    result = to_usd(uah, "2024-05-01", _client=_no_network)  # fallback 2024 = 39.0
    assert result == pytest.approx(uah / _FALLBACK_RATES[2024])


def test_to_usd_with_fake_client():
    def fake_client(url: str):
        return [{"rate": 40.0}]

    result = to_usd(4000.0, "2025-01-01", _client=fake_client)
    assert result == pytest.approx(100.0)
