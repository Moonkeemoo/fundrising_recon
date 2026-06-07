"""Дедуплікація і злиття кейсів: dedup_key + merge_cases + campaign_dedup_key + merge_campaigns.

dedup_key(case) -> str:
  Нормалізований ключ: host+path URL (без query/fragment) або slug actor_id+title.

merge_cases(cases) -> list[Case]:
  Кейси з однаковим ключем зливаються:
  - числові поля: перемагає провенанс з найвищим tier (1 > 2 > 3);
  - style / method: union;
  - провенанс: зберігається переможець кожного поля;
  - date_start: найраніша; date_end: найпізніша;
  - confidence_overall: max confidence збережених числових полів.

campaign_dedup_key(campaign) -> str:
  Аналогічно до dedup_key, але для Campaign (використовує url якщо є, інакше actor_id+title).

merge_campaigns(campaigns) -> list[Campaign]:
  Кампанії з однаковим ключем зливаються:
  - числові метрики: перемагає провенанс з найвищим tier;
  - channels / tone / form_factor: union;
  - date_start: найраніша; date_end: найпізніша;
  - confidence_overall: max confidence збережених числових полів.
  ПРИМІТКА: Креативи зберігаються окремо по campaign_id; re-pointing при злитті
  виконується на рівні store (поза scоpом цієї функції).

content_hash(text) -> str | None:
  Нормалізує текст і повертає sha256 hexdigest[:16] перших ~300 символів.
  None для порожнього або None вводу.

campaign_jar_id(campaign) -> str | None:
  Сканує campaign.provenance на source_url банки Monobank → повертає jar_id або None.

campaign_identity(campaign, *, text=None) -> str:
  Jar-centric hybrid ключ:
  1. jar:<jar_id> якщо є банка в провенансі.
  2. content:<hash> якщо є content_hash тексту/title.
  3. actor:<slug_actor>|<slug_title> як fallback.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urlparse

from .jars import extract_jar_ids
from .schema import Campaign, Case

# Числові поля, які конкурують за провенанс
_NUMERIC_FIELDS = ("amount_uah", "amount_usd", "goal_amount")


def _slugify(text: str) -> str:
    """Перетворює текст на ASCII-slug (для fallback-ключа)."""
    # Нормалізуємо Unicode → ASCII
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^\w\s-]", "", ascii_text.lower())
    return re.sub(r"[\s_-]+", "_", slug).strip("_")


def dedup_key(case: Case) -> str:
    """Повертає нормалізований ключ кейсу для дедуплікації.

    Пріоритет: URL host+path (без query/fragment, без trailing slash).
    Fallback: slug з actor_id + title (коли URL порожній або нераспізнається).
    """
    url = (case.url or "").strip()
    if url:
        try:
            parsed = urlparse(url)
            host = parsed.hostname or ""
            path = parsed.path.rstrip("/")
            if host:
                return f"{host}{path}".lower()
        except Exception:
            pass

    # Fallback: slug з actor_id + title
    return _slugify(f"{case.actor_id}_{case.title}")


def _tier_of(prov: dict, field: str) -> int:
    """Повертає tier провенансу поля або 99 якщо нема."""
    entry = prov.get(field)
    if isinstance(entry, dict):
        return int(entry.get("tier", 99))
    return 99


def _confidence_of(prov: dict, field: str) -> float:
    """Повертає confidence провенансу поля або 0.0 якщо нема."""
    entry = prov.get(field)
    if isinstance(entry, dict):
        return float(entry.get("confidence", 0.0))
    return 0.0


def _merge_two(a: Case, b: Case) -> Case:
    """Зливає два кейси в один. Мутує перший, повертає новий об'єкт."""
    # Числові поля: перемагає найвищий tier (менше число = вищий tier)
    new_provenance: dict = dict(a.provenance)
    new_values: dict = {}

    for field in _NUMERIC_FIELDS:
        tier_a = _tier_of(a.provenance, field)
        tier_b = _tier_of(b.provenance, field)
        val_a = getattr(a, field)
        val_b = getattr(b, field)

        # Вибираємо переможця: менший tier (1 < 2 < 3) перемагає
        if val_b is not None and (val_a is None or tier_b < tier_a):
            new_values[field] = val_b
            new_provenance[field] = b.provenance[field]
        elif val_a is not None:
            new_values[field] = val_a
            if field in a.provenance:
                new_provenance[field] = a.provenance[field]
        else:
            new_values[field] = None

        # Якщо tier однаковий — беремо значення з більшим confidence
        if val_a is not None and val_b is not None and tier_a == tier_b:
            conf_a = _confidence_of(a.provenance, field)
            conf_b = _confidence_of(b.provenance, field)
            if conf_b > conf_a:
                new_values[field] = val_b
                if field in b.provenance:
                    new_provenance[field] = b.provenance[field]

    # style / method: union (зберігаємо порядок)
    merged_style = list(dict.fromkeys(a.style + b.style))
    merged_method = list(dict.fromkeys(a.method + b.method))

    # Дати: найраніша date_start, найпізніша date_end
    dates_start = [d for d in (a.date_start, b.date_start) if d]
    dates_end = [d for d in (a.date_end, b.date_end) if d]
    merged_date_start = min(dates_start) if dates_start else None
    merged_date_end = max(dates_end) if dates_end else None

    # confidence_overall: max confidence збережених числових полів
    confidences = [
        _confidence_of(new_provenance, f)
        for f in _NUMERIC_FIELDS
        if new_values.get(f) is not None and f in new_provenance
    ]
    new_confidence = max(confidences) if confidences else max(a.confidence_overall, b.confidence_overall)

    # id: зберігаємо перший (або менший за алфавітом для детермінізму)
    merged_id = a.id if a.id <= b.id else b.id

    return Case(
        id=merged_id,
        title=a.title or b.title,
        actor_id=a.actor_id or b.actor_id,
        url=a.url or b.url,
        goal=a.goal or b.goal,
        style=merged_style,
        method=merged_method,
        date_start=merged_date_start,
        date_end=merged_date_end,
        year=a.year or b.year,
        amount_uah=new_values.get("amount_uah"),
        amount_usd=new_values.get("amount_usd"),
        goal_amount=new_values.get("goal_amount"),
        currency_raw=a.currency_raw or b.currency_raw,
        provenance=new_provenance,
        confidence_overall=new_confidence,
        verification_status=a.verification_status,
        extracted_at=a.extracted_at or b.extracted_at,
        extracted_by_model=a.extracted_by_model or b.extracted_by_model,
    )


