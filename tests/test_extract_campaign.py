"""Тести для fundrec.extract — extract_campaign (F3)."""
from __future__ import annotations

from fundrec import extract
from fundrec.schema import Source

SRC = Source(
    url="https://www.facebook.com/ads/library/?id=12345",
    type="structured",
    tier=2,
    access="public",
    license="unknown",
    actor_id="a1",
)
RAW = {
    "ad_id": "12345",
    "page_name": "Повернись живим",
    "page_id": "111",
    "title": "FPV-квадри для батальйону",
    "platforms": ["facebook", "instagram"],
    "start_date": "2024-03-01",
    "end_date": "2024-05-31",
    "spend_range": "10000-50000",
    "impressions_range": "100000-500000",
    "copy_text": "Збираємо на FPV-квадрокоптери для захисту Харківщини",
    "media_url": "https://example.com/creative.jpg",
    "format": "image",
}


# --- build_campaign_prompt ---


def test_build_campaign_prompt_includes_raw():
    p = extract.build_campaign_prompt(RAW, SRC)
    assert "FPV-квадри для батальйону" in p


def test_build_campaign_prompt_includes_vocab_lists():
    p = extract.build_campaign_prompt(RAW, SRC)
    # All vocab sets must appear in prompt
    assert "online_ad" in p  # CAMPAIGN_TYPES
    assert "facebook" in p   # CHANNELS
    assert "video" in p      # FORM_FACTORS
    assert "donate_link" in p  # CTA_TYPES
    assert "emotional" in p  # TONES
    assert "soldier" in p    # FACE_TYPES
    assert "one_off" in p    # CADENCE
    assert "sponsor" in p    # PARTNER_ROLES
    assert "carousel" in p   # CREATIVE_FORMATS


def test_build_campaign_prompt_includes_source_info():
    p = extract.build_campaign_prompt(RAW, SRC)
    assert "facebook.com" in p
    assert "tier 2" in p or "tier=2" in p or "2" in p


def test_build_campaign_prompt_requests_json():
    p = extract.build_campaign_prompt(RAW, SRC)
    assert "JSON" in p
    assert "playbook_note" in p


def test_build_campaign_prompt_no_invent_numbers():
    p = extract.build_campaign_prompt(RAW, SRC)
    # Should warn about not inventing numbers
    assert "null" in p.lower() or "не вигадуй" in p.lower() or "not" in p.lower()


# --- parse_campaign_extraction ---


def _llm_obj():
    return {
        "title": "FPV-квадри для батальйону",
        "goal": "military/fpv",
        "type": "online_ad",
        "channels": ["facebook", "instagram"],
        "date_start": "2024-03-01",
        "date_end": "2024-05-31",
        "year": 2024,
        "form_factor": ["image"],
        "cta_type": "donate_link",
        "tone": ["emotional", "urgency"],
        "face": "brand",
        "cadence": "one_off",
        "playbook_note": "Кампанія використовує емоційні звернення до збору FPV-дронів.",
        # Numeric metrics (non-null → provenance)
        "amount_uah": 850000.0,
        "amount_usd": None,
        "reach": 250000.0,
        "engagement": None,
        "spend": None,
        "assets_count": 1.0,
        "case_id": None,
        "creatives": [
            {
                "platform": "facebook",
                "format": "image",
                "copy_text": "Збираємо на FPV-квадрокоптери",
                "hook": "Харківщина потребує вашої допомоги",
                "cta": "Задонатити",
                "media_url": "https://example.com/creative.jpg",
                "published": "2024-03-01",
                "impressions_range": "100000-500000",
                "spend_range": "10000-50000",
                "views": None,
                "likes": None,
            }
        ],
        "partners": [
            {
                "name": "Повернись живим",
                "role": "organizer",
                "links": ["https://povernys.com"],
            }
        ],
    }


def test_parse_campaign_extraction_returns_triple():
    obj = _llm_obj()
    campaign, creatives, partners = extract.parse_campaign_extraction(
        obj, RAW, SRC, model="claude-test", campaign_id="camp1", actor_id="a1"
    )
    assert campaign.id == "camp1"
    assert campaign.actor_id == "a1"
    assert campaign.title == "FPV-квадри для батальйону"
    assert campaign.goal == "military/fpv"
    assert campaign.type == "online_ad"
    assert campaign.verification_status == "auto"
    assert campaign.extracted_by_model == "claude-test"
    assert campaign.extracted_at is not None


def test_parse_campaign_extraction_provenance_on_non_null_metrics():
    """Непорожні числові метрики отримують provenance з tier+confidence."""
    obj = _llm_obj()
    campaign, _, _ = extract.parse_campaign_extraction(
        obj, RAW, SRC, model="m", campaign_id="camp1", actor_id="a1"
    )
    # amount_uah is non-null → should have provenance
    assert "amount_uah" in campaign.provenance
    assert campaign.provenance["amount_uah"]["tier"] == 2
    assert campaign.provenance["amount_uah"]["confidence"] == 0.6  # tier2
    assert campaign.provenance["amount_uah"]["source_url"] == SRC.url

    # reach is non-null → should have provenance
    assert "reach" in campaign.provenance
    assert campaign.provenance["reach"]["tier"] == 2

    # assets_count is non-null → provenance
    assert "assets_count" in campaign.provenance


def test_parse_campaign_extraction_null_metric_no_provenance():
    """Null метрики не отримують provenance."""
    obj = _llm_obj()
    campaign, _, _ = extract.parse_campaign_extraction(
        obj, RAW, SRC, model="m", campaign_id="camp1", actor_id="a1"
    )
    assert "amount_usd" not in campaign.provenance
    assert "engagement" not in campaign.provenance
    assert "spend" not in campaign.provenance


