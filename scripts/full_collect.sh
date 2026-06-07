#!/usr/bin/env bash
# Повний зборо-центричний збір: dig → relink → classify → enrich → dedup(dest)
# → prune(60) → posts(link) → export. Безкоштовно (claude CLI). Резюмовано.
# Запуск: FUNDREC_CRITIC_API_KEY="" bash scripts/full_collect.sh [MAX]
set +e
cd "$(dirname "$0")/.."
export PYTHONIOENCODING=utf-8
export FUNDREC_CRITIC_API_KEY=""
PY=".venv/Scripts/python.exe"
MAX="${1:-200}"

echo "=== [1/8] dig_recent (найновіші пости по всіх каналах) ==="
$PY scripts/dig_recent.py "$MAX"

echo "=== [2/8] relink (банки з усіх лінків + скорочені, глибоко) ==="
$PY -m fundrec.relink --all

echo "=== [3/8] classify (релевантність) ==="
$PY -m fundrec.relevance --classify

echo "=== [4/8] enrich (суми текст+банки) ==="
$PY -m fundrec.enrich

echo "=== [5/8] dedup (зборо-центрично, за призначенням) ==="
$PY -m fundrec.dedup_pass --raw-dir data/raw

echo "=== [6/8] prune (лишити <=60 днів) ==="
$PY -m fundrec.prune --max-age-days 60

echo "=== [7/8] posts (звʼязок пости<->збори, охоплення) ==="
$PY -m fundrec.posts

echo "=== [8/8] export (фінальний cases.json з охопленням) ==="
$PY -c "from fundrec import store,export,config; export.export_cases(store.connect(), config.CASES_JSON); print('exported')"

echo "=== FULL COLLECT DONE ==="
