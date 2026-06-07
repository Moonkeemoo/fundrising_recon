"""Гейт релевантності: is_fundraising(raw) — це збір чи ні?

is_fundraising(raw: dict) -> bool
    Повертає True якщо у raw є хоча б один механізм збору/пожертви:
      1. Посилання на Monobank jar (через jars.jar_ids_from_raw).
      2. Номер картки (16 цифр, можливо з пробілами/тире).
      3. IBAN UA + 27 цифр.
      4. Донат-ключове слово + (сума або URL).
    Інакше — False (топічний/освітній/новинний контент без запиту).

purge_non_fundraising(conn, raw_dir) -> dict
    Для кожної кампанії у БД знаходить raw-файл і перевіряє is_fundraising.
    Якщо raw знайдено і is_fundraising → False — видаляє кампанію (+ її
    creative_assets). Якщо raw НЕ знайдено — залишає (консервативно).
    Повертає {scanned, deleted, kept, no_raw}.

CLI:
    python -m fundrec.relevance --purge [--db PATH] [--raw-dir PATH] [--out PATH]
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from .amounts import parse_amounts_from_text
from .jars import jar_ids_from_raw

# ---------------------------------------------------------------------------
# Regex-константи
# ---------------------------------------------------------------------------

# Номер картки: 16 цифр, розділені пробілами або тире (довільно)
_CARD_PAT = re.compile(r"(?:\d[ -]?){15}\d")

# IBAN: UA + рівно 27 цифр
_IBAN_PAT = re.compile(r"\bUA\d{27}\b")

# Сильні фрази-наміри збору — САМОДОСТАТНІ (механізм часто не в захопленому
# сніпеті, а в кнопці/пінні/біо, але сама назва прямо каже «збір коштів»).
_STRONG_PAT = re.compile(
    r"збір кошт|збір на |збираєм\w* на |оголош\w*\s+збір|терміновий збір|"
    r"відкрит\w* збір|новий збір|"
    r"задонат|донат на |реквізит|потрібно зібрат|допоможіть зібрат|"
    r"допоможи зібрат|благодійн|підтримати збір|підтримати фонд|"
    r"збираємо кошт|зібрати кошт",
    re.IGNORECASE | re.UNICODE,
)

# Донат-ключові слова (слабші — потребують суми/URL поряд)
_DONATE_KW = re.compile(
    r"задонат|донат|підтримати збір|реквізит|банка|монобанк|"
    r"збираємо на|на картку|перекажіть|допомогти збору",
    re.IGNORECASE | re.UNICODE,
)

# URL (http/https або посилання без схеми, але з доменом)
_URL_PAT = re.compile(r"https?://\S+", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Публічний API: is_fundraising
# ---------------------------------------------------------------------------

def _all_text(raw: dict[str, Any]) -> str:
    """Об'єднує text/raw_text, title, description, links у один рядок для пошуку."""
    parts: list[str] = []
    for field in ("text", "raw_text", "title", "description"):
        val = raw.get(field)
        if val:
            parts.append(str(val))
    for link in raw.get("links") or []:
        if link:
            parts.append(str(link))
    return " ".join(parts)


def is_fundraising(raw: dict[str, Any]) -> bool:
    """Повертає True якщо raw містить механізм збору/пожертви.

    Правила (будь-яке з):
    1. Є хоча б один jar-id Monobank.
    2. Є номер картки (16 цифр, можливо з пробілами/тире).
    3. Є IBAN (UA + 27 цифр).
    4. Є донат-ключове слово + (непорожня сума з parse_amounts_from_text АБО URL).

    Консервативно: jar = True безумовно; відсутність механізму = False.
    """
    if not raw:
        return False

    # ── 1. Jar-посилання ────────────────────────────────────────────────────
    # jar_ids_from_raw перевіряє text/links/description; також перевіряємо raw_text
    if jar_ids_from_raw(raw):
        return True
    raw_text_val = raw.get("raw_text") or ""
    if raw_text_val and jar_ids_from_raw({"text": raw_text_val}):
        return True

    # ── Об'єднаний текст для решти перевірок ────────────────────────────────
    combined = _all_text(raw)
    if not combined:
        return False

    # ── 2. Номер картки ─────────────────────────────────────────────────────
    if _CARD_PAT.search(combined):
        return True

    # ── 3. IBAN ──────────────────────────────────────────────────────────────
    if _IBAN_PAT.search(combined):
        return True

    # ── 3.5 Сильні фрази-наміри збору (самодостатні) ─────────────────────────
    if _STRONG_PAT.search(combined):
        return True

    # ── 4. Донат-ключове слово + (сума або URL) ──────────────────────────────
    if _DONATE_KW.search(combined):
        # Перевіряємо наявність URL
        if _URL_PAT.search(combined):
            return True
        # Або непорожньої суми
        amounts = parse_amounts_from_text(combined)
        if amounts.get("amount_uah") is not None or amounts.get("goal_amount") is not None:
            return True

    return False


