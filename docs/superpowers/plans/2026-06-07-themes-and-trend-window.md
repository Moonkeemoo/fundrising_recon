# Themes + Trend Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add keyword-derived campaign themes (multi-label) to the heatmap axis and a 30д/90д/весь час time-window toggle to the trend chart.

**Architecture:** `derive_themes(text)` is a pure function in `analyze.py`; `export_cases` enriches each campaign dict with `themes` at export-time (no schema change); the HTML dashboard adds a `trendWindow` state variable controlling bucketing (day/week/quarter) and a `heatAxis` state variable controlling which axes the heatmap renders (theme×channel, goal×method, tone×channel, format×channel).

**Tech Stack:** Python 3.11, pytest, ruff; vanilla JS (ES2020), ECharts 5; SQLite via existing `store.py`.

---

## File Map

| File | Change |
|---|---|
| `src/fundrec/analyze.py` | Add `derive_themes()` + keyword map |
| `src/fundrec/export.py` | Enrich campaign dicts with `themes` |
| `web/index.html` | Trend window toggle + heatmap axis toggle |
| `tests/test_themes.py` | NEW — unit tests for derive_themes |
| `tests/test_export_themes.py` | NEW — export enrichment test |

---

## Task 1 — `derive_themes()` pure function (TDD)

**Files:**
- Create: `tests/test_themes.py`
- Modify: `src/fundrec/analyze.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_themes.py`:

```python
"""Tests for derive_themes — keyword-based multi-label theme tagger."""
from __future__ import annotations

import pytest

from fundrec.analyze import derive_themes


def test_fpv_and_fiber():
    result = derive_themes("Збір на FPV-дрони на оптоволокні")
    assert set(result) == {"fpv", "fiber"}


def test_interceptors_shahed():
    result = derive_themes("перехоплювачі шахедів")
    assert set(result) == {"interceptors"}


def test_vehicles_and_medical():
    result = derive_themes("евакуаційне авто + аптечки")
    assert set(result) == {"vehicles", "medical"}


def test_no_match_returns_empty():
    result = derive_themes("якийсь загальний текст без конкретики")
    assert result == []


def test_fpv_mavic():
    result = derive_themes("купуємо mavic для розвідки")
    # mavic -> fpv; розвідуваль is not here but "розвідки" matches recon prefix
    assert "fpv" in result


def test_reb_ew():
    result = derive_themes("реб-система і антидрон")
    assert set(result).issuperset({"reb_ew"})


def test_comms_starlink():
    result = derive_themes("Starlink для зв'язку на передовій")
    assert "comms" in result


def test_energy_generator():
    result = derive_themes("генератор та павербанк")
    assert "energy" in result


def test_ammo():
    result = derive_themes("набої та гранати для бригади")
    assert "ammo" in result


def test_optics():
    result = derive_themes("тепловізор та приціл для снайпера")
    assert "optics_electro" in result


def test_humanitarian():
    result = derive_themes("допомога переселенцям та цивільним")
    assert "humanitarian" in result


def test_recon():
    result = derive_themes("розвідувальний крило для ЗСУ")
    assert "recon" in result


def test_vehicles_machine_word_boundary():
    """'машин' pattern matches 'машина' but should not match 'машинально'."""
    result_match = derive_themes("нова машина для евакуації")
    result_no_match = derive_themes("машинально виконали завдання")
    assert "vehicles" in result_match
    assert "vehicles" not in result_no_match


def test_empty_string_returns_empty():
    assert derive_themes("") == []


def test_none_safe():
    # If called with empty string (real usage always passes str)
    assert derive_themes("   ") == []


def test_unique_themes_no_duplicates():
    """fpv appears twice in text — result list has no duplicates."""
    result = derive_themes("FPV дрон, fpv коптер, fpv квадрокоптер")
    assert result.count("fpv") == 1
```

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\Users\tomoo\Documents\GitHub\fundrising_recon
.venv\Scripts\python.exe -m pytest tests/test_themes.py -v 2>&1 | head -30
```

Expected: `ImportError` or `AttributeError` — `derive_themes` does not exist yet.

- [ ] **Step 3: Implement `derive_themes` in `analyze.py`**

Add after the `text_signals_goal_reached` block (around line 384), before the `# ── CAMPAIGN ANALYTICS` section:

```python
# ── THEME TAGGER ─────────────────────────────────────────────────────────────

# Keyword → theme map.
# Rules: lowercase substrings matched in lowercase(text).
# «machines» guard: "машин" patterns need extra word-boundary check (see _MACHINES_GUARD).
_THEME_KEYWORDS: dict[str, list[str]] = {
    "fpv": ["fpv", "фпв", "дрон", "коптер", "квадрокоптер", "мавик", "mavic"],
    "interceptors": ["перехоплюв", "шахед", "антишахед", "ппо", "дрон-перехоплювач"],
    "reb_ew": ["реб", "антидрон", "глушилк", "радіоелектрон", "ew"],
    "vehicles": ["авто", "пікап", "буханк", "транспорт", "баггі", "машин"],
    "recon": ["розвідуваль", "розвідник", "крило", "autel", "автел"],
    "fiber": ["оптоволокн", "оптичн", "на оптиці"],
    "medical": ["медиц", "тактмед", "аптечк", "турнікет", "евакуац", "ноші"],
    "comms": ["starlink", "старлінк", "зв'язк", "рація", "ретранслятор", "антена"],
    "ammo": ["боєприпас", "набої", "рушниц", "гранат"],
    "optics_electro": ["тепловізор", "приціл", "акумулятор", "планшет", "монокуляр"],
    "energy": ["генератор", "павербанк", "енергет"],
    "humanitarian": ["гуманітар", "цивільн", "переселен", "прихист"],
}

# "машин" must NOT match adverb "машинально" — require a word-end char after prefix.
import re as _re
_MACHINES_GUARD = _re.compile(r"машин(?!ально|ний|ному|ній|ною|них|ними)", _re.UNICODE)


def derive_themes(text: str) -> list[str]:
    """Keyword-based multi-label theme tagger.

    Повертає список унікальних тем (рядки), впорядкованих за першою появою.
    Порожній список якщо жоден ключ не співпав.

    Args:
        text: будь-який рядок (title, playbook_note, raw text).

    Returns:
        list of theme strings, e.g. ['fpv', 'fiber']
    """
    if not text or not text.strip():
        return []

    t = text.lower()
    found: list[str] = []

    for theme, keywords in _THEME_KEYWORDS.items():
        matched = False
        for kw in keywords:
            if kw == "машин":
                # special guard: avoid matching машинально
                if _MACHINES_GUARD.search(t):
                    matched = True
                    break
            elif kw in t:
                matched = True
                break
        if matched:
            found.append(theme)

    return found
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd C:\Users\tomoo\Documents\GitHub\fundrising_recon
.venv\Scripts\python.exe -m pytest tests/test_themes.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run ruff on modified file**

```
cd C:\Users\tomoo\Documents\GitHub\fundrising_recon
.venv\Scripts\python.exe -m ruff check src/fundrec/analyze.py --fix
```

Expected: no errors (or auto-fixed). Note: the `import re` inside a module body is fine but ruff may want it at top; move it if ruff flags it.

**If ruff flags the mid-module `import re as _re`:** move it to the top of the file alongside the other imports, then rename all references from `_re` to `re` and add alias at top: `import re as _re_theme` or just `import re` (it's already in stdlib; add `import re` next to existing imports at the file top).

- [ ] **Step 6: Run full suite to confirm no regressions**

```
cd C:\Users\tomoo\Documents\GitHub\fundrising_recon
.venv\Scripts\python.exe -m pytest --ignore=tests/test_check_keys_cli_runs.py -q 2>&1 | tail -20
```

Expected: all pass except possibly the flaky `test_check_keys_cli_runs` which is explicitly ignored.

- [ ] **Step 7: Commit**

```bash
cd C:\Users\tomoo\Documents\GitHub\fundrising_recon
git add src/fundrec/analyze.py tests/test_themes.py
git commit -c commit.gpgsign=false -m "$(cat <<'EOF'
feat: додати derive_themes — keyword-based тематичний тегер

