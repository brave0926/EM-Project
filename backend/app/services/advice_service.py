"""Advice text from templates in EN/RU/ZH/KO. No FastAPI.

build_advice() is pure. polish_advice() may ask the LLM to rewrite it, but falls back to
the template on any error, timeout, or if the rewrite drops the 119 line. Not medical advice.
"""

from __future__ import annotations

import asyncio

from backend.app.clients.llm_client import get_llm_client
from backend.app.core.config import LLM_TIMEOUT_S
from backend.app.models.domain import ERFacility, PharmacyFacility, TriageResult
from backend.app.models.enums import Category, DataStatus, Language, Notice, Severity

_T: dict[Language, dict[str, str]] = {
    Language.EN: {
        "red": "This may be life-threatening. Call 119 now.",
        "amber": "Get medical care soon: go to an ER or clinic.",
        "green": "This can usually be handled with first aid. Visit a pharmacy if needed.",
        "critical": "Stay with the person, keep them still and follow the 119 dispatcher. If they are not breathing and you are trained, start CPR.",
        "burn": "Cool the burn under cool (not ice-cold) running water for 20 minutes. Remove rings or tight items nearby. Cover loosely with a clean non-stick dressing. Do not apply ice, butter or toothpaste.",
        "cut": "Press firmly on the wound with a clean cloth for 10 minutes. Rinse with clean water or saline, then cover with a sterile dressing.",
        "fever": "Rest and drink fluids. A fever reducer can be used as labelled. See a doctor if the fever is 39.5 °C or higher, lasts more than 3 days, or comes with a stiff neck, rash or confusion.",
        "other": "Describe your symptoms to a doctor. If they get worse, go to the nearest ER or call 119.",
        "er": "Nearest ER with free beds: {name} ({km} km, tel {tel}).",
        "ph": "Open pharmacy: {name} ({km} km, open until {until}, tel {tel}).",
        "otc": "Useful first-aid items: {items}.",
        Notice.NO_FREE_ER_BEDS: "No ER with free beds found nearby. Call 119 for guidance.",
        Notice.NO_OPEN_PHARMACY: "No open pharmacy found nearby right now.",
        Notice.ER_UNAVAILABLE: "ER data is unavailable right now. Call 119 if you need an ER.",
        Notice.PHARMACY_UNAVAILABLE: "Pharmacy data is unavailable right now.",
        Notice.OTC_UNAVAILABLE: "First-aid item suggestions are unavailable right now.",
        Notice.DATA_UNCERTAIN: "Some facility data is over 3 hours old and may be wrong. Call ahead.",
        Notice.LOCATION_DEFAULT: "Location not given: distances are from Chungju City Hall.",
        "disclaimer": "Not medical advice. In an emergency call 119.",
    },
    Language.RU: {
        "red": "Возможна угроза жизни. Звоните 119 прямо сейчас.",
        "amber": "Нужна медицинская помощь в ближайшее время: обратитесь в отделение неотложной помощи или клинику.",
        "green": "Обычно достаточно первой помощи. При необходимости зайдите в аптеку.",
        "critical": "Оставайтесь рядом с человеком, не двигайте его и следуйте указаниям диспетчера 119. Если человек не дышит и вы обучены, начните СЛР.",
        "burn": "Охлаждайте ожог под прохладной (не ледяной) проточной водой 20 минут. Снимите кольца и тесные вещи рядом с ожогом. Свободно накройте чистой неприлипающей повязкой. Не наносите лёд, масло или зубную пасту.",
        "cut": "Плотно прижмите рану чистой тканью на 10 минут. Промойте чистой водой или физраствором и закройте стерильной повязкой.",
        "fever": "Отдыхайте и пейте больше жидкости. Жаропонижающее можно принять согласно инструкции. Обратитесь к врачу, если температура 39,5 °C или выше, держится больше 3 дней или есть ригидность шеи, сыпь или спутанность сознания.",
        "other": "Опишите симптомы врачу. Если станет хуже, обратитесь в ближайшее отделение неотложной помощи или звоните 119.",
        "er": "Ближайшее отделение неотложной помощи со свободными местами: {name} ({km} км, тел. {tel}).",
        "ph": "Открытая аптека: {name} ({km} км, открыта до {until}, тел. {tel}).",
        "otc": "Полезные средства первой помощи: {items}.",
        Notice.NO_FREE_ER_BEDS: "Рядом не найдено отделений со свободными местами. Звоните 119 за помощью.",
        Notice.NO_OPEN_PHARMACY: "Сейчас рядом нет открытых аптек.",
        Notice.ER_UNAVAILABLE: "Данные об отделениях неотложной помощи сейчас недоступны. Если нужна помощь, звоните 119.",
        Notice.PHARMACY_UNAVAILABLE: "Данные об аптеках сейчас недоступны.",
        Notice.OTC_UNAVAILABLE: "Рекомендации по средствам первой помощи сейчас недоступны.",
        Notice.DATA_UNCERTAIN: "Часть данных старше 3 часов и может быть неточной. Позвоните заранее.",
        Notice.LOCATION_DEFAULT: "Местоположение не указано: расстояния считаются от мэрии Чхунджу.",
        "disclaimer": "Это не медицинская консультация. В экстренной ситуации звоните 119.",
    },
    Language.ZH: {
        "red": "可能危及生命。请立即拨打119。",
        "amber": "请尽快就医：前往急诊室或诊所。",
        "green": "通常可以用急救处理。如有需要，请去药店。",
        "critical": "请陪在患者身边，尽量不要移动他，并听从119调度员的指示。如果患者没有呼吸且您受过培训，请开始心肺复苏。",
        "burn": "用凉的（不是冰冷的）流动水冲洗烧伤处20分钟。摘下附近的戒指或紧身物品。用干净的不粘敷料轻轻覆盖。不要涂冰块、黄油或牙膏。",
        "cut": "用干净的布用力按压伤口10分钟。用清水或生理盐水冲洗，然后用无菌敷料覆盖。",
        "fever": "多休息，多喝水。可按说明服用退烧药。如果体温达到39.5°C或以上、持续超过3天，或出现颈部僵硬、皮疹或意识混乱，请就医。",
        "other": "请向医生描述症状。如果症状加重，请前往最近的急诊室或拨打119。",
        "er": "最近有空床的急诊室：{name}（{km}公里，电话 {tel}）。",
        "ph": "营业中的药店：{name}（{km}公里，营业至{until}，电话 {tel}）。",
        "otc": "可用的急救用品：{items}。",
        Notice.NO_FREE_ER_BEDS: "附近没有找到有空床的急诊室。请拨打119寻求指导。",
        Notice.NO_OPEN_PHARMACY: "附近目前没有营业中的药店。",
        Notice.ER_UNAVAILABLE: "目前无法获取急诊室数据。如需急诊，请拨打119。",
        Notice.PHARMACY_UNAVAILABLE: "目前无法获取药店数据。",
        Notice.OTC_UNAVAILABLE: "目前无法提供急救用品建议。",
        Notice.DATA_UNCERTAIN: "部分数据已超过3小时，可能不准确。请先打电话确认。",
        Notice.LOCATION_DEFAULT: "未提供位置：距离以忠州市政府为起点计算。",
        "disclaimer": "这不是医疗建议。紧急情况请拨打119。",
    },
    Language.KO: {
        "red": "생명이 위험할 수 있습니다. 지금 바로 119에 전화하세요.",
        "amber": "빨리 진료를 받으세요: 응급실이나 병원으로 가세요.",
        "green": "보통 응급처치로 해결할 수 있습니다. 필요하면 약국에 가세요.",
        "critical": "환자 곁에 있고, 가능하면 움직이지 말고 119 상황실의 안내를 따르세요. 숨을 쉬지 않고 교육을 받았다면 심폐소생술을 시작하세요.",
        "burn": "화상 부위를 시원한(얼음처럼 차갑지 않은) 흐르는 물에 20분간 식히세요. 주변의 반지나 꽉 끼는 물건을 빼세요. 깨끗한 비접착 드레싱으로 느슨하게 덮으세요. 얼음, 버터, 치약은 바르지 마세요.",
        "cut": "깨끗한 천으로 상처를 10분간 세게 누르세요. 깨끗한 물이나 식염수로 씻은 뒤 멸균 드레싱으로 덮으세요.",
        "fever": "충분히 쉬고 수분을 섭취하세요. 해열제는 설명서대로 복용할 수 있습니다. 열이 39.5°C 이상이거나 3일 넘게 지속되거나, 목이 뻣뻣하거나 발진, 의식 혼란이 있으면 진료를 받으세요.",
        "other": "의사에게 증상을 설명하세요. 증상이 나빠지면 가까운 응급실로 가거나 119에 전화하세요.",
        "er": "병상이 있는 가장 가까운 응급실: {name} ({km}km, 전화 {tel}).",
        "ph": "영업 중인 약국: {name} ({km}km, {until}까지 영업, 전화 {tel}).",
        "otc": "도움이 되는 응급용품: {items}.",
        Notice.NO_FREE_ER_BEDS: "근처에 병상이 있는 응급실을 찾지 못했습니다. 119에 전화해 안내를 받으세요.",
        Notice.NO_OPEN_PHARMACY: "지금 근처에 영업 중인 약국이 없습니다.",
        Notice.ER_UNAVAILABLE: "지금은 응급실 정보를 가져올 수 없습니다. 응급실이 필요하면 119에 전화하세요.",
        Notice.PHARMACY_UNAVAILABLE: "지금은 약국 정보를 가져올 수 없습니다.",
        Notice.OTC_UNAVAILABLE: "지금은 응급용품 추천을 제공할 수 없습니다.",
        Notice.DATA_UNCERTAIN: "일부 정보가 3시간 이상 지나 정확하지 않을 수 있습니다. 미리 전화로 확인하세요.",
        Notice.LOCATION_DEFAULT: "위치가 없어 충주시청 기준으로 거리를 계산했습니다.",
        "disclaimer": "의료 조언이 아닙니다. 응급 상황에서는 119에 전화하세요.",
    },
}


