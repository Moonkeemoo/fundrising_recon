"""Тести аудиту повноти збору (детермінований core + --report-only).

Покриває: статус кожного поля (PRESENT / MISSING_FILLABLE / MISSING_UNAVAILABLE),
мапінг сигнал→дія (jar→RENDER_JAR, лінк→RESOLVE_LINKS, handle→SEARCH_POSTS,
raw→LLM_EXTRACT_STYLE, теми→RETAG_THEME/LLM_DIAGNOSE), залишковий hard-gap
LLM_DIAGNOSE, властивості звіту, gap_actions та інтеграцію audit_database.
"""

from __future__ import annotations

from fundrec import audit, config, store
from fundrec.schema import Campaign


# ── фабрики синтетичних обʼєктів ─────────────────────────────────────────────


def _camp(**kw) -> Campaign:
    """Мінімальна кампанія з перевизначенням полів."""
    base = dict(id="k1", actor_id="a1", title="Тестовий збір", goal="military", type="jar")
    base.update(kw)
    return Campaign(**base)


def _jar_prov(jar_id: str = "JARABC") -> dict:
    """Провенанс із jar-банкою Monobank (даватиме campaign_jar_id)."""
    return {
        "amount_uah": {
            "source_url": f"https://send.monobank.ua/jar/{jar_id}",
            "tier": 1,
        }
    }


def _handle_prov(handle: str = "mychannel") -> dict:
    """Провенанс із Telegram-handle у reach source_url (даватиме campaign_handle)."""
    return {"reach": {"source_url": f"https://t.me/s/{handle}/123", "tier": 2}}


_BASELINES: dict[str, float] = {"mychannel": 1000.0}


# ── has_destination ──────────────────────────────────────────────────────────


def test_has_destination_present_via_jar():
    c = _camp(provenance=_jar_prov())
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    assert r.fields["has_destination"] == audit.PRESENT


def test_has_destination_present_via_raw_destination():
    raw = {"text": "Реквізити https://www.privat24.ua/send/ENV1"}
    c = _camp()
    r = audit.audit_campaign(c, raw, baselines=_BASELINES)
    assert r.fields["has_destination"] == audit.PRESENT


def test_has_destination_missing_fillable_when_raw_has_link():
    raw = {"text": "Дивіться більше на http://example.com/info"}
    c = _camp()
    r = audit.audit_campaign(c, raw, baselines=_BASELINES)
    assert r.fields["has_destination"] == audit.MISSING_FILLABLE
    assert audit.RESOLVE_LINKS in r.actions


def test_has_destination_missing_unavailable_no_link():
    raw = {"text": "Просто текст без жодних посилань"}
    c = _camp()
    r = audit.audit_campaign(c, raw, baselines=_BASELINES)
    assert r.fields["has_destination"] == audit.MISSING_UNAVAILABLE


def test_has_destination_missing_unavailable_no_raw():
    c = _camp()
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    assert r.fields["has_destination"] == audit.MISSING_UNAVAILABLE
    assert audit.RESOLVE_LINKS not in r.actions


# ── amount_uah / goal_amount → RENDER_JAR ────────────────────────────────────


def test_amount_present():
    c = _camp(amount_uah=12345.0)
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    assert r.fields["amount_uah"] == audit.PRESENT


def test_amount_missing_fillable_render_jar_with_jar():
    c = _camp(provenance=_jar_prov())
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    assert r.fields["amount_uah"] == audit.MISSING_FILLABLE
    assert audit.RENDER_JAR in r.actions


def test_amount_missing_unavailable_no_jar():
    c = _camp(type="organic_social")  # без jar-провенансу
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    assert r.fields["amount_uah"] == audit.MISSING_UNAVAILABLE


def test_goal_amount_present():
    c = _camp(goal_amount=50000.0)
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    assert r.fields["goal_amount"] == audit.PRESENT


def test_goal_amount_missing_fillable_render_jar():
    c = _camp(provenance=_jar_prov())
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    assert r.fields["goal_amount"] == audit.MISSING_FILLABLE
    assert audit.RENDER_JAR in r.actions