Мульти-лейбл функція з 12 темами (fpv/interceptors/reb_ew/vehicles/
recon/fiber/medical/comms/ammo/optics_electro/energy/humanitarian).
Регекс-захист від хибних спрацювань (машинально). TDD: 16 тестів.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2 — Enrich export with `themes`

**Files:**
- Create: `tests/test_export_themes.py`
- Modify: `src/fundrec/export.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_export_themes.py`:

```python
"""Test that export_cases enriches campaign dicts with `themes`."""
from __future__ import annotations

import json

import pytest

from fundrec import export, store
from fundrec.schema import Actor, Campaign, Case, Source


def _setup(tmp_path):
    conn = store.connect(tmp_path / "t.sqlite")
    store.init_db(conn)
    store.upsert_actor(conn, Actor(id="a1", name="ЗСУ", type="foundation"))
    store.upsert_source(conn, Source(
        url="https://example.com", type="structured", tier=1,
        access="public", license="unknown", actor_id="a1",
    ))
    store.upsert_case(conn, Case(
        id="c1", title="Test", actor_id="a1",
        url="https://example.com", goal="military",
    ))
    return conn


def test_export_themes_fpv(tmp_path):
    """Campaign with FPV title → exported dict has 'fpv' in themes."""
    conn = _setup(tmp_path)
    store.upsert_campaign(conn, Campaign(
        id="k1", actor_id="a1",
        title="Збір на FPV для ЗСУ",
        goal="military/fpv", type="online_ad",
    ))
    out = tmp_path / "cases.json"
    export.export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    camp = data["campaigns"][0]
    assert "themes" in camp
    assert "fpv" in camp["themes"]


def test_export_themes_uses_playbook_note(tmp_path):
    """Theme derived from playbook_note when title is generic."""
    conn = _setup(tmp_path)
    store.upsert_campaign(conn, Campaign(
        id="k2", actor_id="a1",
        title="Допоможи ЗСУ",
        goal="military", type="organic_social",
        playbook_note="Збираємо на старлінк і рацію для зв'язку",
    ))
    out = tmp_path / "cases.json"
    export.export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    camp = data["campaigns"][0]
    assert "comms" in camp["themes"]


def test_export_themes_empty_when_no_match(tmp_path):
    """Generic title with no keywords → themes is empty list."""
    conn = _setup(tmp_path)
    store.upsert_campaign(conn, Campaign(
        id="k3", actor_id="a1",
        title="Підтримай бійців",
        goal="military", type="organic_social",
    ))
    out = tmp_path / "cases.json"
    export.export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    camp = data["campaigns"][0]
    assert camp["themes"] == []


def test_export_themes_present_for_all_campaigns(tmp_path):
    """All exported campaign dicts have a `themes` key."""
    conn = _setup(tmp_path)
    for i, title in enumerate(["FPV збір", "медична допомога", "генератори"]):
        store.upsert_campaign(conn, Campaign(
            id=f"k{i}", actor_id="a1", title=title,
            goal="military", type="organic_social",
        ))
    out = tmp_path / "cases.json"
    export.export_cases(conn, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    for camp in data["campaigns"]:
        assert "themes" in camp, f"Missing 'themes' key in campaign {camp['id']}"
```

- [ ] **Step 2: Run test to verify it fails**

```
cd C:\Users\tomoo\Documents\GitHub\fundrising_recon
.venv\Scripts\python.exe -m pytest tests/test_export_themes.py -v
```

Expected: `AssertionError` — `themes` key missing from exported dicts.

- [ ] **Step 3: Implement themes enrichment in `export.py`**

Modify `src/fundrec/export.py`. Add `derive_themes` to the import and enrich each campaign dict:

