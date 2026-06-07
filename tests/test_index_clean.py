"""Страж: web/index.html має лишатися чистим UTF-8 без NUL-байтів.

NUL у роздільнику ключа теплокарти робив файл «бінарним» для текстових
інструментів (код-рев'ю I1). Цей тест ловить регресію.
"""
from __future__ import annotations

from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "web" / "index.html"


def test_index_has_no_nul_bytes():
    assert b"\x00" not in INDEX.read_bytes()


def test_index_is_valid_utf8():
    INDEX.read_text(encoding="utf-8")  # кине UnicodeDecodeError якщо ні
