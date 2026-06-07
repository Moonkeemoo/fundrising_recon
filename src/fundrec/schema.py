"""Контракт даних: словники + Actor/Source/Case + (де)серіалізація.

Дисципліна (spec §4, §8): значущі числа несуть provenance; осі успіху
порожні до стадії ANALYZE (P3).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

# --- контрольовані словники (spec §4) ---
GOAL_CATEGORIES = {
    "military", "medical", "humanitarian", "reconstruction",
    "energy", "animals", "science_education", "info_defense", "other",
}
STYLE_TAGS = {
    "emotional_personal", "data_transparent", "urgency", "gamification",
    "celebrity", "grassroots", "meme_satire",
}
METHOD_TAGS = {
    "monobank_jar", "bank_transfer", "crypto", "nft_merch", "auction",
    "telethon", "stream", "challenge", "corporate_match", "platform",
}
ACTOR_TYPES = {"foundation", "individual", "milblogger", "corporate", "diaspora", "state"}
SOURCE_TYPES = {"structured", "news", "social"}
VERIFICATION = {"auto", "cross-checked", "verified", "conflict"}


@dataclass
class Actor:
    id: str
    name: str
    type: str
    founded: str | None = None
    links: list[str] = field(default_factory=list)


@dataclass
class Source:
    url: str
    type: str
    tier: int
    access: str
    license: str
    actor_id: str | None = None


@dataclass
class Case:
    id: str
    title: str
    actor_id: str
    url: str
    goal: str                       # "category" або "category/subcategory"
    style: list[str] = field(default_factory=list)
    method: list[str] = field(default_factory=list)
    date_start: str | None = None
    date_end: str | None = None
    year: int | None = None
    amount_uah: float | None = None
    amount_usd: float | None = None
    goal_amount: float | None = None
    currency_raw: str | None = None
    # осі успіху — заповнюються в ANALYZE (P3)
    volume_score: float | None = None
    speed: float | None = None
    virality_score: float | None = None
    repeatability: float | None = None
    # дисципліна
    provenance: dict[str, dict] = field(default_factory=dict)
    confidence_overall: float = 0.0
    verification_status: str = "auto"
    extracted_at: str | None = None
    extracted_by_model: str | None = None


def case_to_dict(c: Case) -> dict:
    return asdict(c)


def case_from_dict(d: dict) -> Case:
    return Case(**d)