def merge_cases(cases: list[Case]) -> list[Case]:
    """Дедуплікує і зливає кейси за ключем dedup_key.

    Для кожного унікального ключа послідовно зливає всі кейси з цим ключем.
    """
    if not cases:
        return []

    # Групуємо за ключем (зберігаємо порядок першого входження)
    groups: dict[str, list[Case]] = {}
    for c in cases:
        key = dedup_key(c)
        groups.setdefault(key, []).append(c)

    result: list[Case] = []
    for group in groups.values():
        merged = group[0]
        for other in group[1:]:
            merged = _merge_two(merged, other)
        result.append(merged)

    return result


# ---------------------------------------------------------------------------
# Campaign dedup (F3)
# ---------------------------------------------------------------------------

# Числові метрики кампанії, що конкурують за провенанс
_CAMPAIGN_NUMERIC_FIELDS = ("amount_uah", "amount_usd", "reach", "engagement", "spend", "assets_count")


def _stable_key(text: str) -> str:
    """Будує стабільний ключ: ASCII-slug + sha256-хеш (8 hex) оригіналу.

    sha256-хеш завжди додається щоб зберегти унікальність для Cyrillic-текстів,
    де slug деградує до actor_id і не розрізняє різні назви.
    """
    import hashlib

    slug = _slugify(text)
    h = hashlib.sha256(text.lower().encode("utf-8")).hexdigest()[:8]
    return f"{slug}_{h}" if slug else h


