"""Модуль пошуку: провайдери веб-пошуку для discover."""
from __future__ import annotations

from .duckduckgo import search as duckduckgo_search

__all__ = ["duckduckgo_search"]