# ---------------------------------------------------------------------------
# purge_non_fundraising
# ---------------------------------------------------------------------------

def _find_raw_file(campaign: Any, raw_dir: Path) -> Path | None:
    """Знаходить raw-файл для кампанії (дзеркало логіки backfill).

    Спочатку за source_url з provenance, потім glob по id-префіксу.
    """
    # Основний шлях: source_url у provenance
    source_url = (campaign.provenance.get("campaign") or {}).get("source_url") or ""
    if source_url:
        file_id = hashlib.sha256(source_url.encode()).hexdigest()[:16]
        candidate = raw_dir / f"{file_id}.json"
        if candidate.exists():
            return candidate

    # Fallback: glob по id-префіксу (camp-{sha256[:12]} → перші 12 hex)
    id_suffix = campaign.id[5:]  # strip "camp-"
    if len(id_suffix) >= 12:
        prefix = id_suffix[:12]
        candidates = list(raw_dir.glob(f"{prefix}*.json"))
        if candidates:
            return candidates[0]

    return None


def purge_non_fundraising(conn: Any, raw_dir: Path | str) -> dict[str, int]:
    """Видаляє нерелевантні кампанії (не збори) з БД.

    Алгоритм (для кожної кампанії):
      - raw знайдено + is_fundraising(raw) is False → видалити (+ creative_assets).
      - raw НЕ знайдено → залишити (консервативно, немає підстав видаляти).
      - raw знайдено + is_fundraising(raw) is True → залишити.

    Args:
        conn: SQLite connection (ініціалізована БД).
        raw_dir: шлях до директорії сирих кешів.

    Returns:
        {scanned, deleted, kept, no_raw}
    """
    from . import store  # noqa: PLC0415

    raw_dir = Path(raw_dir)
    campaigns = store.load_campaigns(conn)

    scanned = 0
    deleted = 0
    kept = 0
    no_raw = 0

    for campaign in campaigns:
        scanned += 1

        raw_file = _find_raw_file(campaign, raw_dir)
        if raw_file is None:
            no_raw += 1
            kept += 1
            continue

        try:
            raw_item: dict[str, Any] = json.loads(raw_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"relevance: не вдалось зчитати {raw_file}: {exc}", file=sys.stderr)
            kept += 1
            continue

        if is_fundraising(raw_item):
            kept += 1
            continue

        # Видаляємо creative_assets перед видаленням кампанії
        conn.execute(
            "DELETE FROM creative_assets WHERE campaign_id = ?",
            (campaign.id,),
        )
        conn.commit()
        store.delete_campaign(conn, campaign.id)

        print(
            f"relevance: видалено (не збір): {campaign.id} — {campaign.title!r}",
            file=sys.stderr,
        )
        deleted += 1

    return {"scanned": scanned, "deleted": deleted, "kept": kept, "no_raw": no_raw}


# ---------------------------------------------------------------------------
# Двоетапний класифікатор is_campaign
# ---------------------------------------------------------------------------

