CREATE TABLE IF NOT EXISTS actors (
    id      TEXT PRIMARY KEY,
    name    TEXT NOT NULL,
    type    TEXT NOT NULL,
    founded TEXT,
    links   TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS sources (
    url      TEXT PRIMARY KEY,
    type     TEXT NOT NULL,
    tier     INTEGER NOT NULL,
    access   TEXT NOT NULL,
    license  TEXT NOT NULL,
    actor_id TEXT REFERENCES actors(id)
);

CREATE TABLE IF NOT EXISTS cases (
    id                  TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    actor_id            TEXT NOT NULL REFERENCES actors(id),
    url                 TEXT NOT NULL,
    goal                TEXT NOT NULL,
    style               TEXT NOT NULL DEFAULT '[]',
    method              TEXT NOT NULL DEFAULT '[]',
    date_start          TEXT,
    date_end            TEXT,
    year                INTEGER,
    amount_uah          REAL,
    amount_usd          REAL,
    goal_amount         REAL,
    currency_raw        TEXT,
    volume_score        REAL,
    speed               REAL,
    virality_score      REAL,
    repeatability       REAL,
    provenance          TEXT NOT NULL DEFAULT '{}',
    confidence_overall  REAL NOT NULL DEFAULT 0.0,
    verification_status TEXT NOT NULL DEFAULT 'auto',
    extracted_at        TEXT,
    extracted_by_model  TEXT,
    verdict_reason      TEXT
);