```python
"""Дамп БД -> data/cases.json для дашборда (P4 + F5).

Payload: {count, cases:[...], analytics:{...}, campaigns:[...], creatives:[...], partners:[...]}
analytics вбудовано (включно з campaign_analytics), щоб кокпіт рендерив без
повторного обчислення. Зворотна сумісність: ключі `count`/`cases`/`analytics`
завжди присутні.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import config, schema, store
from .analyze import derive_themes, engagement_rate, rel_resonance_map
from .pipeline_analyze import build_analytics


def export_cases(conn: sqlite3.Connection, out_path: Path | str = config.CASES_JSON) -> int:
    cases = store.load_cases(conn)
    analytics = build_analytics(conn)
    campaigns = store.load_campaigns(conn)
    creatives = store.load_creatives(conn)
    partners = store.load_partners(conn)

    # Збагачуємо кампанії обчисленими метриками (не змінюємо схему — тільки export-dict)
    rrmap = rel_resonance_map(campaigns)
    campaign_dicts = []
    for c in campaigns:
        d = schema.campaign_to_dict(c)
        d["engagement_rate"] = engagement_rate(c)
        d["rel_resonance"] = rrmap.get(c.id)
        # Теми — keyword-derived з title + playbook_note (export-time, не в схемі)
        text = (c.title or "") + " " + (c.playbook_note or "")
        d["themes"] = derive_themes(text)
        campaign_dicts.append(d)

    payload = {
        "count": len(cases),
        "cases": [schema.case_to_dict(c) for c in cases],
        "analytics": analytics,
        "campaigns": campaign_dicts,
        "creatives": [schema.creative_to_dict(a) for a in creatives],
        "partners": [schema.partner_to_dict(p) for p in partners],
    }
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(cases)
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd C:\Users\tomoo\Documents\GitHub\fundrising_recon
.venv\Scripts\python.exe -m pytest tests/test_export_themes.py tests/test_export.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run ruff on export.py**

```
cd C:\Users\tomoo\Documents\GitHub\fundrising_recon
.venv\Scripts\python.exe -m ruff check src/fundrec/export.py --fix
```

- [ ] **Step 6: Run full suite**

```
cd C:\Users\tomoo\Documents\GitHub\fundrising_recon
.venv\Scripts\python.exe -m pytest --ignore=tests/test_check_keys_cli_runs.py -q 2>&1 | tail -10
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
cd C:\Users\tomoo\Documents\GitHub\fundrising_recon
git add src/fundrec/export.py tests/test_export_themes.py
git commit -c commit.gpgsign=false -m "$(cat <<'EOF'
feat: збагатити export кампаній полем themes (keyword-derived)

derive_themes(title + playbook_note) → themes[] у кожному campaign dict.
Без змін схеми — лише export-time поле. 4 нові тести.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3 — Trend window toggle 30д/90д/весь час (HTML)

**Files:**
- Modify: `web/index.html`

**Context of changes needed:**

The trend panel HTML is at lines ~258–275. The JS state is at line 494. `renderTrend` is at ~663, `trendData` at ~589. We need to:
1. Add HTML seg control for `trend-window` with buttons `data-w="30"`, `data-w="90"`, `data-w="0"` (весь час).
2. Add JS state `let trendWindow = 0;` (весь час is default, preserving current behavior).
3. Add `campDateMs(c)` helper returning milliseconds (reuse `campDate()`; `campDate()` already works for cases too via `caseYear`/`date_start` fallback — but for `Case` objects there is no `campDate`; re-check: `campDate` uses `c.date_start` + `c.year`, same fields `Case` has — OK).
4. Add bucketing helpers: `bucketByDay(date)` → `"YYYY-MM-DD"`, `bucketByWeek(date)` → `"YYYY-Www"` (ISO week approximation), keep `caseQuarter` for весь час.
5. Modify `trendData` to accept `window` parameter and compute appropriate periods + bucketing.
6. Wire `renderTrend` to use the new bucketing.
7. Bind the new seg control.

- [ ] **Step 1: Add the HTML seg control for trend window**

In the trend panel `<div class="head">` (around line 259), add the window seg BEFORE the existing metric seg, so the head reads: `h3 · trend-n · spacer · [window seg] · [metric seg] · [split seg]`.

Find:
```html
    <div class="head">
     <h3>тренд 2022 → 2026</h3><span class="n" id="trend-n"></span>
     <span class="spacer"></span>
     <div class="seg" id="trend-metric">
```

Replace with:
```html
    <div class="head">
     <h3 id="trend-title">тренд 2022 → 2026</h3><span class="n" id="trend-n"></span>
     <span class="spacer"></span>
     <div class="seg" id="trend-window">
      <button data-w="30">30 днів</button>
      <button data-w="90">90 днів</button>
      <button data-w="0" class="on">весь час</button>
     </div>
     <div class="seg" id="trend-metric">
```

- [ ] **Step 2: Add JS state variable and helper functions**

In the JS state block (around line 494), add `trendWindow` after `heatMetric`:

Find:
```javascript
let trendMetric="volume_usd", trendSplit="", heatMetric="count", lbAxis="amount_uah", lbDir=-1;
```

Replace with:
```javascript
let trendMetric="volume_usd", trendSplit="", trendWindow=0, heatMetric="count", lbAxis="amount_uah", lbDir=-1;
```

- [ ] **Step 3: Add bucketing helpers after the `caseQuarter` function**

Find the block (around line 528):
```javascript
function caseQuarter(c){
 if(c.date_start){const d=String(c.date_start);const m=d.match(/^(\d{4})-(\d{2})/);
  if(m){const q=Math.floor((parseInt(m[2],10)-1)/3)+1;return m[1]+"-Q"+q;}
  if(/^\d{4}$/.test(d))return d+"-Q1";}
 if(c.year)return c.year+"-Q1";
 return null;}
```

After that function (keep it), add:

```javascript
function caseDateMs(c){
 // Returns ms timestamp or null — works for both Case and Campaign objects.
 if(c.date_start){const s=String(c.date_start);
  const m=s.match(/^(\d{4}-\d{2}-\d{2})/);if(m)return new Date(m[1]).getTime();
  const m2=s.match(/^(\d{4}-\d{2})/);if(m2)return new Date(m2[1]+"-01").getTime();
  const m3=s.match(/^(\d{4})/);if(m3)return new Date(m3[1]+"-01-01").getTime();}
 if(c.year)return new Date(c.year+"-01-01").getTime();
 return null;}
function bucketDay(ms){const d=new Date(ms);return d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0");}
function bucketWeek(ms){
 // ISO week approx: floor to Monday.
 const d=new Date(ms);const day=d.getDay()||7;d.setDate(d.getDate()-day+1);
 return d.getFullYear()+"-W"+String(Math.ceil((((d-new Date(d.getFullYear(),0,1))/86400000)+1)/7)).padStart(2,"0");}
```

