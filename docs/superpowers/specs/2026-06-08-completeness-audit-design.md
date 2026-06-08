# Аудит повноти збору + автодобір дірок — дизайн

**Дата:** 2026-06-08 · **Статус:** затверджено (2 рішення через AskUserQuestion)

## Мета
Для кожного збору (донат-призначення = одиниця) перевіряти наявність усієї аналітично потрібної
інформації; де дірка — **тригерити точковий добір саме цього** (не сліпий re-collect усього).
Підхід — **гібрид**: спершу детермінований аудит, LLM-діагност лише для складних залишкових дірок.
Окрема резюмована команда `python -m fundrec.audit`.

## Виміри повноти (усі обрані юзером) — поточний стан (64 реальні збори)
| Вимір | Поля | Зараз |
|---|---|---|
| Призначення+гроші | has_destination, amount_uah, goal_amount | 31 / 34 / 18 |
| Охоплення+пости | post_count≥1, reach_total, reach_resonance(база каналу) | 29 / 29 / 43 |
| Стиль | tone, form_factor, face, cta_type | 64/64/64/56 |
| Теми | themes (конкретні предмети) | 45 |

Найдобірніші дірки: **33 без призначення, 46 без цілі, 35 без постів/охоплення, 21 без бази каналу, 19 без теми**.

## Класифікація дірки (ключове)
Кожне відсутнє поле → один зі статусів:
- `present` — є.
- `missing_fillable` — нема, але є сигнал, що добірне (нижче).
- `missing_unavailable` — нема й принципово недоступне (НЕ зациклюватись).

Сигнали заповнюваності → дія:
- **призначення** нема + у raw є нерозвʼязані/скорочені лінки → `RESOLVE_LINKS` (extract_destinations + resolve_jar_id).
- **сума/ціль** нема + є jar-id → `RENDER_JAR` (jar_render.render_jar_cached force). Закрита банка/нема jar → `unavailable`.
- **пости/охоплення/база каналу** нема/мало → `SEARCH_POSTS` (telegram_web по jar-id/ключу/каналу → posts.build_posts; піднімає reach + базу каналу).
- **стиль** (cta/tone/...) порожнє → `LLM_EXTRACT_STYLE` (extract.parse_campaign_extraction на raw).
- **теми** порожні → `RETAG_THEME` (derive_themes; для впертих — `LLM_DIAGNOSE` дотег предмета).
- **складний залишок** (нема призначення/суми після детермінованих дій) → `LLM_DIAGNOSE`: LLM читає raw і або витягає поле напряму, або дає точкову пошук-підказку («ціль у закріпленому пості», «друге посилання на банку»).

Принципові стелі (→ `unavailable`, без ретраїв): закриті банки/приватні конверти без публічного тоталу; Meta/Instagram заблоковані.

## Архітектура (модуль `src/fundrec/audit.py`)
1. `CompletenessReport` (dataclass): per-campaign {field: status} + список `gap_actions`.
2. `audit_campaign(campaign, raw, *, baselines) -> CompletenessReport` — чистий детермінований аналіз (TDD-ядро).
3. `gap_actions(report) -> list[Action]` — мапа missing_fillable → enum дій.
4. `run_audit(conn, *, fields, use_llm=True, max_items=None, report_only=False)` — виконавець:
   реюз наявного (jar_render, destinations/relink, telegram_web.search, posts.build_posts, extract);
   ідемпотентно/резюмовано (наявні `_already`-гарди); наприкінці — re-export.
5. CLI `python -m fundrec.audit`:
   - `--report-only` → друкує матрицю повноти + список дірок (без фетчу).
   - default → аудит+добір+re-export. Прапори `--fields`, `--no-llm`, `--max N`.

## Звіт
Per-збір повнота + агрегат before/after (напр. «призначення 31→45/64; 12 unavailable: закриті банки»).
(Фаза 2, опц.: бейдж повноти на картці збору в морді.)