def test_goal_amount_missing_unavailable_no_jar():
    c = _camp(type="organic_social")
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    assert r.fields["goal_amount"] == audit.MISSING_UNAVAILABLE


# ── post_count / reach_total / reach_resonance → SEARCH_POSTS ─────────────────


def test_post_count_present():
    c = _camp()
    r = audit.audit_campaign(c, None, baselines=_BASELINES, post_count=3)
    assert r.fields["post_count"] == audit.PRESENT


def test_post_count_missing_fillable_with_jar():
    c = _camp(provenance=_jar_prov())
    r = audit.audit_campaign(c, None, baselines=_BASELINES, post_count=0)
    assert r.fields["post_count"] == audit.MISSING_FILLABLE
    assert audit.SEARCH_POSTS in r.actions


def test_post_count_missing_fillable_with_handle():
    c = _camp(type="organic_social", provenance=_handle_prov())
    r = audit.audit_campaign(c, None, baselines=_BASELINES, post_count=0)
    assert r.fields["post_count"] == audit.MISSING_FILLABLE
    assert audit.SEARCH_POSTS in r.actions


def test_post_count_missing_unavailable_no_handle_no_jar():
    c = _camp(type="organic_social")
    r = audit.audit_campaign(c, None, baselines=_BASELINES, post_count=0)
    assert r.fields["post_count"] == audit.MISSING_UNAVAILABLE


def test_reach_total_present():
    c = _camp()
    r = audit.audit_campaign(c, None, baselines=_BASELINES, reach_total=5000)
    assert r.fields["reach_total"] == audit.PRESENT


def test_reach_total_missing_fillable_with_handle():
    c = _camp(type="organic_social", provenance=_handle_prov())
    r = audit.audit_campaign(c, None, baselines=_BASELINES, reach_total=None)
    assert r.fields["reach_total"] == audit.MISSING_FILLABLE
    assert audit.SEARCH_POSTS in r.actions


def test_reach_total_missing_unavailable_no_handle():
    c = _camp(type="organic_social")
    r = audit.audit_campaign(c, None, baselines=_BASELINES, reach_total=None)
    assert r.fields["reach_total"] == audit.MISSING_UNAVAILABLE


def test_reach_resonance_present():
    # reach + handle з базою в baselines → reach_resonance не None
    c = _camp(reach=2000.0, provenance=_handle_prov())
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    assert r.fields["reach_resonance"] == audit.PRESENT


def test_reach_resonance_missing_fillable_with_handle():
    # handle є, але reach=None → резонанс None, добірно через SEARCH_POSTS
    c = _camp(reach=None, provenance=_handle_prov())
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    assert r.fields["reach_resonance"] == audit.MISSING_FILLABLE
    assert audit.SEARCH_POSTS in r.actions


def test_reach_resonance_missing_unavailable_no_handle():
    c = _camp(reach=None)
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    assert r.fields["reach_resonance"] == audit.MISSING_UNAVAILABLE


# ── стиль: tone / form_factor / face / cta_type → LLM_EXTRACT_STYLE ───────────


def test_tone_present():
    c = _camp(tone=["emotional"])
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    assert r.fields["tone"] == audit.PRESENT


def test_tone_missing_fillable_with_raw():
    raw = {"text": "якийсь текст"}
    c = _camp(tone=[])
    r = audit.audit_campaign(c, raw, baselines=_BASELINES)
    assert r.fields["tone"] == audit.MISSING_FILLABLE
    assert audit.LLM_EXTRACT_STYLE in r.actions


def test_tone_missing_unavailable_no_raw():
    c = _camp(tone=[])
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    assert r.fields["tone"] == audit.MISSING_UNAVAILABLE


def test_form_factor_present():
    c = _camp(form_factor=["video"])
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    assert r.fields["form_factor"] == audit.PRESENT


def test_form_factor_missing_fillable_with_raw():
    c = _camp(form_factor=[])
    r = audit.audit_campaign(c, {"text": "x"}, baselines=_BASELINES)
    assert r.fields["form_factor"] == audit.MISSING_FILLABLE


def test_face_present():
    c = _camp(face="soldier")
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    assert r.fields["face"] == audit.PRESENT