- [ ] **Step 4: Modify `trendData` to accept and use `window` param**

Find the full `trendData` function (lines ~589–599):

```javascript
function trendData(cases,metric,split){
 // buckets[key][period] -> list
 const buckets={};
 cases.forEach(c=>{const p=caseQuarter(c);if(!p||!ALL_QUARTERS.includes(p))return;
  keysFor(c,split).forEach(k=>{(buckets[k]=buckets[k]||{});(buckets[k][p]=buckets[k][p]||[]).push(c);});});
 const keys=Object.keys(buckets).sort();
 const series=keys.map(k=>{
  const vals=ALL_QUARTERS.map(p=>metricOf(buckets[k][p]||[],metric));
  const ns=ALL_QUARTERS.map(p=>(buckets[k][p]||[]).length);
  return {key:k,vals,ns};});
 return {keys,series};}
```

Replace with:

```javascript
function trendData(cases,metric,split,windowDays){
 // windowDays: 0=весь час (quarterly), 30=daily buckets, 90=weekly buckets
 // Returns {keys, series: [{key, vals, ns}], periods}
 let bucketFn, periods, filterFn;
 if(windowDays===0){
  // весь час — quarter buckets
  bucketFn=c=>caseQuarter(c);
  periods=ALL_QUARTERS;
  filterFn=()=>true;
 } else {
  const nowMs=Date.now();
  const cutMs=nowMs-windowDays*86400000;
  filterFn=c=>{const ms=caseDateMs(c);return ms!=null&&ms>=cutMs&&ms<=nowMs;};
  if(windowDays<=30){
   bucketFn=c=>{const ms=caseDateMs(c);return ms!=null?bucketDay(ms):null;};
  } else {
   bucketFn=c=>{const ms=caseDateMs(c);return ms!=null?bucketWeek(ms):null;};
  }
  // build periods from filtered cases
  const filteredForPeriods=cases.filter(filterFn);
  const pSet=new Set();
  filteredForPeriods.forEach(c=>{const p=bucketFn(c);if(p)pSet.add(p);});
  periods=[...pSet].sort();
 }
 const filteredCases=cases.filter(filterFn);
 const buckets={};
 filteredCases.forEach(c=>{const p=bucketFn(c);if(!p)return;
  keysFor(c,split).forEach(k=>{(buckets[k]=buckets[k]||{});(buckets[k][p]=buckets[k][p]||[]).push(c);});});
 const keys=Object.keys(buckets).sort();
 const series=keys.map(k=>{
  const vals=periods.map(p=>metricOf(buckets[k][p]||[],metric));
  const ns=periods.map(p=>(buckets[k][p]||[]).length);
  return {key:k,vals,ns};});
 return {keys,series,periods};}
```

- [ ] **Step 5: Update `renderTrend` to use `trendWindow` and dynamic periods**

Find the full `renderTrend` function (lines ~663–690):

```javascript
function renderTrend(cases){
 const {series}=trendData(cases,trendMetric,trendSplit);
 const totalN=cases.filter(c=>caseQuarter(c)&&ALL_QUARTERS.includes(caseQuarter(c))).length;
 document.getElementById("trend-n").textContent="N="+totalN;
 const metricName={volume_usd:"обсяг ₴",count:"к-сть",median_speed:"мед. швидкість ₴/д"}[trendMetric];
 const ech=series.map((s,i)=>({
  name:trendSplit?s.key:metricName,type:"line",smooth:true,symbol:"circle",symbolSize:5,
  connectNulls:false,
  lineStyle:{width:2},itemStyle:{color:PALETTE[i%PALETTE.length]},
  data:s.vals,_ns:s.ns}));
 if(!chTrend)return;
 chTrend.setOption({
  backgroundColor:"transparent",
  tooltip:{trigger:"axis",backgroundColor:"#11151c",borderColor:"#222a35",textStyle:{color:"#d7dce2",fontFamily:"monospace"},
   formatter:p=>{let out=esc(p[0].axisValue);p.forEach(s=>{
    const n=(ech[s.seriesIndex]._ns||[])[s.dataIndex];
    const v=s.value==null?"—":(trendMetric==="volume_usd"?fmtUAH(s.value):trendMetric==="median_speed"?fmtSpeed(s.value):s.value);
    out+=`<br>${s.marker}${esc(s.seriesName)}: <b>${v}</b> <span style="color:#525c6b">N=${n??0}</span>`;});
    return out;}},
  legend:trendSplit?{show:true,top:0,textStyle:{color:"#8893a0",fontFamily:"monospace",fontSize:10},type:"scroll"}:{show:false},
  grid:{left:60,right:18,top:trendSplit?28:12,bottom:48},
  xAxis:{type:"category",data:ALL_QUARTERS,axisLine:{lineStyle:{color:"#222a35"}},
   axisLabel:{color:"#8893a0",fontFamily:"monospace",rotate:45,fontSize:10}},
  yAxis:{type:"value",axisLine:{lineStyle:{color:"#222a35"}},splitLine:{lineStyle:{color:"#161b24"}},
   axisLabel:{color:"#8893a0",fontFamily:"monospace",fontSize:10,
    formatter:v=>trendMetric==="volume_usd"?fmtUAH(v):trendMetric==="median_speed"?(v>=1e6?(v/1e6).toFixed(0)+"M":v>=1e3?(v/1e3).toFixed(0)+"K":v):v}},
  series:ech},true);
}
```

Replace with:

