# Щоденний рефреш радару фандрайзингу.
# Запуск вручну:  powershell -ExecutionPolicy Bypass -File scripts\daily_refresh.ps1
# Або через Планувальник завдань Windows (див. docs/SCHEDULING.md).
#
# Послідовність:
#   1) jar_refresh — перерендерити банки (накопичити momentum, force)
#   2) dig_recent  — зібрати найновіші пости по всіх каналах (свіжі збори)
#   3) pipeline    — classify -> enrich -> dedup -> export (фіналізація)
#
# Екстракція безкоштовна (claude CLI), тому без платного фолбеку:
$ErrorActionPreference = "Continue"
Set-Location -Path (Split-Path -Parent $PSScriptRoot)   # корінь репо
$env:PYTHONIOENCODING = "utf-8"
$env:FUNDREC_CRITIC_API_KEY = ""   # CLI-only, без платного API
$py = ".\.venv\Scripts\python.exe"

Write-Output "=== [1/3] jar_refresh (momentum) ==="
& $py -m fundrec.jar_refresh

Write-Output "=== [2/3] dig_recent (свіжі збори) ==="
& $py scripts\dig_recent.py 80

Write-Output "=== [3/3] pipeline (classify->enrich->dedup->export) ==="
& $py -m fundrec.pipeline

Write-Output "=== DAILY REFRESH DONE ==="
