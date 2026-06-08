"""Суцільний прохід: освіжити ВСІ застарілі raw-пости через single-post
embed (t.me/<ch>/<id>?embed=1, ловить CTA-anchor банки) → витягти всі банки
зі всіх постів → привʼязати призначення + рендер сум → експорт + інвентар.

Запуск: FUNDREC_CRITIC_API_KEY="" .venv/Scripts/python.exe scripts/bank_sweep.py
"""
import glob
import json
import re
import time

import httpx

from fundrec import config, export, store
from fundrec.audit import RENDER_JAR, RESOLVE_LINKS, _write_raw_post, run_audit
from fundrec.collect.telegram_web import parse_tme_html
from fundrec.dedup import campaign_jar_id
from fundrec.jars import jar_ids_from_raw

RAW = config.RAW_DIR
TME_POST = re.compile(r"https?://t\.me/([^/]+)/(\d+)")


def all_raw_items():
    for fp in glob.glob(str(RAW / "**" / "*.json"), recursive=True):
        try:
            r = json.load(open(fp, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        for it in (r if isinstance(r, list) else [r]):
            if isinstance(it, dict):
                yield it


def jar_inventory():
    jars, posts_with = set(), 0
    for it in all_raw_items():
        jids = jar_ids_from_raw(it)
        if jids:
            posts_with += 1
            jars.update(jids)
    return jars, posts_with


conn = store.connect()
real0 = [c for c in store.load_campaigns(conn) if c.is_campaign]
dest0 = sum(1 for c in real0 if campaign_jar_id(c) is not None)
jars0, pw0 = jar_inventory()
print(f"ДО: реальних={len(real0)} з jar-призначенням={dest0} | "
      f"унікальних банок у raw={len(jars0)} постів-з-банкою={pw0}")

# 1) знайти всі застарілі t.me-пости (без anchors)
stale = set()
for it in all_raw_items():
    if "anchors" in it:
        continue
    url = it.get("source_url") or ""
    if TME_POST.match(url):
        stale.add(url)
stale = sorted(stale)
print(f"\n[1/4] освіжаю {len(stale)} застарілих постів через ?embed=1 …")

client = httpx.Client(timeout=20, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0"})
ok = err = newjar = 0
for i, url in enumerate(stale):
    m = TME_POST.match(url)
    ch = m.group(1)
    try:
        resp = client.get(url + "?embed=1")
        posts = parse_tme_html(ch, resp.text)
    except Exception:  # noqa: BLE001
        err += 1
        continue
    for p in posts:
        p["source_url"] = url  # форсуємо перезапис того ж raw-файлу
        if jar_ids_from_raw(p):
            newjar += 1
        _write_raw_post(RAW, p)
    ok += 1
    if i % 50 == 0 and i:
        print(f"   {i}/{len(stale)} (ok={ok} err={err} нових-з-банкою={newjar})")
    time.sleep(0.12)
client.close()
print(f"   освіжено={ok} помилок={err} тепер-мають-банку={newjar}")

# 2) інвентар банок після освіження
jars1, pw1 = jar_inventory()
print(f"\n[2/4] інвентар банок: {len(jars0)}→{len(jars1)} унікальних, "
      f"постів-з-банкою {pw0}→{pw1}")

# 3) привʼязка призначень + рендер сум по ВСІХ зборах
print("\n[3/4] привʼязка банок до зборів + рендер сум (audit resolve+render) …")
client2 = httpx.Client(timeout=20, follow_redirects=True,
                       headers={"User-Agent": "Mozilla/5.0"})
summary = run_audit(conn, use_llm=False,
                    only_actions=[RESOLVE_LINKS, RENDER_JAR], _client=client2)
client2.close()

# 4) фінальний стан
real1 = [c for c in store.load_campaigns(conn) if c.is_campaign]
dest1 = sum(1 for c in real1 if campaign_jar_id(c) is not None)
export.export_cases(conn, config.CASES_JSON)
print("\n[4/4] ГОТОВО")
print(f"  jar-призначень у зборів: {dest0} → {dest1}")
print(f"  has_destination(before/after): {summary['before'].get('has_destination')} → "
      f"{summary['after'].get('has_destination')}")
print(f"  дії: {summary['actions_run']}")
print(f"  унікальних банок виявлено всього: {len(jars1)}")