```javascript
function renderTrend(cases){
 const {series,periods}=trendData(cases,trendMetric,trendSplit,trendWindow);
 const totalN=cases.filter(c=>{if(trendWindow===0){const p=caseQuarter(c);return p&&ALL_QUARTERS.includes(p);}
  const ms=caseDateMs(c);if(ms==null)return false;
  return ms>=Date.now()-trendWindow*86400000&&ms<=Date.now();}).length;
 document.getElementById("trend-n").textContent="N="+totalN;
 const titleEl=document.getElementById("trend-title");
 if(titleEl){titleEl.textContent=trendWindow===0?"тренд 2022 → 2026":trendWindow===30?"тренд — 30 днів":"тренд — 90 днів";}
 const metricName={volume_usd:"обсяг ₴",count:"к-сть",median_speed:"мед. швидкість ₴/д"}[trendMetric];
 const ech=series.map((s,i)=>({
  name:trendSplit?s.key:metricName,type:"line",smooth:true,symbol:"circle",symbolSize:5,
  connectNulls:false,
  lineStyle:{width:2},itemStyle:{color:PALETTE[i%PALETTE.length]},
  data:s.vals,_ns:s.ns}));
 if(!chTrend)return;
 chTrend.setOption({
  backgroundColor:"transparent",
  tooltip:{trigger:"axis",backgroundColor:"#11151c",borderColor:"#222a35",textStyle:{color:"#d7dce2",fontFamily:"monospace"},
   formatter:p=>{let out=esc(p[0].axisValue);p.forEach(s=>{
    const n=(ech[s.seriesIndex]._ns||[])[s.dataIndex];
    const v=s.value==null?"—":(trendMetric==="volume_usd"?fmtUAH(s.value):trendMetric==="median_speed"?fmtSpeed(s.value):s.value);
    out+=`<br>${s.marker}${esc(s.seriesName)}: <b>${v}</b> <span style="color:#525c6b">N=${n??0}</span>`;});
    return out;}},
  legend:trendSplit?{show:true,top:0,textStyle:{color:"#8893a0",fontFamily:"monospace",fontSize:10},type:"scroll"}:{show:false},
  grid:{left:60,right:18,top:trendSplit?28:12,bottom:48},
  xAxis:{type:"category",data:periods,axisLine:{lineStyle:{color:"#222a35"}},
   axisLabel:{color:"#8893a0",fontFamily:"monospace",rotate:45,fontSize:10}},
  yAxis:{type:"value",axisLine:{lineStyle:{color:"#222a35"}},splitLine:{lineStyle:{color:"#161b24"}},
   axisLabel:{color:"#8893a0",fontFamily:"monospace",fontSize:10,
    formatter:v=>trendMetric==="volume_usd"?fmtUAH(v):trendMetric==="median_speed"?(v>=1e6?(v/1e6).toFixed(0)+"M":v>=1e3?(v/1e3).toFixed(0)+"K":v):v}},
  series:ech},true);
}
```

- [ ] **Step 6: Bind the trend-window seg control in `bindSegs`**

Find in `bindSegs` (around line 1484):

```javascript
 document.querySelectorAll("#trend-metric button").forEach(b=>b.onclick=()=>{
  trendMetric=b.dataset.m;document.querySelectorAll("#trend-metric button").forEach(x=>x.classList.toggle("on",x===b));update();});
```

Add BEFORE that line:

```javascript
 document.querySelectorAll("#trend-window button").forEach(b=>b.onclick=()=>{
  trendWindow=parseInt(b.dataset.w,10);document.querySelectorAll("#trend-window button").forEach(x=>x.classList.toggle("on",x===b));update();});
```

- [ ] **Step 7: Verify `test_index_clean` still passes**

```
cd C:\Users\tomoo\Documents\GitHub\fundrising_recon
.venv\Scripts\python.exe -m pytest tests/test_index_clean.py -v
```

Expected: PASS (no NUL bytes).

- [ ] **Step 8: node --check on inline script**

```
node --check web/index.html 2>&1 || echo "node check done"
```

Note: `node --check` parses a JS file, not HTML. Extract the script and check:

```
cd C:\Users\tomoo\Documents\GitHub\fundrising_recon
node -e "require('fs').readFileSync('web/index.html','utf8').replace(/^[\s\S]*<script>/,'').replace(/<\/script>[\s\S]*$/,'')" > /tmp/check_script.js 2>&1 && node --check /tmp/check_script.js 2>&1 || echo "node check complete"
```

On Windows PowerShell:

```powershell
$html = Get-Content web\index.html -Raw
$start = $html.IndexOf('<script>') + '<script>'.Length
$end = $html.LastIndexOf('</script>')
$script = $html.Substring($start, $end - $start)
$script | Out-File -Encoding utf8 $env:TEMP\fundrec_check.js
node --check $env:TEMP\fundrec_check.js
```

Expected: no syntax errors.

- [ ] **Step 9: Commit**

```bash
cd C:\Users\tomoo\Documents\GitHub\fundrising_recon
git add web/index.html
git commit -c commit.gpgsign=false -m "$(cat <<'EOF'
feat(ui): тренд-вікно 30д/90д/весь час із відповідним бакетингом

Segmented control «trend-window» перемикає: весь час (квартальні бакети,
дефолт), 90 днів (тижневі бакети), 30 днів (денні бакети). Метрика та
split залишаються активними. caseDateMs() + bucketDay() + bucketWeek().

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4 — Heatmap theme axis + axis toggle (HTML)

**Files:**
- Modify: `web/index.html`

**Context:** The heatmap panel is at lines ~278–288. `heatData` computes goal×method cells. We need:
1. Add a seg `heat-axis` with options: `тема×канал` (default), `ціль×спосіб`, `тон×канал`, `формат×канал`.
2. Add `heatAxis` state variable, default `"theme_channel"`.
3. Add `heatDataTheme(camps, metric)` that works over `CAMPAIGNS` (not `CASES`) — it reads each campaign's `themes[]` array vs `channels[]` array. Since the heatmap is in the `view-cases` / `Збори` tab (it uses `CASES`), but `themes` is on campaigns — there are two approaches:
   - **Option A (simpler):** The heatmap for `тема×канал` uses `CAMPAIGNS` directly (independent of `CASES` filter). Show all unfiltered campaigns' theme×channel.
   - **Option B:** Only show when on campaigns tab.
   
   **Use Option A:** The `тема×канал` heatmap uses `CAMPAIGNS` (global, unfiltered or lightly filtered) since campaigns carry `themes` and `channels`. The other axes (goal×method, tone×channel, format×channel) remain on `CASES`. Add a note in the N display.
   
   This keeps the existing `renderHeat(cases)` path intact and adds a new path via `renderHeat` checking `heatAxis`.

4. Update the heatmap panel header to show axis toggle.
5. Update `renderHeat` to branch on `heatAxis`.
6. Add a `heatDataCampaign(axis_a_field, axis_b_field, metric)` helper that works over `CAMPAIGNS`.

**THEME_ORDER** for display: `["fpv","interceptors","reb_ew","vehicles","recon","fiber","medical","comms","ammo","optics_electro","energy","humanitarian"]`

- [ ] **Step 1: Add heatmap axis seg HTML**

Find in the heatmap panel (around line 278):

```html
   <!-- HEATMAP -->
   <div class="panel">
    <div class="head">
     <h3>теплокарта ціль × спосіб</h3><span class="n" id="heat-n"></span>
     <span class="spacer"></span>
     <div class="seg" id="heat-metric">
      <button data-m="count" class="on">к-сть</button>
      <button data-m="volume_usd">обсяг ₴</button>
     </div>
    </div>
