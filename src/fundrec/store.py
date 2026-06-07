"""Сховище SQLite: connect/init + upsert/load для actors, sources, cases.

JSON-поля (links, style, method, provenance) серіалізуються в TEXT-колонки.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import fields
from pathlib import Path

from . import config
from .schema import Actor, Campaign, Case, CreativeAsset, Partner, Source

_SCHEMA_SQL = (Path(__file__).parent / "db" / "schema.sql").read_text(encoding="utf-8")
_JSON_CASE_FIELDS = ("style", "method", "provenance")


def connect(path: Path | str = config.DB_PATH) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)
    conn.commit()


def upsert_actor(conn: sqlite3.Connection, actor: Actor) -> None:
    conn.execute(
        "INSERT INTO actors (id, name, type, founded, links) VALUES (?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET name=excluded.name, type=excluded.type, "
        "founded=excluded.founded, links=excluded.links",
        (
            actor.id,
            actor.name,
            actor.type,
            actor.founded,
            json.dumps(actor.links, ensure_ascii=False),
        ),
    )
    conn.commit()


def upsert_source(conn: sqlite3.Connection, source: Source) -> None:
    conn.execute(
        "INSERT INTO sources (url, type, tier, access, license, actor_id) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(url) DO UPDATE SET type=excluded.type, tier=excluded.tier, "
        "access=excluded.access, license=excluded.license, actor_id=excluded.actor_id",
        (source.url, source.type, source.tier, source.access, source.license, source.actor_id),
    )
    conn.commit()


def _case_columns() -> list[str]:
    return [f.name for f in fields(Case)]


def upsert_case(conn: sqlite3.Connection, case: Case) -> None:
    cols = _case_columns()
    values = []
    for name in cols:
        val = getattr(case, name)
        if name in _JSON_CASE_FIELDS:
            val = json.dumps(val, ensure_ascii=False)
        values.append(val)
    placeholders = ",".join("?" for _ in cols)
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "id")
    conn.execute(
        f"INSERT INTO cases ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        values,
    )
    conn.commit()


def _row_to_case(row: sqlite3.Row) -> Case:
    data = dict(row)
    for name in _JSON_CASE_FIELDS:
        data[name] = json.loads(data[name])
    return Case(**data)


def load_cases(conn: sqlite3.Connection) -> list[Case]:
    rows = conn.execute("SELECT * FROM cases ORDER BY id").fetchall()
    return [_row_to_case(r) for r in rows]


def get_case(conn: sqlite3.Connection, case_id: str) -> Case | None:
    row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
    return _row_to_case(row) if row else None


# --- Campaign CRUD ---

_JSON_CAMPAIGN_FIELDS = ("channels", "form_factor", "tone", "partner_ids", "provenance")


def _campaign_columns() -> list[str]:
    return [f.name for f in fields(Campaign)]


def upsert_campaign(conn: sqlite3.Connection, c: Campaign) -> None:
    """Зберігає Campaign; також синхронізує campaign_partners рядки."""
    cols = _campaign_columns()
    values = []
    for name in cols:
        val = getattr(c, name)
        if name in _JSON_CAMPAIGN_FIELDS:
            val = json.dumps(val, ensure_ascii=False)
        values.append(val)
    placeholders = ",".join("?" for _ in cols)
    updates = ",".join(f"{col}=excluded.{col}" for col in cols if col != "id")
    conn.execute(
        f"INSERT INTO campaigns ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        values,
    )
    # Синхронізуємо M:N partner_ids → campaign_partners
    conn.execute("DELETE FROM campaign_partners WHERE campaign_id = ?", (c.id,))
    for pid in c.partner_ids:
        conn.execute(
            "INSERT OR IGNORE INTO campaign_partners (campaign_id, partner_id) VALUES (?,?)",
            (c.id, pid),
        )
    conn.commit()


def _row_to_campaign(row: sqlite3.Row, partner_ids: list[str] | None = None) -> Campaign:
    data = dict(row)
    for name in _JSON_CAMPAIGN_FIELDS:
        data[name] = json.loads(data[name])
    if partner_ids is not None:
        data["partner_ids"] = partner_ids
    return Campaign(**data)


def load_campaigns(conn: sqlite3.Connection) -> list[Campaign]:
    rows = conn.execute("SELECT * FROM campaigns ORDER BY id").fetchall()
    result = []
    for row in rows:
        cid = row["id"]
        pid_rows = conn.execute(
            "SELECT partner_id FROM campaign_partners WHERE campaign_id = ? ORDER BY partner_id",
            (cid,),
        ).fetchall()
        partner_ids = [r[0] for r in pid_rows]
        result.append(_row_to_campaign(row, partner_ids=partner_ids))
    return result


def get_campaign(conn: sqlite3.Connection, campaign_id: str) -> Campaign | None:
    row = conn.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
    if not row:
        return None
    pid_rows = conn.execute(
        "SELECT partner_id FROM campaign_partners WHERE campaign_id = ? ORDER BY partner_id",
        (campaign_id,),
    ).fetchall()
    partner_ids = [r[0] for r in pid_rows]
    return _row_to_campaign(row, partner_ids=partner_ids)


def link_campaign_partner(conn: sqlite3.Connection, campaign_id: str, partner_id: str) -> None:
    """Ідемпотентне посилання кампанія→партнер у M:N таблиці."""
    conn.execute(
        "INSERT OR IGNORE INTO campaign_partners (campaign_id, partner_id) VALUES (?,?)",
        (campaign_id, partner_id),
    )
    conn.commit()


# --- CreativeAsset CRUD ---

_JSON_CREATIVE_FIELDS = ("provenance",)


def _creative_columns() -> list[str]:
    return [f.name for f in fields(CreativeAsset)]


def upsert_creative(conn: sqlite3.Connection, a: CreativeAsset) -> None:
    cols = _creative_columns()
    values = []
    for name in cols:
        val = getattr(a, name)
        if name in _JSON_CREATIVE_FIELDS:
            val = json.dumps(val, ensure_ascii=False)
        values.append(val)
    placeholders = ",".join("?" for _ in cols)
    updates = ",".join(f"{col}=excluded.{col}" for col in cols if col != "id")
    conn.execute(
        f"INSERT INTO creative_assets ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        values,
    )
    conn.commit()


def _row_to_creative(row: sqlite3.Row) -> CreativeAsset:
    data = dict(row)
    for name in _JSON_CREATIVE_FIELDS:
        data[name] = json.loads(data[name])
    return CreativeAsset(**data)


def load_creatives(
    conn: sqlite3.Connection, campaign_id: str | None = None
) -> list[CreativeAsset]:
    if campaign_id is not None:
        rows = conn.execute(
            "SELECT * FROM creative_assets WHERE campaign_id = ? ORDER BY id",
            (campaign_id,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM creative_assets ORDER BY id").fetchall()
    return [_row_to_creative(r) for r in rows]


# --- Partner CRUD ---

_JSON_PARTNER_FIELDS = ("links",)


def _partner_columns() -> list[str]:
    return [f.name for f in fields(Partner)]


def upsert_partner(conn: sqlite3.Connection, p: Partner) -> None:
    cols = _partner_columns()
    values = []
    for name in cols:
        val = getattr(p, name)
        if name in _JSON_PARTNER_FIELDS:
            val = json.dumps(val, ensure_ascii=False)
        values.append(val)
    placeholders = ",".join("?" for _ in cols)
    updates = ",".join(f"{col}=excluded.{col}" for col in cols if col != "id")
    conn.execute(
        f"INSERT INTO partners ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        values,
    )
    conn.commit()


def _row_to_partner(row: sqlite3.Row) -> Partner:
    data = dict(row)
    for name in _JSON_PARTNER_FIELDS:
        data[name] = json.loads(data[name])
    return Partner(**data)


def load_partners(conn: sqlite3.Connection) -> list[Partner]:
    rows = conn.execute("SELECT * FROM partners ORDER BY id").fetchall()
    return [_row_to_partner(r) for r in rows]


def set_verification(
    conn: sqlite3.Connection,
    case_id: str,
    status: str,
    reason: str | None = None,
    confidence_overall: float | None = None,
) -> None:
    """Update verification_status (always), verdict_reason and confidence_overall (if provided)."""
    parts = ["verification_status = ?"]
    values: list = [status]
    if reason is not None:
        parts.append("verdict_reason = ?")
        values.append(reason)
    if confidence_overall is not None:
        parts.append("confidence_overall = ?")
        values.append(confidence_overall)
    values.append(case_id)
    conn.execute(
        f"UPDATE cases SET {', '.join(parts)} WHERE id = ?",
        values,
    )
    conn.commit()
