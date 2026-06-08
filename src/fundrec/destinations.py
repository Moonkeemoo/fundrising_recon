"""Уніфіковані призначення донату (destination-centric база).

Одиниця бази — це ПРИЗНАЧЕННЯ донату, а не пост: банка Monobank АБО
конверт PrivatBank АБО donate-лінк. Багато постів дублюють одну й ту саму
банку/конверт → колапсуємо у один збір за призначенням.

extract_privat_ids(text) -> list[str]
    Витягує стабільні id конвертів PrivatBank з тексту. Підтримує:
    privat24.ua/send/<id>, next.privat24.ua/..., www.privat24.ua/rd/send_qr/...,
    link.privatbank.ua/..., privatbank.ua/.... Стабільний id: останній значущий
    сегмент шляху або query-id; fallback — sha1(normalized_url)[:10]. Дедуп.

donation_candidate_urls(raw) -> list[str]
    Збирає href-и, що є кандидатами на призначення донату, з raw["anchors"]
    (fallback raw["links"]): анкор-текст матчить CTA-патерн АБО href матчить
    донат-хост/шлях. Виключає чисті t.me-навігаційні та соц-профілі (якщо
    текст не сильний CTA). Дедуп, порядок збережено.

extract_destinations(raw, *, _client=None) -> list[str]
    Нормалізовані ключі призначень для raw-поста:
      jar:<id>  — через jars.jar_ids_from_raw_resolved (лінки + скорочувачі);
      priv:<id> — через extract_privat_ids над text+links+raw_text+description;
      url:<sha1[:10]> — донат-лендінг (donation_candidate_urls), що НЕ дав
                  jar:/priv: id (стабільний хеш нормалізованого URL).
    Унікальні, у порядку першої появи (jar → priv → url).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urlsplit

from .jars import extract_jar_ids, jar_ids_from_raw_resolved

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


# ── CTA-сигнали анкор-тексту + донат-хости/шляхи href ────────────────────────

# Українські CTA-фрази у видимому тексті анкора (case-insensitive).
# Ловить «Донать на шахедоріз», «підтримати збір», «реквізити», «банка».
_CTA_TEXT_PAT = re.compile(
    r"донат|задонат|донать|банк(?:а|у|и)|збір\s+на|на\s+збір|реквізит|"
    r"підтрим|допомог|надісл|заслат|скинут(?:ис)?ь?|кинь|monobank|моно|jar",
    re.IGNORECASE,
)

# Донат-інтент хости/шляхи у href (case-insensitive підрядок).
# Хости типу k-2.army/help-us матчаться через /help.
_DONATION_HOST_PAT = re.compile(
    r"send\.monobank\.ua|base\.monobank\.ua|monobank\.ua/jar|"
    r"privat24\.ua|privatbank\.ua|"
    r"/jar|/donate|/donat|/help|/support|/pidtrymka|/zbir",
    re.IGNORECASE,
)

# Соц-профілі/мережі, які НЕ є призначенням донату (якщо текст не сильний CTA).
_SOCIAL_HOST_PAT = re.compile(
    r"facebook\.com|instagram\.com|youtube\.com|youtu\.be|tiktok\.com|"
    r"twitter\.com|x\.com|threads\.net|patreon\.com|(?:wa\.me|whatsapp)",
    re.IGNORECASE,
)

# Чисте t.me-навігаційне посилання: t.me/<channel> або t.me/<channel>/<id>.
_TME_NAV_PAT = re.compile(
    r"^https?://t\.me/[\w+]+(?:/\d+)?/?(?:[?#].*)?$",
    re.IGNORECASE,
)


def _normalize_url(url: str) -> str:
    """Нормалізує URL для стабільного хешування: lower, без трейлінг-слешу/пробілів."""
    return url.strip().rstrip("/").lower()


def _normalize_landing_url(url: str) -> str:
    """Нормалізує лендінг-URL для стабільного id: без схеми, lower-host, без query/fragment.

    Кроки: strip схему → lower host → відкинути query (utm/...) та fragment →
    strip трейлінг-слеш. Path-регістр зберігаємо (деякі сегменти case-sensitive).
    """
    raw = url.strip()
    if "://" not in raw:
        raw = "//" + raw  # дозволяємо «голий» хост
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    path = parts.path.rstrip("/")
    return f"{host}{path}"


def _is_donation_candidate(href: str, text: str) -> bool:
    """Чи є (href, anchor-text) кандидатом на призначення донату.

    True якщо текст матчить _CTA_TEXT_PAT АБО href матчить _DONATION_HOST_PAT.
    Виключення (повертає False): чисте t.me-нав-посилання або соц-профіль,
    ЯКЩО текст не є сильним CTA.
    """
    if not href:
        return False

    strong_cta = bool(text and _CTA_TEXT_PAT.search(text))
    host_hit = bool(_DONATION_HOST_PAT.search(href))

    if not strong_cta and not host_hit:
        return False

    # Якщо текст НЕ сильний CTA — відсіюємо нав/соц-посилання.
    if not strong_cta:
        if _TME_NAV_PAT.match(href):
            return False
        if _SOCIAL_HOST_PAT.search(href):
            return False

    return True


def donation_candidate_urls(raw: dict) -> list[str]:
    """Повертає href-и, що є кандидатами на призначення донату.

    Джерело: raw["anchors"] (list[{"href","text"}]); fallback — raw["links"]
    (list[str], текст порожній). Кандидат = анкор-текст матчить _CTA_TEXT_PAT
    АБО href матчить _DONATION_HOST_PAT, з відсіюванням t.me-нав/соц-профілів
    (якщо текст не сильний CTA). Дедуп за href, порядок першої появи.
    """
    seen: set[str] = set()
    result: list[str] = []

    pairs: list[tuple[str, str]] = []
    anchors = raw.get("anchors")
    if anchors:
        for a in anchors:
            if isinstance(a, dict):
                pairs.append((a.get("href") or "", a.get("text") or ""))
    # Fallback / доповнення: голі links без тексту.
    for link in raw.get("links") or []:
        if link:
            pairs.append((str(link), ""))

    for href, text in pairs:
        if href in seen:
            continue
        if _is_donation_candidate(href, text):
            seen.add(href)
            result.append(href)

    return result


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
      priv:<id> — конверти PrivatBank (через extract_privat_ids);
      url:<sha1(normalized_url)[:10]> — донат-лендінг (donation_candidate_urls),
                  який НЕ дав jar:/priv: id. Нормалізація: без схеми, lower-host,
                  без query(utm)/fragment, без трейлінг-слешу.

    Унікальні, у порядку першої появи (спершу jar, потім priv, потім url).
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

    # Донат-лендінги, що не розпізналися як банка/конверт → стабільний url:-id.
    # Лендінг вважаємо «вже покритим», якщо його href сам містить jar/privat
    # (тоді jar:/priv: вже додано вище — не дублюємо як url:).
    for href in donation_candidate_urls(raw):
        if extract_jar_ids(href) or extract_privat_ids(href):
            continue
        norm = _normalize_landing_url(href)
        url_hash = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:10]
        _add(f"url:{url_hash}")

    return result