def build_relevance_prompt(title: str, text: str) -> str:
    """Будує промпт для LLM-судді: це збір чи топічний контент?

    Args:
        title: заголовок допису/кампанії.
        text: тіло тексту (обрізається до ~800 символів).

    Returns:
        Рядок промпту — LLM повинен відповісти СТРОГО JSON {"is_campaign": true|false}.
    """
    snippet = text[:800] if text else ""
    return (
        "Визнач: чи є цей пост ФАНДРАЙЗИНГОВИМ ЗВЕРНЕННЯМ (збір коштів, запит на донат,\n"
        "збір на ЗСУ/медицину/гум.допомогу, є реквізити або посилання на оплату),\n"
        "чи це ТОПІЧНИЙ/ОСВІТНІЙ/НОВИННИЙ контент без прямого запиту на пожертву.\n\n"
        "Відповідай СТРОГО JSON, без зайвого тексту:\n"
        '{"is_campaign": true}   — якщо це ЗБІР (просить задонатити/перекинути кошти)\n'
        '{"is_campaign": false}  — якщо це топічний/освітній/новинний/оглядовий пост\n\n'
        f"Заголовок: {title}\n"
        f"Текст (до 800 символів):\n{snippet}\n"
    )


def parse_relevance_verdict(obj: dict) -> bool:
    """Зчитує is_campaign з відповіді LLM.

    Args:
        obj: розпарсений JSON-словник від судді.

    Returns:
        True якщо is_campaign is True (строго bool), False у всіх інших випадках
        (відсутній ключ, None, рядок, тощо).
    """
    return obj.get("is_campaign") is True


def _live_judge_relevance(prompt: str) -> dict:  # pragma: no cover
    """Жива LLM-класифікація через claude CLI (haiku — дешево і достатньо)."""
    from . import extract  # noqa: PLC0415
    return extract.claude_cli(prompt, "haiku")


def classify_campaign(campaign: Any, raw: dict[str, Any], *, judge: Any = None) -> bool:
    """Класифікує кампанію: True = збір, False = топічний контент.

    Алгоритм:
      1. is_fundraising(raw) → True → повертаємо True (детерміновано, без LLM).
      2. Інакше → judge(build_relevance_prompt(title, text)) → parse_relevance_verdict.

    Args:
        campaign: об'єкт Campaign (потрібен для fallback title).
        raw: сирий словник запису.
        judge: ін'єктована функція (prompt: str) -> dict; за замовч. _live_judge_relevance.

    Returns:
        bool — True якщо збір, False якщо топічний.
    """
    if judge is None:
        judge = _live_judge_relevance  # pragma: no cover

    # Детермінований гейт — без LLM
    if is_fundraising(raw):
        return True

    # Витягаємо title + text з raw
    title = raw.get("title") or campaign.title or ""
    text = raw.get("text") or raw.get("raw_text") or raw.get("description") or ""

    prompt = build_relevance_prompt(title, text)
    result = judge(prompt)
    return parse_relevance_verdict(result)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """CLI: python -m fundrec.relevance --purge [--db PATH] [--raw-dir PATH] [--out PATH]."""
    import argparse  # noqa: PLC0415

    from . import config, export, store  # noqa: PLC0415

    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(
        description="fundrec relevance: видаляє нерелевантні кампанії з БД"
    )
    parser.add_argument("--purge", action="store_true", help="Запустити purge_non_fundraising")
    parser.add_argument("--db", default=str(config.DB_PATH), help="Шлях до SQLite БД")
    parser.add_argument(
        "--raw-dir", default=str(config.RAW_DIR), help="Директорія сирих кешів"
    )
    parser.add_argument(
        "--out", default=str(config.CASES_JSON), help="Шлях до cases.json для re-export"
    )
    args = parser.parse_args(argv)

    if not args.purge:
        parser.print_help()
        return 1

    db_path = Path(args.db)
    raw_dir = Path(args.raw_dir)

    if not db_path.exists():
        print(f"relevance: БД не знайдено: {db_path}", file=sys.stderr)
        return 1

    conn = store.connect(db_path)
    result = purge_non_fundraising(conn, raw_dir)

    # re-export cases.json
    exported = export.export_cases(conn, args.out)

    print(
        f"purge: scanned={result['scanned']} deleted={result['deleted']} "
        f"kept={result['kept']} no_raw={result['no_raw']} exported={exported}",
        file=sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
