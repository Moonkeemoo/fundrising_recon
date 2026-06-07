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

-- F1: нові таблиці для кампаній/креативів/партнерів ---------------------

CREATE TABLE IF NOT EXISTS campaigns (
    id                  TEXT PRIMARY KEY,
    actor_id            TEXT NOT NULL REFERENCES actors(id),
    title               TEXT NOT NULL,
    goal                TEXT NOT NULL,
    type                TEXT NOT NULL,
    channels            TEXT NOT NULL DEFAULT '[]',
    date_start          TEXT,
    date_end            TEXT,
    year                INTEGER,
    form_factor         TEXT NOT NULL DEFAULT '[]',
    cta_type            TEXT,
    tone                TEXT NOT NULL DEFAULT '[]',
    face                TEXT,
    cadence             TEXT,
    playbook_note       TEXT,
    amount_uah          REAL,
    amount_usd          REAL,
    reach               REAL,
    engagement          REAL,
    spend               REAL,
    assets_count        REAL,
    case_id             TEXT REFERENCES cases(id),
    partner_ids         TEXT NOT NULL DEFAULT '[]',
    provenance          TEXT NOT NULL DEFAULT '{}',
    confidence_overall  REAL NOT NULL DEFAULT 0.0,
    verification_status TEXT NOT NULL DEFAULT 'auto',
    verdict_reason      TEXT,
    extracted_at        TEXT,
    extracted_by_model  TEXT
);

CREATE TABLE IF NOT EXISTS creative_assets (
    id                  TEXT PRIMARY KEY,
    campaign_id         TEXT NOT NULL REFERENCES campaigns(id),
    platform            TEXT NOT NULL,
    format              TEXT NOT NULL,
    copy_text           TEXT,
    hook                TEXT,
    cta                 TEXT,
    media_url           TEXT,
    published           TEXT,
    impressions_range   TEXT,
    spend_range         TEXT,
    views               REAL,
    likes               REAL,
    provenance          TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS partners (
    id      TEXT PRIMARY KEY,
    name    TEXT NOT NULL,
    role    TEXT NOT NULL,
    links   TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS campaign_partners (
    campaign_id TEXT NOT NULL REFERENCES campaigns(id),
    partner_id  TEXT NOT NULL REFERENCES partners(id),
    PRIMARY KEY (campaign_id, partner_id)
);
