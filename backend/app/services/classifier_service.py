"""Rule-based triage: category and severity from keywords in EN/RU/ZH/KO.

Cautious by design: critical signs -> red + 119; danger signs (bleeding, deep wound, poisoning...)
-> at least amber; anything unrecognised -> amber, never green.
Keywords of all languages are checked, so mixed-language queries still work.
Pure: no I/O, no FastAPI. Not medical advice.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from backend.app.models.domain import TriageResult
from backend.app.models.enums import Category, Severity
from backend.app.services import patient_service

HIGH_FEVER_C = 39.5


class Words(NamedTuple):
    english: list[str]  # whole words/phrases, list each form ("bleed", "bleeding", "bleeds")
    russian: list[str]  # regex stems matched at a word start ("жар" must not match "пожар"); ё is read as е
    cjk: list[str]  # Chinese (simplified + traditional) / Korean substrings, matched with spaces removed


_KEYWORDS: dict[Category, Words] = {
    # RED + 119. Any match wins over every other category.
    Category.CRITICAL: Words(
        english=[
            "unconscious", "unresponsive", "not conscious", "passed out", "fainted", "collapsed",
            "not breathing", "can't breathe", "cannot breathe", "can not breathe", "stopped breathing",
            "hard to breathe", "difficulty breathing", "trouble breathing", "struggling to breathe",
            "short of breath", "shortness of breath", "chest pain", "chest pains", "chest tightness",
            "heart attack", "stroke", "seizure", "seizures", "seizing", "convulsion", "convulsions",
            "convulsing", "heavy bleeding", "severe bleeding", "bleeding heavily", "won't stop bleeding",
            "bleeding won't stop", "choking", "choked", "overdose", "overdosed", "no pulse",
            "anaphylaxis", "anaphylactic",
            # RED within a high-risk category: snake bite, swelling of the airway
            "snake", "snakebite", "snake bite", "viper", "swollen lips", "swollen tongue", "swollen throat",
            "throat swelling", "throat is swelling", "lips swelling", "tongue swelling", "tight throat",
        ],
        russian=[
            r"без сознани", r"\w*теря\w* сознани", r"(?:упал\w*|падает) в обморок", r"обморок",
            r"не дыш", r"не мо\w* дышать", r"(?:трудно|тяжело|сложно|невозможно|не могу) дышать",
            r"одышк", r"задыха", r"удушь", r"бол\w* в груди", r"бол\w* груд", r"груд\w* бол", r"давит в груди",
            r"инфаркт", r"инсульт", r"судорог", r"судорож", r"припад\w*", r"эпилепс",
            r"(?:сильн|обильн|массивн)\w* кровотеч", r"кров\w* не останавл", r"нет пульса",
            r"анафилак", r"передозир", r"подавил",
            r"зме[яиюейё]", r"змеин", r"гадюк", r"(?:отек|опух)\w* (?:губ|языка|язык|горла|горло|рта)",
            r"(?:губы|язык|горло)\w* (?:опух|отек)",
        ],
        cjk=[
            # ZH
            "昏迷", "昏倒", "晕倒", "暈倒", "不省人事", "失去知觉", "失去知覺", "失去意识", "失去意識",
            "没有呼吸", "沒有呼吸", "不能呼吸", "无法呼吸", "無法呼吸", "停止呼吸", "呼吸困难", "呼吸困難",
            "喘不过气", "喘不過氣", "喘不上气", "透不过气", "胸痛", "胸口痛", "胸口疼", "胸闷", "胸悶",
            "心脏病发作", "心臟病發作", "心梗", "中风", "中風", "脑卒中", "抽搐", "癫痫", "癲癇",
            "痉挛", "痙攣", "大出血", "血流不止", "止不住血", "没有脉搏", "沒有脈搏", "噎住", "窒息",
            "服药过量", "服藥過量", "过敏性休克", "過敏性休克",
            "蛇咬", "被蛇", "毒蛇", "嘴唇肿", "嘴唇腫", "舌头肿", "舌頭腫", "喉咙肿", "喉嚨腫", "喉咙发紧",
            # KO (matched without spaces: "호흡 곤란" == "호흡곤란")
            "의식이없", "의식없", "의식을잃", "정신을잃", "기절", "쓰러졌", "쓰러져",
            "숨을안", "숨을못", "숨을쉬지", "숨쉬기힘", "숨쉬기어려", "숨이차", "숨이막", "호흡이없",
            "호흡곤란", "가슴통증", "가슴이아", "가슴아파", "가슴이답답", "흉통", "심장마비", "심근경색",
            "뇌졸중", "중풍", "발작", "경련", "과다출혈", "피가멈추지", "피가안멈", "지혈이안", "맥박이없",
            "질식", "목에걸", "과다복용", "아나필락시스",
            "뱀", "독사", "입술이붓", "입술이부", "혀가붓", "혀가부", "목이붓", "목이부", "목구멍이붓",
        ],
    ),
    # High-risk injuries (checked before CRITICAL so the guide is specific; CRITICAL words still make them RED).
    Category.HEAVY_BLEEDING: Words(
        english=["heavy bleeding", "severe bleeding", "bleeding heavily", "won't stop bleeding", "bleeding won't stop",
                 "bleeding doesn't stop", "bleeding does not stop", "blood won't stop", "spurting blood", "blood spurting"],
        russian=[r"(?:сильн|обильн|массивн)\w* кровотеч", r"кров\w* не останавл", r"кровь хлещ", r"кровь бь[её]т"],
        cjk=["大出血", "血流不止", "止不住血", "血止不住", "喷血", "噴血", "血喷", "과다출혈", "피가멈추지", "피가안멈",
             "지혈이안", "피가계속", "피가뿜"],
    ),
    Category.CHOKING: Words(
        english=["choking", "choked", "choke", "something stuck in his throat", "food stuck in throat"],
        russian=[r"подавил", r"поперхну", r"застрял\w* в горле", r"кусок\w* в горле"],
        cjk=["噎住", "噎到", "卡住喉咙", "卡在喉咙", "卡在喉嚨", "窒息", "목에걸", "질식", "사레"],
    ),
    Category.DROWNING: Words(
        english=["drowning", "drowned", "nearly drowned", "almost drowned", "pulled from the water", "pulled out of the water"],
        russian=[r"тонет", r"тонул", r"утону", r"утоп", r"захлебну", r"из воды вытащ"],
        cjk=["溺水", "淹水", "淹死", "差点淹", "落水", "익사", "물에빠", "물에서건져"],
    ),
    Category.ELECTRIC_SHOCK: Words(
        english=["electric shock", "electrocuted", "electrocution", "shocked by electricity", "live wire"],
        russian=[r"удар\w* током", r"ударило током", r"бь[её]т током", r"электротравм", r"поражени\w* током"],
        cjk=["触电", "觸電", "电击", "電擊", "被电", "감전", "전기에감"],
    ),
    Category.ALLERGY: Words(
        english=["allergic", "allergy", "allergic reaction", "anaphylaxis", "anaphylactic", "hives", "swollen lips",
                 "swollen tongue", "swollen throat", "swollen face", "face is swelling", "throat swelling"],
        russian=[r"аллерги", r"анафилак", r"крапивниц", r"(?:отек|опух)\w* (?:лица|лицо|губ|языка|язык|горла|горло)",
                 r"(?:лицо|губы|язык|горло)\w* (?:опух|отек)"],
        cjk=["过敏", "過敏", "荨麻疹", "蕁麻疹", "嘴唇肿", "嘴唇腫", "脸肿", "臉腫", "舌头肿", "舌頭腫", "喉咙肿", "喉嚨腫",
             "알레르기", "알러지", "두드러기", "아나필락시스", "입술이붓", "입술이부", "얼굴이붓", "얼굴이부", "혀가붓",
             "혀가부", "목이붓", "목이부"],
    ),
    Category.BITE: Words(
        english=["bite", "bitten", "bit me", "dog bite", "animal bite", "snake bite", "snakebite"],
        russian=[r"укус", r"укуси", r"укусил", r"покусал", r"зме[яиюейё]", r"змеин", r"гадюк"],
        cjk=["咬伤", "咬傷", "被咬", "被狗咬", "蛇咬", "被蛇", "毒蛇", "물렸", "물린", "개에게", "뱀", "독사"],
    ),
    Category.HEAD_INJURY: Words(
        english=["head injury", "head wound", "hit my head", "hit his head", "hit her head", "hit their head",
                 "hit the head", "banged my head", "banged his head", "bumped my head", "bumped his head",
                 "fell on my head", "fell on his head", "concussion", "head trauma"],
        russian=[r"травм\w* голов", r"удари\w* голов", r"ударил\w* головой", r"разбил\w* голов", r"сотрясени"],
        cjk=["头部受伤", "頭部受傷", "撞到头", "撞到頭", "摔到头", "摔到頭", "头撞", "頭撞", "脑震荡", "腦震盪", "头部外伤",
             "머리를부딪", "머리를다쳤", "머리를다친", "머리부상", "머리를박", "뇌진탕", "머리외상"],
    ),
    Category.EYE_INJURY: Words(
        english=["eye injury", "injured eye", "injured my eye", "in my eye", "in his eye", "in her eye", "in the eye",
                 "in their eye", "in her eyes", "in my eyes", "eye is bleeding", "hit in the eye"],
        russian=[r"в глаз", r"травм\w* глаз", r"поврежд\w* глаз", r"глаз\w* (?:поврежд|травм|кровоточ)"],
        cjk=["眼睛受伤", "眼睛受傷", "进眼睛", "進眼睛", "进了眼睛", "眼睛里", "眼睛裡", "眼外伤", "眼部受伤",
             "눈에들어", "눈을다쳤", "눈을다친", "눈부상", "눈에맞", "눈에뭐가", "눈에이물", "눈에세제", "눈에화학",
             "눈에약품", "눈에모래", "눈을찔", "눈이찔"],
    ),
    Category.FRACTURE: Words(
        english=["broken bone", "broken arm", "broken leg", "broken wrist", "broken ankle", "fracture", "fractured",
                 "bone sticking out", "deformed", "odd angle"],
        russian=[r"перелом", r"сломал\w* (?:руку|ногу|кость|запястье|лодыжку)", r"кость торчит"],
        cjk=["骨折", "骨头断", "骨頭斷", "骨头露出", "骨頭露出", "골절", "뼈가부러", "부러졌", "뼈가튀어"],
    ),
    Category.BURN: Words(
        english=["burn", "burns", "burned", "burnt", "scald", "scalded", "scalding"],
        russian=[r"ожог", r"ожёг", r"обж[её]г", r"обожгл", r"обожж", r"ошпар"],
        cjk=["烧伤", "燒傷", "烫伤", "燙傷", "烧到", "燒到", "烫到", "燙到", "灼伤", "灼傷",
             "화상", "데었", "데인", "뎄"],
    ),
    Category.CUT: Words(
        english=["cut", "cuts", "laceration", "wound", "wounded", "bleed", "bleeds", "bleeding", "knife", "stabbed"],
        russian=[r"порез", r"поранил", r"ран[аыуе]?\b", r"ранен", r"кровотеч", r"кровоточ", r"кровит", r"кровь"],
        cjk=[
            "割伤", "割傷", "切伤", "切傷", "划伤", "劃傷", "刀伤", "刀傷", "伤口", "傷口", "流血", "出血",
            "베였", "베인", "상처", "찢어", "찢어진", "출혈", "피가나", "피가많", "피나",
        ],
    ),
    Category.FEVER: Words(
        english=["fever", "feverish", "temperature", "high temperature"],
        russian=[r"температур", r"жар(?:ом|у)?\b", r"лихорад"],
        cjk=["发烧", "發燒", "发热", "發熱", "高烧", "高燒",
             "열이", "열나", "열과", "열도", "열은", "열을", "열에", "발열", "고열", "미열"],
    ),
    # Mild complaints: GREEN (pharmacy first) unless a severity or danger word lifts them to AMBER.
    Category.MINOR: Words(
        english=["sore throat", "scratchy throat", "throat hurts", "runny nose", "stuffy nose", "blocked nose",
                 "sneezing"],
        russian=[r"бол\w* горл", r"горло болит", r"перш\w* в горле", r"насморк", r"заложен\w* нос", r"чихан"],
        cjk=["喉咙痛", "喉嚨痛", "喉咙疼", "喉嚨疼", "嗓子疼", "嗓子痛", "咽喉痛", "流鼻涕", "鼻塞", "打喷嚏", "打噴嚏",
             "인후통", "목이아파", "목이따끔", "목감기", "콧물", "코막힘", "코가막", "재채기"],
    ),
}
# High-risk categories have a fixed severity (never GREEN); CRITICAL words anywhere make any case RED.
FIXED_SEVERITY: dict[Category, Severity] = {
    Category.HEAVY_BLEEDING: Severity.RED,
    Category.CHOKING: Severity.RED,
    Category.DROWNING: Severity.RED,
    Category.ELECTRIC_SHOCK: Severity.RED,
    Category.ALLERGY: Severity.AMBER,  # RED with airway swelling / anaphylaxis (CRITICAL words)
    Category.BITE: Severity.AMBER,  # RED for a snake bite (CRITICAL words)
    Category.HEAD_INJURY: Severity.AMBER,
    Category.EYE_INJURY: Severity.AMBER,
    Category.FRACTURE: Severity.AMBER,
}
# Checked in this order: the first category that matches wins (high risk first; fever beats a sore throat).
_PRIORITY = [*FIXED_SEVERITY, Category.CRITICAL, Category.BURN, Category.CUT, Category.FEVER, Category.MINOR]

# Lift burn/cut/fever to AMBER: severity words and danger signs (bleeding, deep wound, poisoning,
# fracture...). A danger sign never comes back GREEN; with no category it is OTHER (AMBER) anyway.
_SEVERE = Words(
    english=[
        "severe", "severely", "deep", "large", "big", "badly", "blister", "blisters", "a lot",
        "bleed", "bleeds", "bleeding", "blood", "poison", "poisoned", "poisoning", "swallowed",
        "fracture", "broken bone", "head injury", "stabbed",
    ],
    russian=[r"сильн", r"глубок", r"больш", r"волдыр", r"много", r"кров", r"отрав", r"проглот",
             r"перелом", r"травм\w* голов"],
    cjk=[
        "严重", "嚴重", "很深", "深度", "伤口深", "傷口深", "大面积", "大面積", "水泡", "很大", "大量",
        "出血", "流血", "血流", "中毒", "误服", "誤服", "骨折",
        "심한", "심하게", "깊", "크게", "넓", "물집", "많이", "출혈", "피가", "피나", "중독", "삼켰", "골절",
    ],
)
# Fever with one of these (the warning signs named in the fever advice) is AMBER, never GREEN.
_FEVER_WARNING = Words(
    english=["headache", "headaches", "head hurts", "head is hurting", "stiff neck", "rash", "confused", "confusion"],
    russian=[r"головн\w* бол", r"бол\w* голов", r"голова болит", r"ригидн", r"шея не сгиба", r"сыпь", r"спутан"],
    cjk=["头痛", "頭痛", "头疼", "頭疼", "颈部僵硬", "頸部僵硬", "脖子僵硬", "皮疹", "意识混乱", "意識混亂",
         "두통", "머리가아", "머리아", "목이뻣뻣", "발진", "의식혼란"],
)
# A two-digit number, optionally with a decimal, not followed by a time/duration word
# ("40 minutes", "10 PM", "12시" are not temperatures).
_TEMPERATURE = re.compile(
    r"(?<![\d.,])(\d{2}(?:[.,]\d)?)(?![\d.,]?\d)"
    r"(?!\s*(?:min|hour|h\b|day|am\b|pm\b|мин|час|дн|분|시|일|分|小时|小時|天|点|點))"
)


def _normalise(text: str) -> tuple[str, str]:
    """(lower-case with ё -> е and ’ -> ', the same without whitespace for CJK matching)."""
    lowered = text.lower().replace("ё", "е").replace("\u2019", "'")
    return lowered, re.sub(r"\s+", "", lowered)


def _matches(text: str, words: Words) -> bool:
    lowered, compact = _normalise(text)
    return (
        any(re.search(rf"\b{re.escape(w)}\b", lowered) for w in words.english)
        or any(re.search(rf"\b{w.replace('ё', 'е')}", lowered) for w in words.russian)
        or any(w in compact for w in words.cjk)
    )


def matches_terms(text: str, english: list[str], russian: list[str], cjk: list[str]) -> bool:
    """Same matching as the keyword tables (whole EN words, RU stems, CJK without spaces)."""
    return _matches(text, Words(english=english, russian=russian, cjk=[w.replace(" ", "") for w in cjk]))


def max_temperature_c(text: str) -> float | None:
    temps = [float(t.replace(",", ".")) for t in _TEMPERATURE.findall(text)]
    temps = [t for t in temps if 34.0 <= t <= 44.0]  # plausible body temperatures only
    return max(temps, default=None)


def classify(text: str) -> TriageResult:
    """Category and severity from the keyword rules; who is hurt from patient_service (wording only)."""
    return _classify(text).model_copy(update={"patient": patient_service.detect_patient(text)})


def _classify(text: str) -> TriageResult:
    lowered = text.lower()
    category = next((c for c in _PRIORITY if _matches(lowered, _KEYWORDS[c])), Category.OTHER)
    critical = category is Category.CRITICAL or _matches(lowered, _KEYWORDS[Category.CRITICAL])
    if critical or FIXED_SEVERITY.get(category) is Severity.RED:
        return TriageResult(category=category, severity=Severity.RED, call_119=True)
    if category in FIXED_SEVERITY:
        return TriageResult(category=category, severity=FIXED_SEVERITY[category], call_119=False)
    if category is Category.OTHER:
        return TriageResult(category=category, severity=Severity.AMBER, call_119=False)
    temp = max_temperature_c(lowered) if category is Category.FEVER else None
    severe = _matches(lowered, _SEVERE) or (temp is not None and temp >= HIGH_FEVER_C)
    if category is Category.FEVER:
        severe = severe or _matches(lowered, _FEVER_WARNING)
    return TriageResult(category=category, severity=Severity.AMBER if severe else Severity.GREEN, call_119=False)
