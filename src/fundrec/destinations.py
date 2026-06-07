"""Уніфіковані призначення донату (destination-centric база).

Одиниця бази — це ПРИЗНАЧЕННЯ донату, а не пост: банка Monobank АБО
конверт PrivatBank АБО donate-лінк. Багато постів дублюють одну й ту саму
банку/конверт → колапсуємо у один збір за призначенням.

extract_privat_ids(text) -> list[str]
    Витягує стабільні id конвертів PrivatBank з тексту. Підтримує:
    privat24.ua/send/<id>, next.privat24.ua/..., www.privat24.ua/rd/send_qr/...,
    link.privatbank.ua/..., privatbank.ua/.... Стабільний id: останній значущий
    сегмент шляху або query-id; fallback — sha1(normalized_url)[:10]. Дедуп.

extract_destinations(raw, *, _client=None) -> list[str]
    Нормалізовані ключі призначень для raw-поста:
      jar:<id>  — через jars.jar_ids_from_raw_resolved (лінки + скорочувачі);
      priv:<id> — через extract_privat_ids над text+links+raw_text+description.
    Унікальні, у порядку першої появи.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from .jars import jar_ids_from_raw_resolved

# Хости конвертів/донат-лінків PrivatBank (lower-case підрядок).
# Порядок патернів: спершу специфічні шляхи (send_qr, send), потім загальні хости.
_PRIVAT_PATTERNS = [
    # www.privat24.ua/rd/send_qr/<id>
    re.compile(r"privat24\.ua/rd/send_qr/([A-Za-z0-9_-]+)", re.IGNORECASE),
    # (next.|www.)privat24.ua/send/<id>
    re.compile(r"privat24\.ua/send/([A-Za-z0-9_-]+)", re.IGNORECASE),
    # link.privatbank.ua/<id>
    re.compile(r"link\.privatbank\.ua/([A-Za-z0-9_-]+)", re.IGNORECASE),
]

# Загальний детектор будь-якого privat-URL (для fallback-хешу).
# Допускаємо як повний https://-URL, так і «голий» хост (privat24.ua/...).
_PRIVAT_URL_PAT = re.compile(
    r"(?:https?://)?[^\s)>\]\"']*(?:privat24\.ua|privatbank\.ua)[^\s)>\]\"']*",
    re.IGNORECASE,
)


def _normalize_url(url: str) -> str:
    """Нормалізує URL для стабільного хешування: lower, без трейлінг-слешу/пробілів."""
    return url.strip().rstrip("/").lower()


def extract_privat_ids(text: str) -> list[str]:
    """Витягує унікальні id конвертів PrivatBank з довільного тексту.

    Стабільний id на конверт: значущий сегмент шляху (send/<id>, send_qr/<id>,
    link.privatbank.ua/<id>) або, як fallback, sha1(normalized_url)[:10].
    Порядок першої появи зберігається; дублікати видаляються.
    Повертає [] якщо нічого не знайдено.
    """
    if not text:
        return []

    seen: set[str] = set()
    result: list[str] = []

    def _add(pid: str) -> None:
        if pid and pid not in seen:
            seen.add(pid)
            result.append(pid)

    # Скануємо у порядку появи URL-ів, щоб зберегти послідовність.
    for m in _PRIVAT_URL_PAT.finditer(text):
        url = m.group(0)
        pid: str | None = None
        for pat in _PRIVAT_PATTERNS:
            seg = pat.search(url)
            if seg:
                pid = seg.group(1)
                break
        if pid is None:
            # Fallback: стабільний хеш нормалізованого URL.
            pid = hashlib.sha1(_normalize_url(url).encode("utf-8")).hexdigest()[:10]
        _add(pid)

    return result


def _privat_ids_from_raw(raw: dict) -> list[str]:
    """Збирає privat-id з усіх текстових полів raw: text, links, raw_text, description."""
    seen: set[str] = set()
    result: list[str] = []

    def _add_from(text: str | None) -> None:
        if not text:
            return
        for pid in extract_privat_ids(text):
            if pid not in seen:
                seen.add(pid)
                result.append(pid)

    _add_from(raw.get("text"))
    for link in raw.get("links") or []:
        _add_from(link)
    _add_from(raw.get("raw_text"))
    _add_from(raw.get("description"))
    return result


def extract_destinations(raw: dict, *, _client: Any | None = None) -> list[str]:
    """Повертає нормалізовані ключі призначень донату для raw-поста.

    Формат ключів:
      jar:<id>  — банки Monobank (через jar_ids_from_raw_resolved: прямі лінки
                  + скорочувачі, якщо інжектовано _client);
      priv:<id> — конверти PrivatBank (через extract_privat_ids).

    Унікальні, у порядку першої появи (спершу jar, потім priv).
    Повертає [] якщо призначень немає.
    """
    seen: set[str] = set()
    result: list[str] = []

    def _add(key: str) -> None:
        if key not in seen:
            seen.add(key)
            result.append(key)

    for jar_id in jar_ids_from_raw_resolved(raw, _client=_client):
        _add(f"jar:{jar_id}")

    for priv_id in _privat_ids_from_raw(raw):
        _add(f"priv:{priv_id}")

    return result
