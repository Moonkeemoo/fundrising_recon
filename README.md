# fundrising_recon

База кейсів фандрайзингу України часів війни (2022→2026) для маркет-ресьорчу:
що перформить у 2026, а що ні. Автозбір у дусі Recon — кожне число з провенансом
і рівнем довіри. Дизайн: `docs/superpowers/specs/2026-06-07-fundrising-recon-design.md`.

## Стек
Python 3.12, SQLite, httpx, Claude Agent SDK (екстракція). Тести: pytest.

## Розробка
```bash
pip install -e ".[dev]"
python -m pytest -v
```

## P0 пайплайн (наскрізний зріз)
```bash
python -m fundrec.cli data/seeds/p0_seed.json
# seed -> Monobank jar -> LLM extract -> validate -> SQLite -> data/cases.json
```

## Статус
P0 (кістяк) — наскрізний потік на 1 колекторі (Monobank jar). Далі: P1 (колектори
звітів/новин/соц + Discoverer + дедуп), P2 (критик), P3 (4 осі + тренди), P4 (кокпіт).

## Жива екстракція
`_live_complete` у `extract.py` викликає Claude Agent SDK на підписці. Перед першим
живим запуском підтвердити реальний формат JSON-ендпоінта банки Monobank (spec §10):
`JAR_JSON_URL` у `collect/monobank.py`.
