"""Tests for derive_themes — keyword-based multi-label theme tagger."""
from __future__ import annotations

import pytest

from fundrec.analyze import derive_themes


def test_fpv_and_fiber():
    result = derive_themes("Збір на FPV-дрони на оптоволокні")
    assert set(result) == {"fpv", "fiber"}


def test_interceptors_shahed():
    result = derive_themes("перехоплювачі шахедів")
    assert set(result) == {"interceptors"}


def test_vehicles_and_medical():
    result = derive_themes("евакуаційне авто + аптечки")
    assert set(result) == {"vehicles", "medical"}


def test_no_match_returns_empty():
    result = derive_themes("якийсь загальний текст без конкретики")
    assert result == []


def test_fpv_mavic():
    result = derive_themes("купуємо mavic для розвідки")
    # mavic -> fpv
    assert "fpv" in result


def test_reb_ew():
    result = derive_themes("реб-система і антидрон")
    assert set(result).issuperset({"reb_ew"})


def test_comms_starlink():
    result = derive_themes("Starlink для зв'язку на передовій")
    assert "comms" in result


def test_energy_generator():
    result = derive_themes("генератор та павербанк")
    assert "energy" in result


def test_ammo():
    result = derive_themes("набої та гранати для бригади")
    assert "ammo" in result


def test_optics():
    result = derive_themes("тепловізор та приціл для снайпера")
    assert "optics_electro" in result


def test_humanitarian():
    result = derive_themes("допомога переселенцям та цивільним")
    assert "humanitarian" in result


def test_recon():
    result = derive_themes("розвідувальний крило для ЗСУ")
    assert "recon" in result


def test_vehicles_machine_word_boundary():
    """'машин' pattern matches 'машина' but should not match 'машинально'."""
    result_match = derive_themes("нова машина для евакуації")
    result_no_match = derive_themes("машинально виконали завдання")
    assert "vehicles" in result_match
    assert "vehicles" not in result_no_match


def test_empty_string_returns_empty():
    assert derive_themes("") == []


def test_none_safe():
    # whitespace-only string
    assert derive_themes("   ") == []


def test_unique_themes_no_duplicates():
    """fpv appears twice in text — result list has no duplicates."""
    result = derive_themes("FPV дрон, fpv коптер, fpv квадрокоптер")
    assert result.count("fpv") == 1
