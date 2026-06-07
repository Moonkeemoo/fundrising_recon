# Автооновлення радару (щоденний рефреш)

Щоб радар лишався «живим» сам — налаштуй щоденний запуск `scripts\daily_refresh.ps1`.
Він робить: `jar_refresh` (динаміка банок) → `dig_recent` (свіжі збори по всіх каналах)
→ `pipeline` (classify → enrich → dedup → export). Екстракція безкоштовна (claude CLI).

## Варіант 1 — Планувальник завдань Windows (GUI)
1. Win → «Планувальник завдань» (Task Scheduler) → «Створити просте завдання».
2. Назва: `fundrec-daily-refresh`. Тригер: щодня (напр. 08:00).
3. Дія: «Запустити програму»:
   - Програма: `powershell.exe`
   - Аргументи: `-ExecutionPolicy Bypass -File "C:\Users\tomoo\Documents\GitHub\fundrising_recon\scripts\daily_refresh.ps1"`
4. Готово.

## Варіант 2 — командою (PowerShell від адміністратора)
```powershell
$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument '-ExecutionPolicy Bypass -File "C:\Users\tomoo\Documents\GitHub\fundrising_recon\scripts\daily_refresh.ps1"'
$trigger = New-ScheduledTaskTrigger -Daily -At 8am
Register-ScheduledTask -TaskName "fundrec-daily-refresh" -Action $action -Trigger $trigger -Description "Щоденний рефреш радару фандрайзингу"
```

## Перевірити вручну
```
powershell -ExecutionPolicy Bypass -File scripts\daily_refresh.ps1
```

## Примітки
- Momentum банок зʼявляється після ≥2 рефрешів (різниця сум або ≥6 год між запусками).
- Дашборд читає `data/cases.json` свіжо щоразу — після рефрешу досить оновити сторінку.
- Для постійного доступу з телефону тримай дашборд піднятим:
  `python -m fundrec.dashboard --host 0.0.0.0 --port 8770` (або теж заплануй автозапуск).