def data_notices(er: list[ERFacility], pharmacies: list[PharmacyFacility]) -> list[Notice]:
    """Notices that follow from the facility data itself (RT-104 staleness)."""
    if any(f.status is DataStatus.UNCERTAIN for f in [*er, *pharmacies]):
        return [Notice.DATA_UNCERTAIN]
    return []


def _km(distance_km: float | None) -> str:
    return "?" if distance_km is None else f"{distance_km:.1f}"


def build_advice(
    language: Language,
    triage: TriageResult,
    er: list[ERFacility],
    pharmacies: list[PharmacyFacility],
    otc: list[str],
    notices: list[Notice],
) -> str:
    t = _T[language]
    lines = [t[triage.severity.value], t[triage.category.value]]
    free = [e for e in er if e.hvec > 0]
    if free:
        lines.append(t["er"].format(name=free[0].name, km=_km(free[0].distance_km), tel=free[0].tel))
    if triage.severity is not Severity.RED:  # critical: the 119 call comes first, no pharmacy
        known_open = [p for p in pharmacies if p.is_open and p.open_until]
        if known_open:
            p = known_open[0]
            lines.append(t["ph"].format(name=p.name, km=_km(p.distance_km), until=p.open_until, tel=p.tel))
        if otc:
            lines.append(t["otc"].format(items=", ".join(otc)))
    lines += [t[n] for n in notices]
    lines.append(t["disclaimer"])
    return "\n".join(lines)


async def polish_advice(advice: str, language: Language) -> str:
    """Optional LLM rewrite. Any failure, timeout or a rewrite without "119" -> template."""
    try:
        rewritten = await asyncio.wait_for(get_llm_client().rewrite_advice(advice, language), LLM_TIMEOUT_S)
    except Exception:
        return advice
    return rewritten if rewritten and "119" in rewritten else advice