```

Replace with:

```html
   <!-- HEATMAP -->
   <div class="panel">
    <div class="head">
     <h3>теплокарта</h3><span class="n" id="heat-n"></span>
     <span class="spacer"></span>
     <div class="seg" id="heat-axis">
      <button data-ax="theme_channel" class="on">тема×канал</button>
      <button data-ax="goal_method">ціль×спосіб</button>
      <button data-ax="tone_channel">тон×канал</button>
      <button data-ax="format_channel">формат×канал</button>
     </div>
     <div class="seg" id="heat-metric">
      <button data-m="count" class="on">к-сть</button>
      <button data-m="volume_usd">обсяг ₴</button>
     </div>
    </div>
```

- [ ] **Step 2: Add `heatAxis` state variable**

Find:
```javascript
let trendMetric="volume_usd", trendSplit="", trendWindow=0, heatMetric="count", lbAxis="amount_uah", lbDir=-1;
```

Replace with:
```javascript
let trendMetric="volume_usd", trendSplit="", trendWindow=0, heatMetric="count", heatAxis="theme_channel", lbAxis="amount_uah", lbDir=-1;
```

- [ ] **Step 3: Add `THEME_ORDER` constant and `heatDataCampaign` helper**

Add after the existing `CTA_ORDER` and `SA_AXIS_FIELD` constants (around line 523):

```javascript
const THEME_ORDER=["fpv","interceptors","reb_ew","vehicles","recon","fiber","medical","comms","ammo","optics_electro","energy","humanitarian"];
```

Then add after the `heatData` function (after line 611):

```javascript
function heatDataCampaign(axisAField, axisBField, orderA, orderB, metric){
 // Works over CAMPAIGNS (global, unfiltered) since themes+channels live on campaigns.
 // Returns {rowLabels, colLabels, data} same shape as heatData.
 const cells={}; // "a|b" -> list of campaigns
 CAMPAIGNS.forEach(c=>{
  const aVals=(axisAField==="themes")?(c.themes||[]):(c[axisAField]||[]);
  const bVals=Array.isArray(c[axisBField])?(c[axisBField]||[]):(c[axisBField]?[c[axisBField]]:[]);
  aVals.forEach(a=>bVals.forEach(b=>{
   const key=a+"|"+b;(cells[key]=cells[key]||[]).push(c);}));});
 const rowLabels=orderA.filter(a=>CAMPAIGNS.some(c=>(axisAField==="themes"?(c.themes||[]):(c[axisAField]||[])).includes(a)));
 const colLabels=orderB.filter(b=>CAMPAIGNS.some(c=>(Array.isArray(c[axisBField])?(c[axisBField]||[]):(c[axisBField]?[c[axisBField]]:[])).includes(b)));
 const data=[];
 rowLabels.forEach((a,ai)=>colLabels.forEach((b,bi)=>{
  const cell=cells[a+"|"+b];
  if(cell){
   let v;
   if(metric==="count")v=cell.length;
   else{const vals=cell.map(c=>c[metric]==="engagement_rate"?c.engagement_rate:c[metric]).filter(x=>x!=null);v=vals.length?vals.reduce((s,x)=>s+x,0)/vals.length:null;}
   data.push([bi,ai,v==null?0:v,cell.length]);
  }}));
 return {rowLabels,colLabels,data};}