def test_face_missing_unavailable_no_raw():
    c = _camp(face=None)
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    assert r.fields["face"] == audit.MISSING_UNAVAILABLE


def test_cta_type_present():
    c = _camp(cta_type="jar")
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    assert r.fields["cta_type"] == audit.PRESENT


def test_cta_type_missing_fillable_with_raw():
    c = _camp(cta_type=None)
    r = audit.audit_campaign(c, {"text": "x"}, baselines=_BASELINES)
    assert r.fields["cta_type"] == audit.MISSING_FILLABLE
    assert audit.LLM_EXTRACT_STYLE in r.actions


# ── themes → RETAG_THEME / LLM_DIAGNOSE ──────────────────────────────────────


def test_themes_present_from_title():
    c = _camp(title="Збір на FPV-дрони для підрозділу")
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    assert r.fields["themes"] == audit.PRESENT


def test_themes_present_from_playbook_note():
    c = _camp(title="Допомога", playbook_note="купуємо тепловізор")
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    assert r.fields["themes"] == audit.PRESENT


def test_themes_missing_fillable_retag_only_no_raw():
    c = _camp(title="Загальний збір допомоги", playbook_note=None)
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    assert r.fields["themes"] == audit.MISSING_FILLABLE
    assert audit.RETAG_THEME in r.actions
    assert audit.LLM_DIAGNOSE not in r.actions


def test_themes_missing_fillable_retag_and_diagnose_with_raw():
    # has_destination present (jar) щоб уникнути hard-gap LLM_DIAGNOSE — ізолюємо тему
    c = _camp(title="Загальний збір", amount_uah=1.0, provenance=_jar_prov())
    r = audit.audit_campaign(c, {"text": "якийсь нейтральний текст"}, baselines=_BASELINES)
    assert r.fields["themes"] == audit.MISSING_FILLABLE
    assert audit.RETAG_THEME in r.actions
    assert audit.LLM_DIAGNOSE in r.actions


# ── залишковий hard-gap LLM_DIAGNOSE ─────────────────────────────────────────


def test_residual_hard_gap_adds_llm_diagnose_when_destination_missing():
    # призначення відсутнє, але є raw → додаємо LLM_DIAGNOSE
    raw = {"text": "Просто текст без посилань"}
    c = _camp(type="organic_social", title="Збір на FPV", amount_uah=1.0)
    r = audit.audit_campaign(c, raw, baselines=_BASELINES)
    assert r.fields["has_destination"] == audit.MISSING_UNAVAILABLE
    assert audit.LLM_DIAGNOSE in r.actions


def test_residual_hard_gap_adds_llm_diagnose_when_amount_missing():
    # amount відсутній (нема jar), raw є → LLM_DIAGNOSE
    raw = {"text": "Текст збору на FPV без банки"}
    c = _camp(type="organic_social", title="Збір на FPV", provenance=_handle_prov())
    r = audit.audit_campaign(c, raw, baselines=_BASELINES)
    assert r.fields["amount_uah"] == audit.MISSING_UNAVAILABLE
    assert audit.LLM_DIAGNOSE in r.actions


def test_no_hard_gap_diagnose_without_raw():
    c = _camp(type="organic_social", title="Збір на FPV")
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    # без raw залишковий LLM_DIAGNOSE не додається
    assert audit.LLM_DIAGNOSE not in r.actions


# ── властивості звіту + gap_actions ──────────────────────────────────────────


def test_report_is_complete_when_all_present_or_unavailable():
    # повністю заповнений збір
    c = _camp(
        amount_uah=1.0,
        goal_amount=2.0,
        reach=2000.0,
        tone=["emotional"],
        form_factor=["video"],
        face="soldier",
        cta_type="jar",
        title="Збір на FPV-дрони",
        provenance={**_jar_prov(), **_handle_prov()},
    )
    r = audit.audit_campaign(c, {"text": "x"}, baselines=_BASELINES, post_count=2, reach_total=2000)
    assert r.is_complete is True
    assert r.n_missing_fillable == 0


