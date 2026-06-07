"""Генерація ІЛЮСТРАТИВНОГО зразкового набору кейсів для перевірки кокпіта (P4).

Це НЕ ручний набір фандрайзингу — це демо-дані, щоб морда була показово
робочою ще до живого прогону пайплайна. Кожен кейс позначено
"ILLUSTRATIVE SAMPLE" у `verdict_reason`.

Покриває: всі категорії цілей, кілька стилів/методів, роки 2022–2026,
мікс verification_status (включно з одним `conflict`), пару кейсів із
соц-сигналами (virality non-null) і решту без них (virality null).

Запуск:  python -m fundrec.make_sample
"""
from __future__ import annotations

from . import config, export, store
from .pipeline_analyze import analyze_all
from .schema import Actor, Campaign, Case, CreativeAsset, Partner, Source

_MODEL = "ILLUSTRATIVE-SAMPLE"
_NOTE = "ILLUSTRATIVE SAMPLE — демо-дані для перевірки кокпіта, НЕ реальний кейс."


def _prov(field: str, url: str, tier: int, conf: float = 0.7) -> dict:
    """Мінімальний provenance-запис для значущого поля."""
    return {field: {"source_url": url, "confidence": conf, "tier": tier, "note": _NOTE}}


def _actors() -> list[Actor]:
    return [
        Actor(id="prytula", name="Фонд Сергія Притули", type="foundation",
              founded="2020", links=["https://prytulafoundation.org"]),
        Actor(id="comeback", name="Повернись живим", type="foundation",
              founded="2014", links=["https://savelife.in.ua"]),
        Actor(id="united24", name="UNITED24", type="state",
              founded="2022", links=["https://u24.gov.ua"]),
        Actor(id="sternenko", name="Сергій Стерненко", type="milblogger",
              founded="2022", links=["https://t.me/ssternenko"]),
        Actor(id="uanimals", name="UAnimals", type="foundation",
              founded="2016", links=["https://uanimals.org"]),
        Actor(id="diaspora_ca", name="Діаспора Канади", type="diaspora",
              founded="2022", links=["https://example.org/ca"]),
        Actor(id="corp_monobank", name="monobank", type="corporate",
              founded="2017", links=["https://monobank.ua"]),
        Actor(id="medbat", name="Госпітальєри", type="foundation",
              founded="2014", links=["https://hospitallers.life"]),
    ]


def _sources() -> list[Source]:
    return [
        Source(url="https://send.monobank.ua/jar/sample", type="structured", tier=1,
               access="public", license="unknown", actor_id="prytula"),
        Source(url="https://savelife.in.ua/reports/sample", type="structured", tier=1,
               access="public", license="cc-by", actor_id="comeback"),
        Source(url="https://u24.gov.ua/news/sample", type="news", tier=2,
               access="public", license="unknown", actor_id="united24"),
        Source(url="https://t.me/ssternenko/sample", type="social", tier=3,
               access="public", license="unknown", actor_id="sternenko"),
        Source(url="https://uanimals.org/sample", type="structured", tier=2,
               access="public", license="unknown", actor_id="uanimals"),
        Source(url="https://hospitallers.life/sample", type="structured", tier=2,
               access="public", license="unknown", actor_id="medbat"),
    ]