def campaign_dedup_key(campaign: Campaign) -> str:
    """Повертає нормалізований ключ кампанії для дедуплікації.

    Campaign не має поля url, тому ключ будується як slug з actor_id + title.
    Для тестів на Cyrillic-текстах додається sha256-хеш (8 hex) щоб зберегти унікальність.
    Це стабільний ключ: кампанія того самого актора з тією самою назвою — один запис.
    """
    return _stable_key(f"{campaign.actor_id}_{campaign.title}")


def _campaign_merge_two(a: Campaign, b: Campaign) -> Campaign:
    """Зливає дві кампанії. Повертає новий об'єкт Campaign."""
    new_provenance: dict = dict(a.provenance)
    new_values: dict = {}

    for field in _CAMPAIGN_NUMERIC_FIELDS:
        tier_a = _tier_of(a.provenance, field)
        tier_b = _tier_of(b.provenance, field)
        val_a = getattr(a, field)
        val_b = getattr(b, field)

        if val_b is not None and (val_a is None or tier_b < tier_a):
            new_values[field] = val_b
            new_provenance[field] = b.provenance[field]
        elif val_a is not None:
            new_values[field] = val_a
            if field in a.provenance:
                new_provenance[field] = a.provenance[field]
        else:
            new_values[field] = None

        if val_a is not None and val_b is not None and tier_a == tier_b:
            conf_a = _confidence_of(a.provenance, field)
            conf_b = _confidence_of(b.provenance, field)
            if conf_b > conf_a:
                new_values[field] = val_b
                if field in b.provenance:
                    new_provenance[field] = b.provenance[field]

    # channels / tone / form_factor: union (зберігаємо порядок)
    merged_channels = list(dict.fromkeys((a.channels or []) + (b.channels or [])))
    merged_tone = list(dict.fromkeys((a.tone or []) + (b.tone or [])))
    merged_form_factor = list(dict.fromkeys((a.form_factor or []) + (b.form_factor or [])))

    # Дати
    dates_start = [d for d in (a.date_start, b.date_start) if d]
    dates_end = [d for d in (a.date_end, b.date_end) if d]
    merged_date_start = min(dates_start) if dates_start else None
    merged_date_end = max(dates_end) if dates_end else None

    # confidence_overall
    confidences = [
        _confidence_of(new_provenance, f)
        for f in _CAMPAIGN_NUMERIC_FIELDS
        if new_values.get(f) is not None and f in new_provenance
    ]
    new_confidence = max(confidences) if confidences else max(a.confidence_overall, b.confidence_overall)

    # id: менший за алфавітом для детермінізму
    merged_id = a.id if a.id <= b.id else b.id

    # Coalesce: canonical (a) wins якщо не None; інакше береться b
    merged_is_campaign = a.is_campaign if a.is_campaign is not None else b.is_campaign
    merged_goal_reached = a.goal_reached if a.goal_reached is not None else b.goal_reached
    merged_verdict_reason = a.verdict_reason if a.verdict_reason is not None else b.verdict_reason

    return Campaign(
        id=merged_id,
        actor_id=a.actor_id or b.actor_id,
        title=a.title or b.title,
        goal=a.goal or b.goal,
        type=a.type or b.type,
        channels=merged_channels,
        date_start=merged_date_start,
        date_end=merged_date_end,
        year=a.year or b.year,
        form_factor=merged_form_factor,
        cta_type=a.cta_type or b.cta_type,
        tone=merged_tone,
        face=a.face or b.face,
        cadence=a.cadence or b.cadence,
        playbook_note=a.playbook_note or b.playbook_note,
        amount_uah=new_values.get("amount_uah"),
        amount_usd=new_values.get("amount_usd"),
        reach=new_values.get("reach"),
        engagement=new_values.get("engagement"),
        spend=new_values.get("spend"),
        assets_count=new_values.get("assets_count"),
        goal_reached=merged_goal_reached,
        is_campaign=merged_is_campaign,
        case_id=a.case_id or b.case_id,
        partner_ids=list(dict.fromkeys((a.partner_ids or []) + (b.partner_ids or []))),
        provenance=new_provenance,
        confidence_overall=new_confidence,
        verification_status=a.verification_status,
        verdict_reason=merged_verdict_reason,
        extracted_at=a.extracted_at or b.extracted_at,
        extracted_by_model=a.extracted_by_model or b.extracted_by_model,
    )


