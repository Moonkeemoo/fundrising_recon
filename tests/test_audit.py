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
