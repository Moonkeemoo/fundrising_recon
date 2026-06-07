"""Тести для fundrec.discover — discover_sources."""
from __future__ import annotations

from fundrec.discover import discover_sources


# --- Підробки для _search ---

def _make_search(*urls: str):
    """Повертає fake _search(query) -> list[str]."""
    def _search(query: str) -> list[str]:
        return list(urls)
    return _search


# --- Тести ---

def test_discover_returns_new_urls():
    """Повертає URLs з _search, яких нема в existing_urls."""
    search = _make_search(
        "https://example.com/1",
        "https://example.com/2",
        "https://example.com/3",
    )
    result = discover_sources("FPV дрони", existing_urls=set(), _search=search)
    assert "https://example.com/1" in result
    assert "https://example.com/2" in result
    assert "https://example.com/3" in result


def test_discover_filters_existing_urls():
    """URL з existing_urls фільтруються — не потрапляють у результат."""
    search = _make_search(
        "https://example.com/1",
        "https://example.com/already-known",
        "https://example.com/3",
    )
    existing = {"https://example.com/already-known"}
    result = discover_sources("тест", existing_urls=existing, _search=search)
    assert "https://example.com/already-known" not in result
    assert "https://example.com/1" in result
    assert "https://example.com/3" in result


def test_discover_respects_max_results():
    """max_results обмежує кількість повернених URLs."""
    search = _make_search(*[f"https://example.com/{i}" for i in range(20)])
    result = discover_sources("тест", existing_urls=set(), _search=search, max_results=5)
    assert len(result) <= 5


def test_discover_no_duplicates_in_result():
    """Якщо _search повернув дублікати — результат унікальний."""
    search = _make_search(
        "https://example.com/1",
        "https://example.com/1",  # дублікат
        "https://example.com/2",
    )
    result = discover_sources("тест", existing_urls=set(), _search=search)
    assert result.count("https://example.com/1") == 1


def test_discover_empty_search_returns_empty():
    """_search повертає [] → результат порожній."""
    search = _make_search()
    result = discover_sources("тест", existing_urls=set(), _search=search)
    assert result == []


def test_discover_all_known_returns_empty():
    """Всі результати вже в existing_urls → порожній список."""
    urls = ["https://example.com/1", "https://example.com/2"]
    search = _make_search(*urls)
    result = discover_sources("тест", existing_urls=set(urls), _search=search)
    assert result == []


def test_discover_default_max_results_is_10():
    """max_results за замовчуванням = 10."""
    search = _make_search(*[f"https://example.com/{i}" for i in range(50)])
    result = discover_sources("тест", existing_urls=set(), _search=search)
    assert len(result) <= 10


def test_discover_result_is_list_of_strings():
    """Результат — список рядків (URLs)."""
    search = _make_search("https://example.com/1")
    result = discover_sources("тест", existing_urls=set(), _search=search)
    assert isinstance(result, list)
    for url in result:
        assert isinstance(url, str)


def test_discover_no_search_returns_empty():
    """Fake _search повертає [] → результат порожній список."""
    # Інжектуємо _search що повертає [] — перевіряємо поведінку без мережі
    result = discover_sources("тест тема", existing_urls=set(), _search=lambda q: [])
    assert result == []


def test_live_search_wired_to_duckduckgo():
    """_live_search imports search.duckduckgo — wiring is testable via source inspection."""
    import inspect
    from fundrec import discover
    src = inspect.getsource(discover._live_search)
    assert "duckduckgo" in src