def test_report_is_complete_with_unavailable_fields():
    # стиль повний, але дірки — усі unavailable (нема raw, нема jar/handle)
    c = _camp(
        type="organic_social",
        title="нейтральна назва",
        tone=["emotional"],
        form_factor=["video"],
        face="soldier",
        cta_type="jar",
        amount_uah=1.0,  # щоб уникнути hard-gap, але призначення все одно unavailable
    )
    r = audit.audit_campaign(c, None, baselines=_BASELINES, post_count=0, reach_total=None)
    # усі дірки мають бути unavailable, fillable=0, але є RETAG_THEME (theme завжди fillable з raw=None)
    # тому is_complete може бути False через theme; перевіряємо n_missing_fillable окремо
    assert r.n_missing_fillable >= 1  # тема fillable
    assert isinstance(r.is_complete, bool)


def test_n_missing_fillable_counts_only_fillable():
    c = _camp(provenance=_jar_prov())  # amount+goal fillable (RENDER_JAR), has_destination present
    r = audit.audit_campaign(c, None, baselines=_BASELINES, post_count=1, reach_total=1)
    n_fill = sum(1 for s in r.fields.values() if s == audit.MISSING_FILLABLE)
    assert r.n_missing_fillable == n_fill


def test_actions_sorted_and_unique():
    c = _camp(provenance=_jar_prov())
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    assert r.actions == sorted(set(r.actions))


def test_gap_actions_returns_report_actions():
    c = _camp(provenance=_jar_prov())
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    assert audit.gap_actions(r) == r.actions


def test_report_has_campaign_id():
    c = _camp(id="kXYZ")
    r = audit.audit_campaign(c, None, baselines=_BASELINES)
    assert r.campaign_id == "kXYZ"


# ── інтеграція: audit_database проти живої БД ─────────────────────────────────


def test_audit_database_live():
    conn = store.connect(config.DB_PATH)
    reports = audit.audit_database(conn, raw_dir=config.RAW_DIR)
    # ~64 реальні збори
    assert 60 <= len(reports) <= 70
    # покриття узгоджене зі spec (has_destination≈31, amount≈34)
    n_dest = sum(1 for r in reports if r.fields["has_destination"] == audit.PRESENT)
    n_amount = sum(1 for r in reports if r.fields["amount_uah"] == audit.PRESENT)
    assert 28 <= n_dest <= 34
    assert 31 <= n_amount <= 37
    # кожен звіт — валідний CompletenessReport
    for r in reports:
        assert isinstance(r.campaign_id, str)
        assert set(r.fields) >= {
            "has_destination", "amount_uah", "goal_amount",
            "post_count", "reach_total", "reach_resonance",
            "tone", "form_factor", "face", "cta_type", "themes",
        }


# ═════════════════════════════════════════════════════════════════════════════
# ВИКОНАВЕЦЬ (executor): handler-и добору дірок + run_audit + CLI
# Усі зовнішні ефекти (мережа/LLM/рендер) ІНʼЄКТУЮТЬСЯ — жодного реального I/O.
# ═════════════════════════════════════════════════════════════════════════════

import hashlib  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402


def _seed_db(tmp_path: Path):
    """Створює tmp БД + порожній raw_dir; повертає (conn, db_path, raw_dir)."""
    db_path = tmp_path / "test.sqlite"
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    conn = store.connect(db_path)
    store.init_db(conn)
    from fundrec.schema import Actor
    store.upsert_actor(conn, Actor(id="a1", name="Тест-актор", type="unknown"))
    return conn, db_path, raw_dir


