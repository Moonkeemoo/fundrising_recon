# fundrising_recon — реальні дані + шар «Кампанія / Креатив / Стиль» (дизайн)

> Розширення системи від числової бази зборів до **глибокої масової аналітики
> фандрайзингових кампаній України**: реальний збір даних + якісний шар
> (стиль/підходи/креатив) по онлайн і IRL каналах. Мета — дати підрозділу
> **глибоку аналітику** (дані + графіки + галерея реальних креативів + крос-таби
> стиль/канал/формат), щоб запускати ефективні кампанії. Дисципліна Recon
> зберігається: кожне число з провенансом і рівнем довіри; honest null.

- **Дата:** 2026-06-07
- **Репо:** `git@github.com:Moonkeemoo/fundrising_recon.git`
- **Базується на:** P0-P4 (модель Case/Actor/Source, SQLite, колектори, критик,
  analyze, кокпіт) — див. `2026-06-07-fundrising-recon-design.md`.
- **Статус:** дизайн узгоджено, чекає рев'ю спеки → плани (F1-F6).

---

## 1. Мета і не-мета

**Мета.** Зібрати **реальні** дані про фандрайзингові кампанії України (з 2022),
з числами І якісним шаром (стиль, підхід, креатив, канали), по онлайн і IRL,
та дати **глибоку аналітику**: що корелює з результатом (стиль × обсяг,
канал × швидкість, формат × залучення, тон × віральність), з галереєю реальних
креативів і прикладами.

**Не-мета.**
- **Без LLM-плейбука/рекомендацій** — система дає дані й аналітику; висновки
  робить людина. (Описова `playbook_note` на кампанію — це ДАНІ про підхід, не порада.)
