"""Контракт даних: словники + Actor/Source/Case + (де)серіалізація.

Дисципліна (spec §4, §8): значущі числа несуть provenance; осі успіху
порожні до стадії ANALYZE (P3).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

# --- контрольовані словники (spec §4) ---
GOAL_CATEGORIES = {
    "military",
    "medical",
    "humanitarian",
    "reconstruction",
    "energy",
    "animals",
    "science_education",
    "info_defense",
    "other",
}
STYLE_TAGS = {
    "emotional_personal",
    "data_transparent",
    "urgency",
    "gamification",
    "celebrity",
    "grassroots",
    "meme_satire",
}
METHOD_TAGS = {
    "monobank_jar",
    "bank_transfer",
    "crypto",
    "nft_merch",
    "auction",
    "telethon",
    "stream",
    "challenge",
    "corporate_match",
    "platform",
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
    goal: str  # "category" або "category/subcategory"
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
    verdict_reason: str | None = None


def case_to_dict(c: Case) -> dict:
    return asdict(c)


def case_from_dict(d: dict) -> Case:
    return Case(**d)


# --- нові контрольовані словники (spec §6, F1) ---

CAMPAIGN_TYPES: set[str] = {
    "online_ad",
    "organic_social",
    "telethon",
    "event_irl",
    "platform",
    "jar",
    "mixed",
}
CHANNELS: set[str] = {
    "facebook",
    "instagram",
    "threads",
    "youtube",
    "telegram",
    "tiktok",
    "web",
    "irl",
}
FORM_FACTORS: set[str] = {
    "video",
    "carousel",
    "banner",
    "longread",
    "stream",
    "image",
    "text",
}
CTA_TYPES: set[str] = {
    "donate_link",
    "jar",
    "qr",
    "auction",
    "subscription",
    "merch",
}
TONES: set[str] = {
    "emotional",
    "urgency",
    "humor",
    "data_transparent",
    "heroism",
    "gratitude",
}
FACE_TYPES: set[str] = {
    "soldier",
    "blogger",
    "celebrity",
    "brand",
    "official",
    "anonymous",
}
CADENCE: set[str] = {"one_off", "series", "ongoing"}
PARTNER_ROLES: set[str] = {"sponsor", "organizer", "celebrity", "brand", "partner"}
CREATIVE_FORMATS: set[str] = {"image", "video", "carousel", "text", "stream"}


# --- нові дата-класи (spec §3, F1) ---


@dataclass
class Campaign:
    """Кампанія фандрайзингу: якісний+числовий шар."""

    id: str
    actor_id: str
    title: str
    goal: str  # category[/subcategory]
    type: str
    channels: list[str] = field(default_factory=list)
    date_start: str | None = None
    date_end: str | None = None
    year: int | None = None
    form_factor: list[str] = field(default_factory=list)
    cta_type: str | None = None
    tone: list[str] = field(default_factory=list)
    face: str | None = None
    cadence: str | None = None
    playbook_note: str | None = None
    # метрики (nullable; honest null)
    amount_uah: float | None = None
    amount_usd: float | None = None
    reach: float | None = None
    engagement: float | None = None
    spend: float | None = None
    assets_count: float | None = None
    # звʼязки
    case_id: str | None = None
    partner_ids: list[str] = field(default_factory=list)
    # дисципліна
    provenance: dict = field(default_factory=dict)
    confidence_overall: float = 0.0
    verification_status: str = "auto"
    verdict_reason: str | None = None
    extracted_at: str | None = None
    extracted_by_model: str | None = None


@dataclass
class CreativeAsset:
    """Окремий рекламний/контентний актив кампанії."""

    id: str
    campaign_id: str
    platform: str
    format: str
    copy_text: str | None = None
    hook: str | None = None
    cta: str | None = None
    media_url: str | None = None
    published: str | None = None
    impressions_range: str | None = None
    spend_range: str | None = None
    views: float | None = None
    likes: float | None = None
    provenance: dict = field(default_factory=dict)


@dataclass
class Partner:
    """Публічна сутність-партнер кампанії (без приватних контактів)."""

    id: str
    name: str
    role: str
    links: list[str] = field(default_factory=list)


# --- серіалізація кампаній ---


def campaign_to_dict(c: Campaign) -> dict:
    return asdict(c)


def campaign_from_dict(d: dict) -> Campaign:
    return Campaign(**d)


def creative_to_dict(a: CreativeAsset) -> dict:
    return asdict(a)


def creative_from_dict(d: dict) -> CreativeAsset:
    return CreativeAsset(**d)


def partner_to_dict(p: Partner) -> dict:
    return asdict(p)


def partner_from_dict(d: dict) -> Partner:
    return Partner(**d)
