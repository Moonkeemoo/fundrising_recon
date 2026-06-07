# Щоденний рефреш радару фандрайзингу.
# Запуск вручну:  powershell -ExecutionPolicy Bypass -File scripts\daily_refresh.ps1
# Або через Планувальник завдань Windows (див. docs/SCHEDULING.md).
#
# Повний зборо-центричний конвеєр (той самий, що scripts/full_collect.sh):
#   jar_refresh(momentum) → dig_recent → relink → classify → enrich →
#   dedup(dest) → prune(60) → posts(link) → export.
# Екстракція безкоштовна (claude CLI), тому без платного фолбеку:
$ErrorActionPreference = "Continue"
Set-Location -Path (Split-Path -Parent $PSScriptRoot)   # корінь репо
$env:PYTHONIOENCODING = "utf-8"
$env:FUNDREC_CRITIC_API_KEY = ""   # CLI-only, без платного API
$py = ".\.venv\Scripts\python.exe"

Write-Output "=== jar_refresh (momentum) ==="
& $py -m fundrec.jar_refresh
Write-Output "=== dig_recent (свіжі збори) ==="
& $py scripts\dig_recent.py 80
Write-Output "=== relink (банки з усіх лінків) ==="
& $py -m fundrec.relink --all
Write-Output "=== classify (релевантність) ==="
& $py -m fundrec.relevance --classify
Write-Output "=== enrich (суми) ==="
& $py -m fundrec.enrich
Write-Output "=== dedup (зборо-центрично) ==="
& $py -m fundrec.dedup_pass --raw-dir data\raw
Write-Output "=== prune (<=60 днів) ==="
& $py -m fundrec.prune --max-age-days 60
Write-Output "=== posts (звʼязок + охоплення) ==="
& $py -m fundrec.posts
Write-Output "=== export ==="
& $py -c "from fundrec import store,export,config; export.export_cases(store.connect(), config.CASES_JSON)"

Write-Output "=== DAILY REFRESH DONE ==="