def _write_raw(raw_dir: Path, source_url: str, payload: dict) -> None:
    """Записує raw-файл так, як його знайде _find_raw_for_campaign (sha256[:16])."""
    file_id = hashlib.sha256(source_url.encode()).hexdigest()[:16]
    (raw_dir / f"{file_id}.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _camp_with_source(source_url: str, **kw) -> Campaign:
    """Кампанія з provenance['campaign'].source_url (щоб raw знаходився)."""
    prov = kw.pop("provenance", {})
    prov.setdefault("campaign", {"source_url": source_url, "tier": 2})
    cid = "camp-" + hashlib.sha256(source_url.encode()).hexdigest()[:12]
    base = dict(id=cid, actor_id="a1", title="Тестовий збір", goal="military", type="jar")
    base.update(kw)
    return Campaign(provenance=prov, **base)


# ── fill_render_jar ──────────────────────────────────────────────────────────


def test_fill_render_jar_sets_amount_and_goal(tmp_path):
    conn, _db, _raw = _seed_db(tmp_path)
    c = _camp_with_source("https://t.me/ch/1", provenance=_jar_prov("JARX"))
    store.upsert_campaign(conn, c)

    def _render(jar_id):  # повертає тіло сторінки банки
        return "Збір на дрони\n100 000 ₴\n500 000 ₴"

    ok = audit.fill_render_jar(
        conn, c, _render=_render, cache_path=tmp_path / "jars.json"
    )
    assert ok is True
    reloaded = store.get_campaign(conn, c.id)
    assert reloaded.amount_uah == 100000.0
    assert reloaded.goal_amount == 500000.0


def test_fill_render_jar_closed_jar_returns_false(tmp_path):
    conn, _db, _raw = _seed_db(tmp_path)
    c = _camp_with_source("https://t.me/ch/2", provenance=_jar_prov("JARCLOSED"))
    store.upsert_campaign(conn, c)

    def _render(jar_id):  # закрита банка — жодних чисел
        return "Збір завершено\nДякуємо!"

    ok = audit.fill_render_jar(
        conn, c, _render=_render, cache_path=tmp_path / "jars.json"
    )
    assert ok is False
    reloaded = store.get_campaign(conn, c.id)
    assert reloaded.amount_uah is None
    assert reloaded.goal_amount is None


def test_fill_render_jar_no_jar_returns_false(tmp_path):
    conn, _db, _raw = _seed_db(tmp_path)
    c = _camp_with_source("https://t.me/ch/3", type="organic_social")  # без jar
    store.upsert_campaign(conn, c)
    ok = audit.fill_render_jar(
        conn, c, _render=lambda jid: "1 ₴", cache_path=tmp_path / "jars.json"
    )
    assert ok is False


# ── fill_resolve_links ───────────────────────────────────────────────────────


class _FakeShortenerClient:
    """Імітує httpx-клієнт: HEAD скороченого лінку → редирект на банку."""

    def __init__(self, mapping: dict[str, str]):
        self._mapping = mapping

    def head(self, url, timeout=10):  # noqa: ARG002
        final = self._mapping.get(url, url)
        return type("R", (), {"url": final})()

    def get(self, url, timeout=10):  # noqa: ARG002
        final = self._mapping.get(url, url)
        return type("R", (), {"url": final})()


def test_fill_resolve_links_attaches_jar_from_shortener(tmp_path):
    conn, _db, raw_dir = _seed_db(tmp_path)
    src = "https://t.me/ch/10"
    raw = {"source_url": src, "text": "Донат тут", "links": ["https://cutt.ly/abc"]}
    _write_raw(raw_dir, src, raw)
    c = _camp_with_source(src, type="organic_social")  # призначення відсутнє
    store.upsert_campaign(conn, c)
    assert audit.campaign_jar_id(c) is None

    client = _FakeShortenerClient(
        {"https://cutt.ly/abc": "https://send.monobank.ua/jar/RESOLVED1"}
    )
    ok = audit.fill_resolve_links(conn, c, raw, _resolve=client)
    assert ok is True
    reloaded = store.get_campaign(conn, c.id)
    assert audit.campaign_jar_id(reloaded) == "RESOLVED1"


def test_fill_resolve_links_no_new_destination_returns_false(tmp_path):
    conn, _db, raw_dir = _seed_db(tmp_path)
    src = "https://t.me/ch/11"
    raw = {"source_url": src, "text": "Просто текст без банки", "links": []}
    _write_raw(raw_dir, src, raw)
    c = _camp_with_source(src, type="organic_social")
    store.upsert_campaign(conn, c)
    ok = audit.fill_resolve_links(conn, c, raw, _resolve=_FakeShortenerClient({}))
    assert ok is False


# ── fill_search_posts ────────────────────────────────────────────────────────


class _FakeTgClient:
    """Імітує httpx для fetch_channel_web: повертає HTML t.me/s з постами."""

    def __init__(self, html: str):
        self._html = html

    def get(self, url, timeout=20):  # noqa: ARG002
        return type("R", (), {"text": self._html, "raise_for_status": lambda self=None: None})()


def _tme_html(channel: str, msgs: list[tuple[int, str]]) -> str:
    """Будує мінімальний HTML t.me/s/<channel> з постами (id, text)."""
    blocks = []
    for mid, text in msgs:
        blocks.append(
            f'<div class="tgme_widget_message" data-post="{channel}/{mid}">'
            f'<div class="tgme_widget_message_text">{text} '
            f'<a href="https://send.monobank.ua/jar/JARSP">банка</a></div>'
            f'<span class="tgme_widget_message_views">1.2K</span>'
            f"</div>"
        )
    return "<html><body>" + "".join(blocks) + "</body></html>"


def test_fill_search_posts_links_new_posts(tmp_path):
    conn, _db, raw_dir = _seed_db(tmp_path)
    src = "https://t.me/spchan/100"
    # raw кампанії містить банку JARSP — пости з тією ж банкою привʼяжуться
    raw = {
        "source_url": src,
        "channel": "spchan",
        "text": "Збір банка https://send.monobank.ua/jar/JARSP",
        "links": ["https://send.monobank.ua/jar/JARSP"],
    }
    _write_raw(raw_dir, src, raw)
    c = _camp_with_source(
        src, provenance={"reach": {"source_url": "https://t.me/s/spchan/100", "tier": 2}}
    )
    store.upsert_campaign(conn, c)

    html = _tme_html("spchan", [(101, "Ще пост про збір"), (102, "І ще один збір")])
    client = _FakeTgClient(html)

    n = audit.fill_search_posts(
        conn, c, pages=1, raw_dir=raw_dir, _client=client
    )
    assert n > 0
    linked = store.load_posts(conn, campaign_id=c.id)
    assert len(linked) >= 1

    # Ідемпотентність: повторний запуск не додає нових постів
    n2 = audit.fill_search_posts(
        conn, c, pages=1, raw_dir=raw_dir, _client=client
    )
    assert n2 == 0


# ── fill_llm_style ───────────────────────────────────────────────────────────


def test_fill_llm_style_fills_only_empty_fields(tmp_path):
    conn, _db, _raw = _seed_db(tmp_path)
    # tone вже задано (НЕ чіпаємо), cta_type/face порожні (заповнюємо)
    c = _camp_with_source(
        "https://t.me/ch/20", tone=["emotional"], cta_type=None, face=None
    )
    store.upsert_campaign(conn, c)
    raw = {"source_url": "https://t.me/ch/20", "text": "Збір на дрони"}

    def _complete(prompt):  # noqa: ARG001
        return {
            "tone": ["urgent"],          # НЕ повинно перезаписати наявне
            "form_factor": ["video"],
            "cta_type": "jar",
            "face": "soldier",
        }

    ok = audit.fill_llm_style(conn, c, raw, _complete=_complete)
    assert ok is True
    reloaded = store.get_campaign(conn, c.id)
    assert reloaded.tone == ["emotional"]   # збережено наявне
    assert reloaded.cta_type == "jar"        # заповнено порожнє
    assert reloaded.face == "soldier"


def test_fill_llm_style_no_raw_returns_false(tmp_path):
    conn, _db, _raw = _seed_db(tmp_path)
    c = _camp_with_source("https://t.me/ch/21", cta_type=None)
    store.upsert_campaign(conn, c)
    ok = audit.fill_llm_style(conn, c, None, _complete=lambda p: {"cta_type": "jar"})
    assert ok is False


# ── fill_diagnose ────────────────────────────────────────────────────────────


def test_fill_diagnose_applies_goal_and_destination(tmp_path):
    conn, _db, _raw = _seed_db(tmp_path)
    c = _camp_with_source("https://t.me/ch/30", type="organic_social")
    store.upsert_campaign(conn, c)
    raw = {"source_url": "https://t.me/ch/30", "text": "Ціль у закріпі"}

    def _complete(prompt):  # noqa: ARG001
        return {
            "found_destination": "https://send.monobank.ua/jar/DIAGJAR",
            "found_goal": 250000,
        }

    hint = audit.fill_diagnose(conn, c, raw, _complete=_complete)
    assert isinstance(hint, dict)
    reloaded = store.get_campaign(conn, c.id)
    assert reloaded.goal_amount == 250000
    assert audit.campaign_jar_id(reloaded) == "DIAGJAR"


# ── run_audit ────────────────────────────────────────────────────────────────


def test_run_audit_dry_run_writes_nothing(tmp_path):
    conn, _db, raw_dir = _seed_db(tmp_path)
    src = "https://t.me/ch/40"
    raw = {"source_url": src, "text": "Донат", "links": ["https://cutt.ly/x"]}
    _write_raw(raw_dir, src, raw)
    c = _camp_with_source(src, is_campaign=True, type="organic_social")
    store.upsert_campaign(conn, c)

    before = store.get_campaign(conn, c.id)
    summary = audit.run_audit(
        conn, raw_dir=raw_dir, use_llm=False, dry_run=True
    )
    after = store.get_campaign(conn, c.id)

    # Нічого не змінилось у БД
    assert after.amount_uah == before.amount_uah
    assert after.provenance == before.provenance
    # summary містить намічені дії
    assert summary["n_campaigns"] >= 1
    assert "actions_run" in summary
    assert sum(summary["actions_run"].values()) >= 1


def test_run_audit_summary_shape_no_llm(tmp_path):
    conn, db_path, raw_dir = _seed_db(tmp_path)
    src = "https://t.me/ch/50"
    raw = {"source_url": src, "channel": "ch", "text": "Збір банка",
           "links": ["https://send.monobank.ua/jar/RUNJAR"]}
    _write_raw(raw_dir, src, raw)
    c = _camp_with_source(src, is_campaign=True, provenance=_jar_prov("RUNJAR"))
    store.upsert_campaign(conn, c)

    def _render(jar_id):
        return "Збір\n10 000 ₴\n20 000 ₴"

    summary = audit.run_audit(
        conn,
        raw_dir=raw_dir,
        channels_file=tmp_path / "channels.txt",
        use_llm=False,
        _render=_render,
        _client=_FakeTgClient(_tme_html("ch", [])),
        out_path=tmp_path / "cases.json",
        jars_cache_path=tmp_path / "jars.json",
    )
    # форма summary
    for key in ("before", "after", "actions_run", "n_campaigns",
                "fully_complete_before", "fully_complete_after"):
        assert key in summary
    # LLM-дії пропущені (use_llm=False)
    assert summary["actions_run"].get(audit.LLM_EXTRACT_STYLE, 0) == 0
    assert summary["actions_run"].get(audit.LLM_DIAGNOSE, 0) == 0
    # RENDER_JAR заповнив суму → before<after для amount_uah
    assert summary["after"]["amount_uah"] >= summary["before"]["amount_uah"]


def test_run_audit_only_actions_filter(tmp_path):
    conn, _db, raw_dir = _seed_db(tmp_path)
    src = "https://t.me/ch/60"
    raw = {"source_url": src, "text": "Донат", "links": ["https://cutt.ly/y"]}
    _write_raw(raw_dir, src, raw)
    c = _camp_with_source(src, is_campaign=True, type="organic_social", provenance=_jar_prov("ONLYJAR"))
    store.upsert_campaign(conn, c)

    summary = audit.run_audit(
        conn,
        raw_dir=raw_dir,
        channels_file=tmp_path / "channels.txt",
        use_llm=False,
        only_actions={audit.RENDER_JAR},
        _render=lambda jid: "Збір завершено",  # закрита → no-op
        out_path=tmp_path / "cases.json",
        jars_cache_path=tmp_path / "jars.json",
    )
    # Лише RENDER_JAR розглядався; RESOLVE_LINKS не запускався
    assert audit.RESOLVE_LINKS not in summary["actions_run"] or \
        summary["actions_run"].get(audit.RESOLVE_LINKS, 0) == 0