def test_parse_campaign_extraction_confidence_overall():
    """confidence_overall встановлюється за tier, якщо є provenance."""
    obj = _llm_obj()
    campaign, _, _ = extract.parse_campaign_extraction(
        obj, RAW, SRC, model="m", campaign_id="camp1", actor_id="a1"
    )
    assert campaign.confidence_overall == 0.6  # tier2


def test_parse_campaign_extraction_creatives_ids():
    """Креативи отримують id camp1-a0, camp1-a1, …"""
    obj = _llm_obj()
    _, creatives, _ = extract.parse_campaign_extraction(
        obj, RAW, SRC, model="m", campaign_id="camp1", actor_id="a1"
    )
    assert len(creatives) == 1
    assert creatives[0].id == "camp1-a0"
    assert creatives[0].campaign_id == "camp1"
    assert creatives[0].platform == "facebook"
    assert creatives[0].format == "image"


def test_parse_campaign_extraction_creatives_provenance_on_views():
    """Якщо views/likes ненульові — provenance ставиться."""
    obj = _llm_obj()
    obj["creatives"][0]["views"] = 5000.0
    _, creatives, _ = extract.parse_campaign_extraction(
        obj, RAW, SRC, model="m", campaign_id="camp1", actor_id="a1"
    )
    assert "views" in creatives[0].provenance
    assert creatives[0].provenance["views"]["tier"] == 2


def test_parse_campaign_extraction_creatives_null_views_no_provenance():
    """Null views/likes — без provenance."""
    obj = _llm_obj()
    _, creatives, _ = extract.parse_campaign_extraction(
        obj, RAW, SRC, model="m", campaign_id="camp1", actor_id="a1"
    )
    assert "views" not in creatives[0].provenance
    assert "likes" not in creatives[0].provenance


def test_parse_campaign_extraction_partners():
    """Партнери парсяться правильно."""
    obj = _llm_obj()
    _, _, partners = extract.parse_campaign_extraction(
        obj, RAW, SRC, model="m", campaign_id="camp1", actor_id="a1"
    )
    assert len(partners) == 1
    assert partners[0].name == "Повернись живим"
    assert partners[0].role == "organizer"
    assert "povernys.com" in partners[0].links[0]


def test_parse_campaign_extraction_partner_ids_in_campaign():
    """campaign.partner_ids містять id партнерів."""
    obj = _llm_obj()
    campaign, _, partners = extract.parse_campaign_extraction(
        obj, RAW, SRC, model="m", campaign_id="camp1", actor_id="a1"
    )
    assert len(campaign.partner_ids) == 1
    assert campaign.partner_ids[0] == partners[0].id


def test_parse_campaign_extraction_unknown_tone_dropped():
    """Невідомий тег тону відфільтровується, відомі зберігаються."""
    obj = _llm_obj()
    obj["tone"] = ["emotional", "UNKNOWN_TAG_XYZ", "urgency"]
    campaign, _, _ = extract.parse_campaign_extraction(
        obj, RAW, SRC, model="m", campaign_id="camp1", actor_id="a1"
    )
    assert "UNKNOWN_TAG_XYZ" not in campaign.tone
    assert "emotional" in campaign.tone
    assert "urgency" in campaign.tone


def test_parse_campaign_extraction_unknown_channel_dropped():
    """Невідомий канал відфільтровується."""
    obj = _llm_obj()
    obj["channels"] = ["facebook", "UNKNOWN_CHANNEL"]
    campaign, _, _ = extract.parse_campaign_extraction(
        obj, RAW, SRC, model="m", campaign_id="camp1", actor_id="a1"
    )
    assert "UNKNOWN_CHANNEL" not in campaign.channels
    assert "facebook" in campaign.channels


def test_parse_campaign_extraction_unknown_form_factor_dropped():
    """Невідомий form_factor відфільтровується."""
    obj = _llm_obj()
    obj["form_factor"] = ["image", "INVALID_FF"]
    campaign, _, _ = extract.parse_campaign_extraction(
        obj, RAW, SRC, model="m", campaign_id="camp1", actor_id="a1"
    )
    assert "INVALID_FF" not in campaign.form_factor
    assert "image" in campaign.form_factor


# --- extract_campaign ---


def test_extract_campaign_uses_injected_complete():
    """extract_campaign з fake _complete повертає когерентний Campaign+creatives+partners."""
    def fake_complete(prompt: str) -> dict:
        return _llm_obj()

    campaign, creatives, partners = extract.extract_campaign(
        RAW, SRC,
        campaign_id="camp1",
        actor_id="a1",
        model="claude-test",
        _complete=fake_complete,
    )
    assert campaign.id == "camp1"
    assert campaign.title == "FPV-квадри для батальйону"
    assert campaign.type == "online_ad"
    assert len(creatives) == 1
    assert len(partners) == 1
    assert creatives[0].campaign_id == "camp1"


def test_extract_campaign_prompt_passed_to_complete():
    """Переконуємося, що промпт передається в _complete (містить raw дані)."""
    captured = {}

    def fake_complete(prompt: str) -> dict:
        captured["prompt"] = prompt
        return _llm_obj()

    extract.extract_campaign(
        RAW, SRC,
        campaign_id="camp1",
        actor_id="a1",
        model="m",
        _complete=fake_complete,
    )
    assert "FPV-квадри для батальйону" in captured["prompt"]