def _cases() -> list[Case]:
    """~18 ілюстративних кейсів. Суми навмисно круглі/правдоподібні."""
    c: list[Case] = []

    # 1 — military, великий, verified, з соц-сигналами (virality non-null)
    c.append(Case(
        id="s-prytula-satellite", title="Супутник ICEYE", actor_id="prytula",
        url="https://send.monobank.ua/jar/sample", goal="military/recon",
        style=["data_transparent", "celebrity"], method=["monobank_jar", "platform"],
        date_start="2022-06-23", date_end="2022-06-26", year=2022,
        amount_uah=600_000_000.0, goal_amount=500_000_000.0, currency_raw="600 млн ₴",
        provenance=_prov("amount_uah", "https://send.monobank.ua/jar/sample", 1, 0.9),
        confidence_overall=0.9, verification_status="verified", verdict_reason=_NOTE))

    # 2 — military, telethon, cross-checked, соц-сигнали
    c.append(Case(
        id="s-comeback-fpv", title="20 тисяч FPV-дронів", actor_id="comeback",
        url="https://savelife.in.ua/reports/sample", goal="military/fpv",
        style=["data_transparent", "urgency"], method=["bank_transfer", "platform"],
        date_start="2024-02-01", date_end="2024-03-15", year=2024,
        amount_uah=235_000_000.0, goal_amount=235_000_000.0, currency_raw="235 млн ₴",
        provenance=_prov("amount_uah", "https://savelife.in.ua/reports/sample", 1, 0.8),
        confidence_overall=0.8, verification_status="cross-checked", verdict_reason=_NOTE))

    # 3 — military, мілблогер, stream/challenge, cross-checked, соц-сигнали
    c.append(Case(
        id="s-sternenko-drones", title="Збір на дрони (стрім)", actor_id="sternenko",
        url="https://t.me/ssternenko/sample", goal="military/fpv",
        style=["urgency", "grassroots", "meme_satire"], method=["monobank_jar", "stream", "challenge"],
        date_start="2023-11-01", date_end="2023-11-05", year=2023,
        amount_uah=50_000_000.0, goal_amount=40_000_000.0, currency_raw="50 млн ₴",
        provenance=_prov("amount_uah", "https://t.me/ssternenko/sample", 3, 0.6),
        confidence_overall=0.6, verification_status="cross-checked", verdict_reason=_NOTE))

    # 4 — medical, госпітальєри, verified
    c.append(Case(
        id="s-medbat-ambulance", title="Бронемашини для медиків", actor_id="medbat",
        url="https://hospitallers.life/sample", goal="medical/evacuation",
        style=["emotional_personal", "data_transparent"], method=["bank_transfer", "monobank_jar"],
        date_start="2023-05-10", date_end="2023-07-10", year=2023,
        amount_uah=18_000_000.0, goal_amount=20_000_000.0, currency_raw="18 млн ₴",
        provenance=_prov("amount_uah", "https://hospitallers.life/sample", 2, 0.7),
        confidence_overall=0.7, verification_status="verified", verdict_reason=_NOTE))

    # 5 — medical, auto, auto-status (нижче cross-checked)
    c.append(Case(
        id="s-med-tourniquets", title="Турнікети для бригади", actor_id="comeback",
        url="https://savelife.in.ua/reports/sample", goal="medical",
        style=["urgency"], method=["monobank_jar"],
        date_start="2025-01-15", date_end="2025-01-20", year=2025,
        amount_uah=3_000_000.0, goal_amount=3_000_000.0, currency_raw="3 млн ₴",
        provenance=_prov("amount_uah", "https://savelife.in.ua/reports/sample", 2, 0.4),
        confidence_overall=0.4, verification_status="auto", verdict_reason=_NOTE))

    # 6 — humanitarian, united24, verified
    c.append(Case(
        id="s-u24-shelter", title="Прихистки для переселенців", actor_id="united24",
        url="https://u24.gov.ua/news/sample", goal="humanitarian/idp",
        style=["data_transparent"], method=["platform", "corporate_match"],
        date_start="2022-09-01", date_end="2022-12-01", year=2022,
        amount_uah=120_000_000.0, goal_amount=100_000_000.0, currency_raw="120 млн ₴",
        provenance=_prov("amount_uah", "https://u24.gov.ua/news/sample", 2, 0.8),
        confidence_overall=0.8, verification_status="verified", verdict_reason=_NOTE))

    # 7 — humanitarian, grassroots, auto
    c.append(Case(
        id="s-hum-winter", title="Генератори на зиму", actor_id="prytula",
        url="https://send.monobank.ua/jar/sample", goal="humanitarian",
        style=["urgency", "grassroots"], method=["monobank_jar"],
        date_start="2024-10-01", date_end="2024-11-15", year=2024,
        amount_uah=22_000_000.0, goal_amount=25_000_000.0, currency_raw="22 млн ₴",
        provenance=_prov("amount_uah", "https://send.monobank.ua/jar/sample", 1, 0.5),
        confidence_overall=0.5, verification_status="auto", verdict_reason=_NOTE))

    # 8 — reconstruction, cross-checked
    c.append(Case(
        id="s-recon-school", title="Відбудова школи на Чернігівщині", actor_id="united24",
        url="https://u24.gov.ua/news/sample", goal="reconstruction/school",
        style=["data_transparent", "emotional_personal"], method=["platform"],
        date_start="2024-04-01", date_end="2024-08-01", year=2024,
        amount_uah=45_000_000.0, goal_amount=45_000_000.0, currency_raw="45 млн ₴",
        provenance=_prov("amount_uah", "https://u24.gov.ua/news/sample", 2, 0.7),
        confidence_overall=0.7, verification_status="cross-checked", verdict_reason=_NOTE))

    # 9 — energy, corporate_match, verified, соц-сигнали
    c.append(Case(
        id="s-energy-grid", title="Трансформатори для енергосистеми", actor_id="united24",
        url="https://u24.gov.ua/news/sample", goal="energy/grid",
        style=["data_transparent"], method=["platform", "corporate_match"],
        date_start="2023-12-01", date_end="2024-02-01", year=2023,
        amount_uah=80_000_000.0, goal_amount=75_000_000.0, currency_raw="80 млн ₴",
        provenance=_prov("amount_uah", "https://u24.gov.ua/news/sample", 2, 0.8),
        confidence_overall=0.8, verification_status="verified", verdict_reason=_NOTE))

    # 10 — animals, emotional, cross-checked, соц-сигнали
    c.append(Case(
        id="s-animals-shelter", title="Порятунок тварин з-під обстрілів", actor_id="uanimals",
        url="https://uanimals.org/sample", goal="animals/rescue",
        style=["emotional_personal", "meme_satire"], method=["monobank_jar", "nft_merch"],
        date_start="2023-03-01", date_end="2023-04-15", year=2023,
        amount_uah=8_000_000.0, goal_amount=10_000_000.0, currency_raw="8 млн ₴",
        provenance=_prov("amount_uah", "https://uanimals.org/sample", 2, 0.6),
        confidence_overall=0.6, verification_status="cross-checked", verdict_reason=_NOTE))

    # 11 — science_education, auto
    c.append(Case(
        id="s-sci-grant", title="Гранти молодим науковцям", actor_id="united24",
        url="https://u24.gov.ua/news/sample", goal="science_education",
        style=["data_transparent"], method=["platform"],
        date_start="2025-02-01", date_end="2025-05-01", year=2025,
        amount_uah=12_000_000.0, goal_amount=15_000_000.0, currency_raw="12 млн ₴",
        provenance=_prov("amount_uah", "https://u24.gov.ua/news/sample", 2, 0.4),
        confidence_overall=0.4, verification_status="auto", verdict_reason=_NOTE))

    # 12 — info_defense, cross-checked
    c.append(Case(
        id="s-info-counter", title="Протидія дезінформації", actor_id="sternenko",
        url="https://t.me/ssternenko/sample", goal="info_defense",
        style=["urgency", "grassroots"], method=["stream", "monobank_jar"],
        date_start="2024-06-01", date_end="2024-06-10", year=2024,
        amount_uah=6_000_000.0, goal_amount=5_000_000.0, currency_raw="6 млн ₴",
        provenance=_prov("amount_uah", "https://t.me/ssternenko/sample", 3, 0.6),
        confidence_overall=0.6, verification_status="cross-checked", verdict_reason=_NOTE))

    # 13 — other, auction, gamification, auto
    c.append(Case(
        id="s-other-auction", title="Благодійний аукціон артефактів", actor_id="diaspora_ca",
        url="https://send.monobank.ua/jar/sample", goal="other/auction",
        style=["gamification", "celebrity"], method=["auction", "nft_merch"],
        date_start="2024-12-01", date_end="2024-12-20", year=2024,
        amount_uah=15_000_000.0, goal_amount=10_000_000.0, currency_raw="15 млн ₴",
        provenance=_prov("amount_uah", "https://send.monobank.ua/jar/sample", 2, 0.5),
        confidence_overall=0.5, verification_status="auto", verdict_reason=_NOTE))

    # 14 — military, crypto, diaspora, cross-checked
    c.append(Case(
        id="s-diaspora-crypto", title="Крипто-збір діаспори на РЕБ", actor_id="diaspora_ca",
        url="https://savelife.in.ua/reports/sample", goal="military/ew",
        style=["data_transparent", "grassroots"], method=["crypto", "bank_transfer"],
        date_start="2025-03-01", date_end="2025-04-01", year=2025,
        amount_uah=30_000_000.0, goal_amount=28_000_000.0, currency_raw="30 млн ₴",
        provenance=_prov("amount_uah", "https://savelife.in.ua/reports/sample", 2, 0.7),
        confidence_overall=0.7, verification_status="cross-checked", verdict_reason=_NOTE))

    # 15 — humanitarian, corporate, verified, 2026
    c.append(Case(
        id="s-corp-food", title="Продуктові набори (корпоративний матч)", actor_id="corp_monobank",
        url="https://u24.gov.ua/news/sample", goal="humanitarian/food",
        style=["data_transparent"], method=["corporate_match", "platform"],
        date_start="2026-01-10", date_end="2026-02-10", year=2026,
        amount_uah=40_000_000.0, goal_amount=40_000_000.0, currency_raw="40 млн ₴",
        provenance=_prov("amount_uah", "https://u24.gov.ua/news/sample", 2, 0.8),
        confidence_overall=0.8, verification_status="verified", verdict_reason=_NOTE))

    # 16 — military, повторний кейс Притули (для repeatability), 2026
    c.append(Case(
        id="s-prytula-vehicles", title="Пікапи для розвідки", actor_id="prytula",
        url="https://send.monobank.ua/jar/sample", goal="military/logistics",
        style=["data_transparent", "celebrity"], method=["monobank_jar", "platform"],
        date_start="2026-03-01", date_end="2026-03-20", year=2026,
        amount_uah=90_000_000.0, goal_amount=80_000_000.0, currency_raw="90 млн ₴",
        provenance=_prov("amount_uah", "https://send.monobank.ua/jar/sample", 1, 0.8),
        confidence_overall=0.8, verification_status="verified", verdict_reason=_NOTE))

    # 17 — medical, конфлікт у даних (CONFLICT — показуємо, але флагуємо)
    c.append(Case(
        id="s-conflict-meds", title="Партія ліків (суперечливі суми)", actor_id="medbat",
        url="https://hospitallers.life/sample", goal="medical/pharma",
        style=["urgency"], method=["monobank_jar", "bank_transfer"],
        date_start="2025-06-01", date_end="2025-06-30", year=2025,
        amount_uah=10_000_000.0, goal_amount=10_000_000.0, currency_raw="10 млн ₴ (≠ 25 млн у іншому джерелі)",
        provenance=_prov("amount_uah", "https://hospitallers.life/sample", 2, 0.3),
        confidence_overall=0.3, verification_status="conflict",
        verdict_reason=_NOTE + " КОНФЛІКТ: джерела не сходяться щодо суми."))

    # 18 — animals, 2025, auto, без дат (speed=null), без amount? -> має amount
    c.append(Case(
        id="s-animals-feed", title="Корм для притулків", actor_id="uanimals",
        url="https://uanimals.org/sample", goal="animals",
        style=["emotional_personal"], method=["monobank_jar"],
        date_start=None, date_end=None, year=2025,
        amount_uah=2_500_000.0, goal_amount=2_500_000.0, currency_raw="2.5 млн ₴",
        provenance=_prov("amount_uah", "https://uanimals.org/sample", 2, 0.4),
        confidence_overall=0.4, verification_status="auto", verdict_reason=_NOTE))

    return c