```

- [ ] **Step 4: Update `renderHeat` to branch on `heatAxis`**

Find the full `renderHeat` function (lines ~693–721):

```javascript
// ── HEATMAP ──
function renderHeat(cases){
 const {goals,methods,data}=heatData(cases,heatMetric);
 document.getElementById("heat-n").textContent="N="+data.reduce((s,d)=>s+d[3],0)+" клітинок="+data.length;
 if(!chHeat)return;
 if(!goals.length||!methods.length){
  chHeat.clear();
  chHeat.setOption({backgroundColor:"transparent",
   graphic:{type:"text",left:"center",top:"center",style:{text:"немає даних для теплокарти",fill:"#8893a0",fontFamily:"monospace"}}});
  return;}
 const maxV=Math.max(1,...data.map(d=>d[2]));
 chHeat.setOption({
  backgroundColor:"transparent",
  tooltip:{position:"top",backgroundColor:"#11151c",borderColor:"#222a35",textStyle:{color:"#d7dce2",fontFamily:"monospace"},
   formatter:p=>{const[mi,gi,v,n]=p.data;
    const vs=heatMetric==="volume_usd"?fmtUAH(v):v;
    return `${esc(goals[gi])} × ${esc(methods[mi])}<br><b>${vs}</b> <span style="color:#525c6b">N=${n}</span>`;}},
  grid:{left:130,right:24,top:10,bottom:90},
  xAxis:{type:"category",data:methods,splitArea:{show:true},
   axisLabel:{color:"#8893a0",fontFamily:"monospace",rotate:45,fontSize:10},axisLine:{lineStyle:{color:"#222a35"}}},
  yAxis:{type:"category",data:goals,splitArea:{show:true},
   axisLabel:{color:"#8893a0",fontFamily:"monospace",fontSize:11},axisLine:{lineStyle:{color:"#222a35"}}},
  visualMap:{min:0,max:maxV,calculable:true,orient:"horizontal",left:"center",bottom:6,
   inRange:{color:["#11151c","#1f3a2e","#2e6b4f","#33ff99"]},
   textStyle:{color:"#8893a0",fontFamily:"monospace",fontSize:10}},
  series:[{type:"heatmap",data:data.map(d=>[d[0],d[1],d[2],d[3]]),
   label:{show:true,fontFamily:"monospace",fontSize:10,color:"#0a0c10",
    formatter:p=>{const v=p.data[2];return heatMetric==="volume_usd"?(v>=1e6?(v/1e6).toFixed(0)+"M":v>=1e3?(v/1e3).toFixed(0)+"K":v||""):v||"";}},
   emphasis:{itemStyle:{borderColor:"#ffb000",borderWidth:1}}}]},true);
}
```

Replace with:

```javascript
// ── HEATMAP ──
function renderHeat(cases){
 // Determine row/col data based on heatAxis
 let rowLabels, colLabels, data, tooltipFmt;
 if(heatAxis==="theme_channel"){
  const r=heatDataCampaign("themes","channels",THEME_ORDER,CHANNEL_ORDER,heatMetric);
  rowLabels=r.rowLabels;colLabels=r.colLabels;data=r.data;
  tooltipFmt=(p)=>{const[ci,ri,v,n]=p.data;const vs=heatMetric==="volume_usd"?fmtUAH(v):v;
   return `${esc(rowLabels[ri])} × ${esc(colLabels[ci])}<br><b>${vs}</b> <span style="color:#525c6b">N=${n}</span> <span style="color:#525c6b">(кампанії)</span>`;};
 } else if(heatAxis==="goal_method"){
  const r=heatData(cases,heatMetric);rowLabels=r.goals;colLabels=r.methods;data=r.data;
  tooltipFmt=(p)=>{const[mi,gi,v,n]=p.data;const vs=heatMetric==="volume_usd"?fmtUAH(v):v;
   return `${esc(rowLabels[gi])} × ${esc(colLabels[mi])}<br><b>${vs}</b> <span style="color:#525c6b">N=${n}</span>`;};
 } else if(heatAxis==="tone_channel"){
  const r=heatDataCampaign("tone","channels",TONE_ORDER,CHANNEL_ORDER,heatMetric);
  rowLabels=r.rowLabels;colLabels=r.colLabels;data=r.data;
  tooltipFmt=(p)=>{const[ci,ri,v,n]=p.data;const vs=heatMetric==="volume_usd"?fmtUAH(v):v;
   return `${esc(rowLabels[ri])} × ${esc(colLabels[ci])}<br><b>${vs}</b> <span style="color:#525c6b">N=${n}</span>`;};
 } else { // format_channel
  const r=heatDataCampaign("form_factor","channels",FORM_ORDER,CHANNEL_ORDER,heatMetric);
  rowLabels=r.rowLabels;colLabels=r.colLabels;data=r.data;
  tooltipFmt=(p)=>{const[ci,ri,v,n]=p.data;const vs=heatMetric==="volume_usd"?fmtUAH(v):v;
   return `${esc(rowLabels[ri])} × ${esc(colLabels[ci])}<br><b>${vs}</b> <span style="color:#525c6b">N=${n}</span>`;};
 }
 const campSuffix=(heatAxis==="theme_channel"||heatAxis==="tone_channel"||heatAxis==="format_channel")?" (кампаній="+CAMPAIGNS.length+")":"";
 document.getElementById("heat-n").textContent="N="+data.reduce((s,d)=>s+d[3],0)+" клітинок="+data.length+campSuffix;
 if(!chHeat)return;
 if(!rowLabels.length||!colLabels.length){
  chHeat.clear();
  chHeat.setOption({backgroundColor:"transparent",
   graphic:{type:"text",left:"center",top:"center",style:{text:"нема даних",fill:"#8893a0",fontFamily:"monospace"}}});
  return;}
 const maxV=Math.max(1,...data.map(d=>d[2]));
 chHeat.setOption({
  backgroundColor:"transparent",
  tooltip:{position:"top",backgroundColor:"#11151c",borderColor:"#222a35",textStyle:{color:"#d7dce2",fontFamily:"monospace"},
   formatter:tooltipFmt},
  grid:{left:130,right:24,top:10,bottom:90},
  xAxis:{type:"category",data:colLabels,splitArea:{show:true},
   axisLabel:{color:"#8893a0",fontFamily:"monospace",rotate:45,fontSize:10},axisLine:{lineStyle:{color:"#222a35"}}},
  yAxis:{type:"category",data:rowLabels,splitArea:{show:true},
   axisLabel:{color:"#8893a0",fontFamily:"monospace",fontSize:11},axisLine:{lineStyle:{color:"#222a35"}}},
  visualMap:{min:0,max:maxV,calculable:true,orient:"horizontal",left:"center",bottom:6,
   inRange:{color:["#11151c","#1f3a2e","#2e6b4f","#33ff99"]},
   textStyle:{color:"#8893a0",fontFamily:"monospace",fontSize:10}},
  series:[{type:"heatmap",data:data.map(d=>[d[0],d[1],d[2],d[3]]),
   label:{show:true,fontFamily:"monospace",fontSize:10,color:"#0a0c10",
    formatter:p=>{const v=p.data[2];return heatMetric==="volume_usd"?(v>=1e6?(v/1e6).toFixed(0)+"M":v>=1e3?(v/1e3).toFixed(0)+"K":v||""):v||"";}},
   emphasis:{itemStyle:{borderColor:"#ffb000",borderWidth:1}}}]},true);
}
```

- [ ] **Step 5: Bind the `heat-axis` seg control in `bindSegs`**

Find in `bindSegs`:
```javascript
 document.querySelectorAll("#heat-metric button").forEach(b=>b.onclick=()=>{
  heatMetric=b.dataset.m;document.querySelectorAll("#heat-metric button").forEach(x=>x.classList.toggle("on",x===b));update();});
```

Add BEFORE that line:

```javascript
 document.querySelectorAll("#heat-axis button").forEach(b=>b.onclick=()=>{
  heatAxis=b.dataset.ax;document.querySelectorAll("#heat-axis button").forEach(x=>x.classList.toggle("on",x===b));update();});