- **Без приватних контактів людей** (PII / інваріант #6). Публічні
  організатори/спонсори/партнери — так, приватні контакти — ні.
- Не зброя, не таргетинг людей для шкоди. Вивчаємо ПУБЛІЧНІ кампанії, щоб
  навчитися ефективному фандрайзингу.

**Критерій успіху.** Дашборд показує реальні кампанії з креативами й стилем,
відповідає на «який канал/формат/тон історично корелює з вищим результатом для
цілі X», кожен висновок із видимим `N`; дані тягнуться автоматично з реальних
джерел по наявних ключах.

---

## 2. Рішення зі скоупу (узгоджено)

| Питання | Рішення |
|---|---|
| Обсяг | **Роби все** — S1 (live-цифри) + S2 (кампанія/креатив/стиль) + S3 (глибока аналітика), інкрементально фазами F1-F6 |
| Онлайн-джерела | **Meta Ad Library** (FB/IG/**Threads** реклама), **Monobank + платформи/звіти**, **YouTube**, **Telegram** (публ. канали); Threads-органіка — best-effort пізніше |
| Глибина стилю | **Теги + описова playbook-нотатка** на кампанію |
| IRL | **Публічні події/партнери через новини/анонси** (без приватних контактів) |
| Ключі | **Гайд `docs/SETUP-KEYS.md`**; код+тести на фікстурах одразу, живий прогін — по готових ключах |
| Вихід | **Глибока аналітика** (дашборд + галерея креативів + крос-таби стилю); БЕЗ синтез-плейбука |

---

## 3. Розширення моделі (контракт)

Наявні `Case`/`Actor`/`Source` лишаються. Нові сутності:

### Campaign (нова одиниця аналізу)
```
id, actor_id, title, goal                # та сама ієрархія цілей category[/subcategory]
type                                      # online_ad | organic_social | telethon
                                          #   | event_irl | platform | jar | mixed
channels[]                                # facebook, instagram, threads, youtube,
                                          #   telegram, tiktok, web, irl
date_start, date_end, year
# СТИЛЬ (контрольовані теги)
form_factor[]                             # video, carousel, banner, longread, stream, image, text
cta_type                                  # donate_link, jar, qr, auction, subscription, merch
tone[]                                    # emotional, urgency, humor, data_transparent, heroism, gratitude
face                                      # soldier, blogger, celebrity, brand, official, anonymous
cadence                                   # one_off, series, ongoing
playbook_note                            # коротка ОПИСОВА LLM-нотатка про підхід (не порада)
# МЕТРИКИ (кожна nullable + provenance+confidence+tier; honest null)
amount_uah, amount_usd                    # через звʼязок із Case/jar
reach, engagement, spend, assets_count
# звʼязки + дисципліна
case_id                                   # числовий результат (FK -> cases)
partner_ids[]                             # M:N -> partners
provenance, confidence_overall, verification_status, verdict_reason, extracted_at, extracted_by_model
```

### CreativeAsset (діти кампанії — окрема реклама/пост/відео)
```
id, campaign_id, platform, format         # image | video | carousel | text | stream
copy_text, hook, cta, media_url, published
impressions_range, spend_range            # з Ad Library, де є
views, likes                              # nullable + provenance
provenance
```

### Partner (публічна сутність)
```
id, name, role (sponsor|organizer|celebrity|brand|partner), links[]
# БЕЗ приватних контактів
```

### Звʼязки
`Campaign → Actor` (хто веде); `Campaign → Case` (числовий результат);
`Campaign 1:N CreativeAsset`; `Campaign M:N Partner`.

Сховище: нові таблиці `campaigns`, `creative_assets`, `partners`, `campaign_partners`
(M:N). JSON-поля (масиви/provenance) у TEXT-колонках — патерн наявного store.

---

## 4. Колектори + ключі (spec джерел)

Кожен колектор — інжектабельний клієнт, фікстури в тестах, graceful-skip без ключа
(лог «нема доступу», не падає, не вигадує).

| Модуль | Джерело | Дає | Ключ |
|---|---|---|---|
| `collect/meta_ads.py` | Meta Ad Library API (FB/IG/Threads реклама) | креатив (текст/медіа/формат), дати, spend/impressions-діапазони, сторінка | `META_ADS_TOKEN` |
| `collect/youtube.py` | YouTube Data API v3 | телетони/відеозвернення, views/likes | `YOUTUBE_API_KEY` |
| `collect/telegram.py` | Telegram публ. канали (Telethon) | пости-збори, реакції/перегляди | `TELEGRAM_API_ID` + `TELEGRAM_API_HASH` |
| `collect/monobank.py` ✓ | банки Monobank | суми/ціль | — |
| `collect/reports.py` ✓ `news.py` ✓ | платформи/звіти/новини | суми + IRL-події + партнери | — |

- **Threads:** окремого публ. API нема; реклама — через Meta Ad Library; органіка — best-effort пізніше (позначено чесно).
- **Секрети** — у `.env` (`/.env.example` оновити), читаються в `config.py`. Жодних ключів у git.
- **Гайд** — `docs/SETUP-KEYS.md`: покроково Meta dev app → Ad Library token; Google Cloud → YouTube Data API key; my.telegram.org → api_id/hash; куди класти в `.env`. Українською.

---

## 5. Live-wiring (увімкнення реального збору)

1. **`discover._live_search`** → реальний веб-пошук. Дефолт-провайдер `search/duckduckgo.py`
   (DuckDuckGo HTML, без ключа), інжектабельний, тест на фікстурі. Опційно — Agent SDK web-search.
2. **`extract._live_complete`** → коректне зведення з **Claude Agent SDK** (підписка,
   без ключа): async `query`, парсинг JSON. Запасний шлях — прямий Anthropic API з тим
   самим `parse`-surface, якщо SDK не злетить. Детермінований surface лишається тестованим.
3. **Monobank-ендпоінт** → recon на старті живого прогону: реальна сторінка банки →
   фіксуємо `JAR_JSON_URL`/парсер (зараз здогад).
4. **`config.py`** — нові ключі (Meta/YouTube/Telegram), усі graceful-skip без них.
5. **Єдиний live-CLI** `python -m fundrec.ingest --theme "<тема>" [--sources meta,youtube,telegram,reports,news,monobank] [--max N]`:
   `discover → collect (усі доступні) → extract (campaigns+creatives) → verify (critic+crosscheck)
   → analyze → export`. Резюмований, rate-limit, retry 429/5xx, сирий кеш `data/raw/`,
   чесний лог «зібрано / пропущено через брак ключа».

---

## 6. Екстракція кампаній / креативу / стилю

- **`extract.extract_campaign(raw, source, …)`** → `Campaign` + `CreativeAsset[]` +
  `Partner[]`, структурований вивід строго за схемою. З Ad Library багато вже
  структуроване — LLM переважно мапить + класифікує style-теги зі словників і пише
  описову `playbook_note`. Жорстке правило: число без джерела+цитати → null;
  provenance+confidence за tier.
- **Нові словники** у `schema.py`: `CAMPAIGN_TYPES`, `CHANNELS`, `FORM_FACTORS`,
  `CTA_TYPES`, `TONES`, `FACE_TYPES`, `CADENCE`. `validate.py` розширюється на них.
- **Критик** (`critic.py`) поширюється на кампанії (підтвердження сум/метрик/типізації).
- **Дедуп** (`dedup.py`) — кампанія з кількох джерел → мердж за tier, обʼєднання
  креативів/каналів/партнерів.

---

## 7. Дашборд глибокої аналітики (розширення кокпіта; БЕЗ синтез-плейбука)

- **Галерея креативів** — сітка `CreativeAsset` (мініатюра медіа, копірайт, платформа,
  формат, spend/impressions-діапазон, лінк на джерело), фільтрована.
- **Аналітика стилю** — крос-таби кореляції з результатом: `стиль × обсяг`,
  `канал × обсяг/швидкість`, `формат × залучення`, `тон × віральність`, `обличчя × результат`.
  Кожна клітинка з `N` (без N — не показуємо).
- **Дослідник кампаній** — кампанії з креативами, тег-стилем, метриками, партнерами.
- Наявні тренд/теплокарта/лідерборд отримують нові осі (канал, формат, тон); нові
  фільтри (канал, формат, тон, обличчя, тип кампанії).
- `export` віддає `campaigns` + `creatives` + розширену `analytics` для морди.

---

## 8. Інваріанти (додатково до базових)

| # | Правило | Наслідок порушення |
|---|---|---|
| 1 | Число без `source_url`+цитати → null (і для метрик кампаній/креативів) | Хибна аналітика |
| 2 | `confidence`+`tier` на кожне значуще поле | Не відділити надійне від шуму |
| 5 | Метрики/осі лише де є дані; null≠0 | Фальшива точність |
| 6 | НЕ приватні контакти; НЕ зброя/таргетинг для шкоди | PII / поза призначенням |
| 7 | Колектор без ключа → graceful-skip із логом, не вигадка | «Дані» з нізвідки |
| 8 | Ключі/секрети лише в `.env`, ніколи в git | Витік креденшалів |

---

## 9. Фазовий план (кожна фаза — окремий план writing-plans)

| Фаза | Зміст |
|---|---|
| **F1** | Модель: таблиці campaigns/creative_assets/partners(+M:N) + дата-класи + нові словники + валідатори + store CRUD. Тести. |
| **F2** | Колектори `meta_ads`/`youtube`/`telegram` (інжектабельні, фікстури) + секрети в config + `.env.example` + `docs/SETUP-KEYS.md`. |
| **F3** | Екстракція `extract_campaign` (campaigns+creatives+partners+style+playbook_note) + критик/дедуп на кампанії. |
| **F4** | Live-wiring: `search/duckduckgo`, реальний `extract._live_complete` (Agent SDK + fallback), Monobank-recon, `ingest`-CLI. |
| **F5** | Дашборд: галерея креативів + аналітика стилю + дослідник кампаній + нові осі/фільтри + export. |
| **F6** | Живий прогін по наявних ключах → реальний `cases.json`/`campaigns.json`; чесний звіт покриття. |

---

## 10. Відкриті питання (вирішити під час фаз)

- Точна форма відповіді Meta Ad Library (поля spend/impressions для UA-реклами;
  чи доступні нерекламні/комерційні оголошення без «political» дозволу) — recon у F2.
- Реальний рантайм Claude Agent SDK (форма async API) — валідація у F4; готовий fallback на прямий API.
- Telethon потребує разової інтерактивної авторизації сесії — описати в SETUP-KEYS.
- Rate-limits кожного API → консервативні дефолти + резюмованість.
- Threads-органіка — поки best-effort; основне покриття Threads — через Ad Library.