_CAMP_NOTE = (
    "ILLUSTRATIVE SAMPLE — демо-кампанія для перевірки дашборда стилю, НЕ реальна."
)


def _partners() -> list[Partner]:
    return [
        Partner(id="p-monobank", name="monobank", role="sponsor",
                links=["https://monobank.ua"]),
        Partner(id="p-novapay", name="NovaPay", role="sponsor",
                links=["https://novapay.ua"]),
        Partner(id="p-celeb-usyk", name="Олександр Усик", role="celebrity",
                links=["https://example.org/usyk"]),
        Partner(id="p-org-uarmy", name="Армія Дронів", role="organizer",
                links=["https://example.org/uarmy"]),
        Partner(id="p-brand-rozetka", name="Rozetka", role="brand",
                links=["https://rozetka.com.ua"]),
    ]


def _cprov(url: str, tier: int, conf: float = 0.6) -> dict:
    return {"campaign": {"source_url": url, "confidence": conf, "tier": tier, "note": _CAMP_NOTE}}


def _campaigns() -> list[Campaign]:
    """~12 ілюстративних кампаній: різні канали/формати/тони/обличчя/CTA/типи,
    роки 2022–2026, мікс null/non-null метрик (reach/engagement/spend)."""
    c: list[Campaign] = []

    c.append(Campaign(
        id="k-prytula-sat-ad", actor_id="prytula", title="Супутник: рекламна кампанія",
        goal="military/recon", type="online_ad",
        channels=["facebook", "instagram"], form_factor=["video", "carousel"],
        tone=["data_transparent", "heroism"], cta_type="donate_link", face="celebrity",
        cadence="one_off", year=2022, date_start="2022-06-20", date_end="2022-06-26",
        amount_uah=600_000_000.0, reach=4_200_000.0, engagement=310_000.0, spend=850_000.0,
        case_id="s-prytula-satellite", partner_ids=["p-monobank", "p-celeb-usyk"],
        playbook_note="Прозорі цифри + публічна особа; короткий дедлайн підсилює терміновість.",
        provenance=_cprov("https://www.facebook.com/ads/library/sample1", 1, 0.8),
        confidence_overall=0.8, verification_status="verified", verdict_reason=_CAMP_NOTE))

    c.append(Campaign(
        id="k-comeback-fpv-tg", actor_id="comeback", title="FPV-дрони: телеграм-збір",
        goal="military/fpv", type="organic_social",
        channels=["telegram", "web"], form_factor=["longread", "image"],
        tone=["urgency", "data_transparent"], cta_type="jar", face="brand",
        cadence="series", year=2024, date_start="2024-02-01", date_end="2024-03-15",
        amount_uah=235_000_000.0, reach=1_800_000.0, engagement=None, spend=None,
        case_id="s-comeback-fpv", partner_ids=["p-novapay"],
        playbook_note="Серійні апдейти з лічильником; банка як основний CTA.",
        provenance=_cprov("https://savelife.in.ua/reports/sample", 1, 0.7),
        confidence_overall=0.7, verification_status="cross-checked", verdict_reason=_CAMP_NOTE))

    c.append(Campaign(
        id="k-sternenko-stream", actor_id="sternenko", title="Стрім-марафон на дрони",
        goal="military/fpv", type="telethon",
        channels=["youtube", "telegram"], form_factor=["stream"],
        tone=["urgency", "humor"], cta_type="jar", face="blogger",
        cadence="series", year=2023, date_start="2023-11-01", date_end="2023-11-05",
        amount_uah=50_000_000.0, reach=2_500_000.0, engagement=420_000.0, spend=None,
        case_id="s-sternenko-drones", partner_ids=[],
        playbook_note="Лайв-стрім із гейміфікацією донатів; мемна подача.",
        provenance=_cprov("https://t.me/ssternenko/sample", 3, 0.6),
        confidence_overall=0.6, verification_status="cross-checked", verdict_reason=_CAMP_NOTE))

    c.append(Campaign(
        id="k-medbat-irl", actor_id="medbat", title="Благодійний забіг (офлайн)",
        goal="medical/evacuation", type="event_irl",
        channels=["irl", "instagram"], form_factor=["image"],
        tone=["emotional", "gratitude"], cta_type="qr", face="official",
        cadence="one_off", year=2023, date_start="2023-05-10", date_end="2023-05-10",
        amount_uah=18_000_000.0, reach=None, engagement=None, spend=120_000.0,
        case_id="s-medbat-ambulance", partner_ids=["p-brand-rozetka", "p-org-uarmy"],
        playbook_note="Офлайн-подія з QR-донатами; емоційні історії медиків.",
        provenance=_cprov("https://hospitallers.life/sample", 2, 0.6),
        confidence_overall=0.6, verification_status="verified", verdict_reason=_CAMP_NOTE))

    c.append(Campaign(
        id="k-u24-shelter-ad", actor_id="united24", title="Прихистки: банерна кампанія",
        goal="humanitarian/idp", type="online_ad",
        channels=["facebook", "web"], form_factor=["banner", "video"],
        tone=["data_transparent"], cta_type="donate_link", face="official",
        cadence="ongoing", year=2022, date_start="2022-09-01", date_end="2022-12-01",
        amount_uah=120_000_000.0, reach=3_100_000.0, engagement=95_000.0, spend=540_000.0,
        case_id="s-u24-shelter", partner_ids=["p-monobank"],
        playbook_note="Державний бренд; банери з чіткою статистикою потреб.",
        provenance=_cprov("https://u24.gov.ua/news/sample", 2, 0.7),
        confidence_overall=0.7, verification_status="verified", verdict_reason=_CAMP_NOTE))

    c.append(Campaign(
        id="k-prytula-winter", actor_id="prytula", title="Генератори: зимовий збір",
        goal="humanitarian", type="jar",
        channels=["instagram", "telegram"], form_factor=["carousel", "image"],
        tone=["urgency", "gratitude"], cta_type="jar", face="celebrity",
        cadence="one_off", year=2024, date_start="2024-10-01", date_end="2024-11-15",
        amount_uah=22_000_000.0, reach=None, engagement=None, spend=None,
        case_id="s-hum-winter", partner_ids=[],
        playbook_note="Сезонна терміновість (зима/блекаути); банка-CTA.",
        provenance=_cprov("https://send.monobank.ua/jar/sample", 1, 0.5),
        confidence_overall=0.5, verification_status="auto", verdict_reason=_CAMP_NOTE))

    c.append(Campaign(
        id="k-u24-school", actor_id="united24", title="Відбудова школи: лонгрід",
        goal="reconstruction/school", type="platform",
        channels=["web", "facebook"], form_factor=["longread", "video"],
        tone=["data_transparent", "emotional"], cta_type="donate_link", face="official",
        cadence="one_off", year=2024, date_start="2024-04-01", date_end="2024-08-01",
        amount_uah=45_000_000.0, reach=900_000.0, engagement=40_000.0, spend=210_000.0,
        case_id="s-recon-school", partner_ids=["p-brand-rozetka"],
        playbook_note="Платформний лонгрід «до/після»; прогрес відбудови.",
        provenance=_cprov("https://u24.gov.ua/news/sample", 2, 0.7),
        confidence_overall=0.7, verification_status="cross-checked", verdict_reason=_CAMP_NOTE))

    c.append(Campaign(
        id="k-energy-grid-ad", actor_id="united24", title="Трансформатори: відео-кампанія",
        goal="energy/grid", type="online_ad",
        channels=["youtube", "facebook"], form_factor=["video"],
        tone=["data_transparent", "heroism"], cta_type="donate_link", face="brand",
        cadence="series", year=2023, date_start="2023-12-01", date_end="2024-02-01",
        amount_uah=80_000_000.0, reach=2_700_000.0, engagement=130_000.0, spend=620_000.0,
        case_id="s-energy-grid", partner_ids=["p-monobank", "p-novapay"],
        playbook_note="Корпоративний матч; відео про критичну інфраструктуру.",
        provenance=_cprov("https://u24.gov.ua/news/sample", 2, 0.7),
        confidence_overall=0.7, verification_status="verified", verdict_reason=_CAMP_NOTE))

    c.append(Campaign(
        id="k-uanimals-rescue", actor_id="uanimals", title="Порятунок тварин: емоційна серія",
        goal="animals/rescue", type="organic_social",
        channels=["instagram", "tiktok"], form_factor=["video", "image"],
        tone=["emotional", "humor"], cta_type="jar", face="anonymous",
        cadence="series", year=2023, date_start="2023-03-01", date_end="2023-04-15",
        amount_uah=8_000_000.0, reach=1_200_000.0, engagement=210_000.0, spend=None,
        case_id="s-animals-shelter", partner_ids=[],
        playbook_note="Емоційні відео порятунку; мерч/NFT як додатковий CTA.",
        provenance=_cprov("https://uanimals.org/sample", 2, 0.6),
        confidence_overall=0.6, verification_status="cross-checked", verdict_reason=_CAMP_NOTE))

    c.append(Campaign(
        id="k-sci-grants", actor_id="united24", title="Гранти науковцям: вебсторінка",
        goal="science_education", type="platform",
        channels=["web"], form_factor=["longread"],
        tone=["data_transparent"], cta_type="subscription", face="official",
        cadence="ongoing", year=2025, date_start="2025-02-01", date_end="2025-05-01",
        amount_uah=12_000_000.0, reach=None, engagement=None, spend=None,
        case_id="s-sci-grant", partner_ids=[],
        playbook_note="Підписна модель регулярних внесків на гранти.",
        provenance=_cprov("https://u24.gov.ua/news/sample", 2, 0.4),
        confidence_overall=0.4, verification_status="auto", verdict_reason=_CAMP_NOTE))

    c.append(Campaign(
        id="k-diaspora-auction", actor_id="diaspora_ca", title="Аукціон артефактів",
        goal="other/auction", type="event_irl",
        channels=["irl", "web"], form_factor=["image", "text"],
        tone=["heroism", "gratitude"], cta_type="auction", face="celebrity",
        cadence="one_off", year=2024, date_start="2024-12-01", date_end="2024-12-20",
        amount_uah=15_000_000.0, reach=None, engagement=None, spend=80_000.0,
        case_id="s-other-auction", partner_ids=["p-celeb-usyk"],
        playbook_note="Аукціонна гейміфікація; діаспорна аудиторія.",
        provenance=_cprov("https://send.monobank.ua/jar/sample", 2, 0.5),
        confidence_overall=0.5, verification_status="auto", verdict_reason=_CAMP_NOTE))

    c.append(Campaign(
        id="k-corp-food-2026", actor_id="corp_monobank", title="Продуктові набори: корп-матч",
        goal="humanitarian/food", type="mixed",
        channels=["facebook", "web", "telegram"], form_factor=["banner", "video"],
        tone=["data_transparent", "gratitude"], cta_type="merch", face="brand",
        cadence="ongoing", year=2026, date_start="2026-01-10", date_end="2026-02-10",
        amount_uah=40_000_000.0, reach=1_500_000.0, engagement=70_000.0, spend=300_000.0,
        case_id="s-corp-food", partner_ids=["p-monobank", "p-brand-rozetka"],
        playbook_note="Корпоративний матч; мерч як винагорода донора.",
        provenance=_cprov("https://u24.gov.ua/news/sample", 2, 0.7),
        confidence_overall=0.7, verification_status="verified", verdict_reason=_CAMP_NOTE))

    return c