```

- [ ] **Step 6: Verify `test_index_clean` still passes**

```
cd C:\Users\tomoo\Documents\GitHub\fundrising_recon
.venv\Scripts\python.exe -m pytest tests/test_index_clean.py -v
```

Expected: PASS.

- [ ] **Step 7: Run node --check on inline script (PowerShell)**

```powershell
$html = Get-Content web\index.html -Raw
$start = $html.IndexOf('<script>') + '<script>'.Length
$end = $html.LastIndexOf('</script>')
$script = $html.Substring($start, $end - $start)
$script | Out-File -Encoding utf8 $env:TEMP\fundrec_check.js
node --check $env:TEMP\fundrec_check.js
echo "node check done"
```

Expected: no syntax errors.

- [ ] **Step 8: Full suite**

```
cd C:\Users\tomoo\Documents\GitHub\fundrising_recon
.venv\Scripts\python.exe -m pytest --ignore=tests/test_check_keys_cli_runs.py -q 2>&1 | tail -10
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
cd C:\Users\tomoo\Documents\GitHub\fundrising_recon
git add web/index.html
git commit -c commit.gpgsign=false -m "$(cat <<'EOF'
feat(ui): теплокарта — вісь тема×канал (дефолт) + перемикач осей

Новий дефолт «тема×канал» використовує campaigns.themes[] (multi-label).
Перемикач: тема×канал / ціль×спосіб / тон×канал / формат×канал.
heatDataCampaign() агрегує над CAMPAIGNS; N у заголовку.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5 — Verification (server smoke test)

**Files:** none (read-only verification)

- [ ] **Step 1: Regenerate cases.json with themes (if DB exists)**

```powershell
cd C:\Users\tomoo\Documents\GitHub\fundrising_recon
if (Test-Path "data\fundrec.db") {
  .venv\Scripts\python.exe -m fundrec.export
  echo "export done"
} else {
  echo "no DB — using existing cases.json or running make_sample"
  .venv\Scripts\python.exe -m fundrec.make_sample
}
```

- [ ] **Step 2: Start dashboard in background**

```powershell
Start-Process -NoNewWindow .venv\Scripts\python.exe -ArgumentList "-m","fundrec.dashboard","--port","8792"
Start-Sleep -Seconds 3
```

- [ ] **Step 3: curl / and check markers**

```powershell
$r = Invoke-WebRequest -Uri "http://localhost:8792/" -UseBasicParsing
$r.StatusCode
$body = $r.Content
# Check for trend window seg id
if ($body -match 'id="trend-window"') { echo "PASS: trend-window seg found" } else { echo "FAIL: trend-window seg missing" }
# Check heatmap axis toggle
if ($body -match 'id="heat-axis"') { echo "PASS: heat-axis seg found" } else { echo "FAIL: heat-axis seg missing" }
# Check тема×канал button
if ($body -match "тема×канал") { echo "PASS: тема×канал button found" } else { echo "FAIL: тема×канал missing" }
# Check 30 днів button in trend-window
if ($body -match "30 днів") { echo "PASS: 30 днів found" } else { echo "FAIL: 30 днів missing" }
```

- [ ] **Step 4: curl /cases.json and check themes field**

```powershell
$j = Invoke-WebRequest -Uri "http://localhost:8792/cases.json" -UseBasicParsing
$j.StatusCode
$data = $j.Content | ConvertFrom-Json
$camps = $data.campaigns
if ($camps.Count -gt 0) {
  $first = $camps[0]
  if ($first.PSObject.Properties.Name -contains "themes") { echo "PASS: themes field present" } else { echo "FAIL: themes field missing" }
} else { echo "WARN: no campaigns in data" }
```

- [ ] **Step 5: Stop the dashboard server**

```powershell
Get-Process python | Where-Object { $_.CommandLine -match "fundrec.dashboard" } | Stop-Process -Force 2>$null
# Fallback: kill any python on port 8792
netstat -ano | findstr ":8792" | ForEach-Object { $pid = ($_ -split '\s+')[-1]; Stop-Process -Id $pid -Force 2>$null }
```

- [ ] **Step 6: Final suite + ruff check**

```powershell
cd C:\Users\tomoo\Documents\GitHub\fundrising_recon
.venv\Scripts\python.exe -m pytest --ignore=tests/test_check_keys_cli_runs.py -q 2>&1 | tail -10
.venv\Scripts\python.exe -m ruff check src/fundrec/ 2>&1 | tail -20
```

Expected: suite passes (except known flaky), ruff clean.

- [ ] **Step 7: git log --oneline**

```
git log --oneline -8
```

Expected to see 3 commits (task 1–3) in order:
1. `feat: додати derive_themes ...`
2. `feat: збагатити export кампаній полем themes ...`
3. `feat(ui): тренд-вікно 30д/90д/весь час ...`
4. `feat(ui): теплокарта — вісь тема×канал ...`

---

## Self-Review

**Spec coverage check:**

| Requirement | Task |
|---|---|
| `derive_themes(text)` pure function with 12 themes | Task 1 |
| 15+ keyword tests incl. multi-label, no-match, boundary | Task 1 |
| Export enriches campaigns with `themes` | Task 2 |
| TDD test for export themes | Task 2 |
| Trend window 30/90/весь час seg control | Task 3 HTML step 1 |
| 30д → daily bucketing | Task 3 JS step 4 |
| 90д → weekly bucketing | Task 3 JS step 4 |
| весь час → quarterly bucketing (existing behavior) | Task 3 JS step 4 |
| Metric + split toggles still work with windowing | Task 3 (trendData is parameterized) |
| Heatmap axis seg control | Task 4 HTML step 1 |
| Default тема×канал | Task 4 (heatAxis state = "theme_channel") |
| Multi-valued themes → each contributes to its row | Task 4 heatDataCampaign |
| Keep goal×method as option | Task 4 (heatAxis==="goal_method" branch) |
| N shown on all widgets | Task 3 (trend-n), Task 4 (heat-n) |
| test_index_clean green | Task 3 step 7, Task 4 step 6 |
| node --check | Task 3 step 8, Task 4 step 7 |
| No regressions | Task 1 step 6, Task 2 step 6, Task 5 step 6 |
| curl / 200 + markers | Task 5 steps 3–4 |

**Placeholder scan:** None found — all steps include exact code.

**Type consistency:**
- `derive_themes(text: str) -> list[str]` — referenced consistently in analyze.py, export.py, and tests.
- `trendData(cases, metric, split, windowDays)` — 4-arg signature used in renderTrend.
- `heatDataCampaign(axisAField, axisBField, orderA, orderB, metric)` — used consistently in renderHeat branches.
- `caseDateMs(c)` — defined once, used in `trendData` and `renderTrend`.