def merge_campaigns(campaigns: list[Campaign]) -> list[Campaign]:
    """Дедуплікує і зливає кампанії за ключем campaign_dedup_key.

    Для кожного унікального ключа послідовно зливає всі кампанії з цим ключем.
    ПРИМІТКА: Злиття Campaign не переприв'язує CreativeAsset — це відповідальність
    store. Surviving campaign зберігає менший id (алфавітно) для детермінізму.
    """
    if not campaigns:
        return []

    groups: dict[str, list[Campaign]] = {}
    for c in campaigns:
        key = campaign_dedup_key(c)
        groups.setdefault(key, []).append(c)

    result: list[Campaign] = []
    for group in groups.values():
        merged = group[0]
        for other in group[1:]:
            merged = _campaign_merge_two(merged, other)
        result.append(merged)

    return result


# ---------------------------------------------------------------------------
# Jar-centric identity helpers (Unit 1 — dedup engine)
# ---------------------------------------------------------------------------

# Regex для видалення URL з тексту перед нормалізацією
_URL_PAT = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
# Regex для видалення емодзі (Unicode категорія So/Sm/Sk/Cf та Emoji blocks)
_EMOJI_PAT = re.compile(
    "["
    "\U0001f600-\U0001f64f"
    "\U0001f300-\U0001f5ff"
    "\U0001f680-\U0001f9ff"
    "\U00002600-\U000027bf"
    "\U0001fa00-\U0001faff"
    "]+",
    re.UNICODE,
)


def content_hash(text: str | None) -> str | None:
    """Нормалізує текст і повертає sha256 hexdigest[:16] перших ~300 символів.

    Нормалізація: lowercase → видалити URL → видалити емодзі → видалити пунктуацію
    → collapse whitespace → взяти перші 300 символів.
    Повертає None для порожнього або None вводу.
    """
    if not text:
        return None
    t = text.lower()
    t = _URL_PAT.sub(" ", t)
    t = _EMOJI_PAT.sub(" ", t)
    # Видаляємо пунктуацію (залишаємо літери/цифри/пробіли)
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return None
    snippet = t[:300]
    return hashlib.sha256(snippet.encode("utf-8")).hexdigest()[:16]


def campaign_jar_id(campaign: Campaign) -> str | None:
    """Сканує campaign.provenance на source_url банки Monobank → jar_id або None.

    Перевіряє кожне поле провенансу; якщо source_url містить
    send.monobank.ua/jar/<id> — повертає перший знайдений jar_id.
    """
    for entry in campaign.provenance.values():
        if not isinstance(entry, dict):
            continue
        url = entry.get("source_url", "")
        if not url:
            continue
        ids = extract_jar_ids(str(url))
        if ids:
            return ids[0]
    return None


def campaign_identity(campaign: Campaign, *, text: str | None = None) -> str:
    """Jar-centric hybrid ключ ідентичності кампанії.

    Пріоритети:
    1. ``jar:<jar_id>`` — якщо в провенансі є source_url банки Monobank.
    2. ``content:<hash>`` — якщо є content_hash тексту (або campaign.title).
    3. ``actor:<slug_actor>|<slug_title>`` — fallback за actor_id + normalized title.
    """
    jar_id = campaign_jar_id(campaign)
    if jar_id:
        return f"jar:{jar_id}"

    effective_text = text if text is not None else (campaign.title or "")
    h = content_hash(effective_text)
    if h:
        return f"content:{h}"

    # Fallback: actor + title slug
    actor_slug = _slugify(campaign.actor_id or "")
    title_slug = _slugify(campaign.title or "")
    return f"actor:{actor_slug}|{title_slug}"