def _creatives() -> list[CreativeAsset]:
    """1–3 креативи на кампанію; плейсхолдер-зображення для галереї."""
    a: list[CreativeAsset] = []

    def cr(id, campaign_id, platform, fmt, copy_text, hook, cta, seed,
           views=None, likes=None, impressions_range=None, spend_range=None,
           published=None) -> CreativeAsset:
        return CreativeAsset(
            id=id, campaign_id=campaign_id, platform=platform, format=fmt,
            copy_text=copy_text, hook=hook, cta=cta,
            media_url=f"https://picsum.photos/seed/{seed}/320/180",
            published=published, impressions_range=impressions_range,
            spend_range=spend_range, views=views, likes=likes,
            provenance={"creative": {"source_url": f"https://www.facebook.com/ads/library/{seed}",
                                     "confidence": 0.6, "tier": 2, "note": _CAMP_NOTE}})

    a += [
        cr("cr-sat-1", "k-prytula-sat-ad", "facebook", "video",
           "За 3 дні зберемо на супутник — кожна гривня бачить ціль.",
           "Україна стане першою країною з власним бойовим супутником", "Зробити внесок",
           11, views=820_000.0, likes=64_000.0,
           impressions_range="1M-5M", spend_range="$50K-100K", published="2022-06-21"),
        cr("cr-sat-2", "k-prytula-sat-ad", "instagram", "carousel",
           "Карусель: як працює супутникова розвідка ICEYE.",
           "Дивись, що ти фінансуєш", "Донат за посиланням",
           12, views=410_000.0, likes=33_000.0, published="2022-06-23"),
    ]
    a += [
        cr("cr-fpv-1", "k-comeback-fpv-tg", "telegram", "text",
           "20 000 FPV — лічильник оновлюється щогодини. Доєднуйся.",
           "20 тисяч дронів — реально", "Банка ⬇",
           21, published="2024-02-02"),
        cr("cr-fpv-2", "k-comeback-fpv-tg", "web", "image",
           "Інфографіка: скільки дронів вже зібрано.",
           "Прозорий звіт по кожній партії", "Підтримати",
           22, impressions_range="500K-1M", published="2024-02-20"),
    ]
    a += [
        cr("cr-stream-1", "k-sternenko-stream", "youtube", "stream",
           "Стрім-марафон: ставимо ціль і ламаємо її разом.",
           "Лайв до перемоги цілі", "Кидай у банку",
           31, views=1_400_000.0, likes=180_000.0, published="2023-11-01"),
    ]
    a += [
        cr("cr-irl-1", "k-medbat-irl", "instagram", "image",
           "Забіг на підтримку медиків — скануй QR на старті.",
           "Біжимо за тих, хто рятує", "QR на місці",
           41, published="2023-05-09"),
    ]
    a += [
        cr("cr-shelter-1", "k-u24-shelter-ad", "facebook", "banner",
           "2,3 млн переселенців потребують прихистку цієї зими.",
           "Дім для тих, хто втратив свій", "Допомогти зараз",
           51, impressions_range="1M-5M", spend_range="$100K-500K", published="2022-09-05"),
        cr("cr-shelter-2", "k-u24-shelter-ad", "web", "video",
           "Відео: як облаштовуються модульні містечка.",
           "Від намету до теплого дому", "Внести депозит надії",
           52, views=300_000.0, published="2022-10-01"),
    ]
    a += [
        cr("cr-winter-1", "k-prytula-winter", "instagram", "carousel",
           "Генератор = світло в укритті. Закриваємо потребу.",
           "Зима близько — світло потрібне зараз", "Банка ⬇",
           61, published="2024-10-02"),
    ]
    a += [
        cr("cr-school-1", "k-u24-school", "web", "text",
           "Лонгрід: школа на Чернігівщині — до і після.",
           "Діти повертаються за парти", "Долучитись до відбудови",
           71, published="2024-04-05"),
        cr("cr-school-2", "k-u24-school", "facebook", "video",
           "Тайм-лапс відбудови за 4 місяці.",
           "Руїни → клас за 120 днів", "Підтримати проєкт",
           72, views=220_000.0, likes=18_000.0, published="2024-07-15"),
    ]
    a += [
        cr("cr-grid-1", "k-energy-grid-ad", "youtube", "video",
           "Один трансформатор — світло для цілого району.",
           "Темрява не пройде", "Зробити внесок",
           81, views=900_000.0, likes=72_000.0,
           impressions_range="1M-5M", spend_range="$100K-500K", published="2023-12-05"),
    ]
    a += [
        cr("cr-animals-1", "k-uanimals-rescue", "tiktok", "video",
           "Витягли песика з-під завалів — дивись до кінця.",
           "Він чекав на порятунок 3 дні", "Банка у профілі",
           91, views=2_100_000.0, likes=410_000.0, published="2023-03-03"),
        cr("cr-animals-2", "k-uanimals-rescue", "instagram", "image",
           "До/після: притулок отримав корм на місяць.",
           "Твій донат = миска корму", "Підтримати",
           92, likes=55_000.0, published="2023-04-01"),
    ]
    a += [
        cr("cr-grants-1", "k-sci-grants", "web", "text",
           "Підпишись на щомісячний внесок у науку.",
           "Майбутнє починається з гранту", "Оформити підписку",
           101, published="2025-02-01"),
    ]
    a += [
        cr("cr-auction-1", "k-diaspora-auction", "web", "image",
           "Лот №1: шеврон із автографом. Торги відкрито.",
           "Володій історією — підтримай фронт", "Зробити ставку",
           111, published="2024-12-02"),
    ]
    a += [
        cr("cr-food-1", "k-corp-food-2026", "facebook", "banner",
           "Купуєш — компанія подвоює. Продуктові набори родинам.",
           "Твій внесок × 2", "Замовити з мерчем",
           121, impressions_range="500K-1M", spend_range="$50K-100K", published="2026-01-12"),
        cr("cr-food-2", "k-corp-food-2026", "telegram", "video",
           "Як виглядає набір на місяць для родини.",
           "Один набір — місяць спокою", "Долучитись",
           122, views=140_000.0, published="2026-01-20"),
    ]

    return a


# Соц-сигнали лише для частини кейсів -> virality non-null для них, null для решти.
_SIGNALS = {
    "s-prytula-satellite": {"mentions": 9000, "shares": 4500, "peak": 14000},
    "s-comeback-fpv": {"mentions": 5000, "shares": 2200, "peak": 8000},
    "s-sternenko-drones": {"mentions": 12000, "shares": 6000, "peak": 16000},
    "s-energy-grid": {"mentions": 3000, "shares": 1500, "peak": 5000},
    "s-animals-shelter": {"mentions": 7000, "shares": 3500, "peak": 9000},
}


def build_sample(
    db_path=None,
    out_path=None,
    *,
    _client=None,
) -> None:
    """Будує зразковий набір через справжні частини пайплайна та пише cases.json.

    Args:
        db_path: шлях до SQLite (default config.DB_PATH).
        out_path: шлях до cases.json (default config.CASES_JSON).
        _client: ін'єктований HTTP-клієнт курсу (для тестів = lambda url: []).
    """
    db_path = db_path or config.DB_PATH
    out_path = out_path or config.CASES_JSON
    client = _client if _client is not None else (lambda url: [])

    conn = store.connect(db_path)
    try:
        store.init_db(conn)
        for actor in _actors():
            store.upsert_actor(conn, actor)
        for source in _sources():
            store.upsert_source(conn, source)
        for case in _cases():
            case.extracted_by_model = _MODEL
            store.upsert_case(conn, case)

        # F5: партнери → кампанії (M:N) → креативи.
        for partner in _partners():
            store.upsert_partner(conn, partner)
        for campaign in _campaigns():
            campaign.extracted_by_model = _MODEL
            store.upsert_campaign(conn, campaign)
        for creative in _creatives():
            store.upsert_creative(conn, creative)

        # Прогін через справжній ANALYZE (4 осі + amount_usd через курс).
        analyze_all(conn, signals_by_case=_SIGNALS, _client=client)
        # verification_status уже задано в кейсах; зберігаємо як є через export.
        n = export.export_cases(conn, out_path)
        print(f"[make_sample] записано {n} ілюстративних кейсів -> {out_path}")
    finally:
        conn.close()


def main() -> int:
    import sys  # noqa: PLC0415

    for stream in (sys.stdout, sys.stderr):
        rc = getattr(stream, "reconfigure", None)
        if rc is not None:
            rc(encoding="utf-8")
    build_sample()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
