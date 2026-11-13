"""Who is hurt: the writer (SELF), someone else (OTHER) or not said (UNKNOWN). Pure rules, no I/O.

Only the wording of the advice and the first-aid card depends on this ("ask someone to stay with
you" instead of "stay with the person"); severity and category never do.

A third person anywhere in the text wins over first-person words: "my son burned his hand" is about
the son, "I am with my friend, he cut his arm" is about the friend. No cue at all -> UNKNOWN, which
keeps the helper wording (safe for both readers).
"""

from __future__ import annotations

import re

from backend.app.models.enums import Patient

# English: whole words (a trailing 's is allowed: "friend's").
_EN_OTHER = (
    "friend", "he", "she", "him", "her", "his", "hers", "son", "daughter", "child", "children", "kid",
    "kids", "baby", "toddler", "mother", "mom", "mum", "father", "dad", "wife", "husband", "brother",
    "sister", "grandma", "grandmother", "grandpa", "grandfather", "someone", "somebody", "person", "man",
    "woman", "boy", "girl", "guy", "colleague", "coworker", "neighbor", "neighbour", "partner",
    "boyfriend", "girlfriend", "roommate", "patient", "classmate",
)
_EN_SELF = ("i", "i'm", "im", "i've", "i'd", "i'll", "me", "my", "myself", "mine")

# Russian: pronouns as whole words, nouns as stems (start of a word).
_RU_OTHER_WORDS = ("он", "она", "его", "ее", "ему", "ей", "ним", "ней", "нему", "неё", "кто-то", "кого-то")
_RU_OTHER_STEMS = (
    "друг", "подруг", "ребен", "ребён", "сын", "доч", "мам", "пап", "мать", "матер", "отец", "отц", "муж",
    "жен", "брат", "сестр", "бабушк", "дедушк", "человек", "коллег", "сосед", "малыш", "пострадавш",
    "пациент", "девочк", "мальчик", "парн", "девушк",
)
_RU_SELF = (
    "я", "мне", "меня", "мной", "мой", "моя", "моё", "мое", "мою", "моей", "моего", "моим", "моих", "мои",
    "моему", "сам", "сама",
)

# Chinese (simplified + traditional): substrings.
_ZH_OTHER = (
    "朋友", "他", "她", "孩子", "儿子", "兒子", "女儿", "女兒", "妈妈", "媽媽", "母亲", "母親", "爸爸", "父亲",
    "父親", "丈夫", "妻子", "老公", "老婆", "有人", "别人", "別人", "宝宝", "寶寶", "婴儿", "嬰兒", "同事",
    "室友", "奶奶", "爷爷", "爺爺", "外婆", "外公", "弟弟", "妹妹", "哥哥", "姐姐", "病人", "患者", "同学", "同學",
)
_ZH_IGNORE = ("其他", "我们", "我們")  # "other" and "we" contain 他 / 我
_ZH_SELF = ("我",)

# Korean: nouns as substrings (with a particle where the bare noun is part of other words).
_KO_OTHER = (
    "친구", "아이가", "아이는", "아이의", "아이를", "아이한테", "아기", "아들", "딸이", "딸은", "딸의", "딸을",
    "엄마", "아빠", "어머니", "아버지", "남편", "아내", "부인", "할머니", "할아버지", "동생", "형이", "형은",
    "언니", "오빠", "누나", "누군가", "사람", "그가", "그는", "그녀", "환자", "동료", "룸메이트",
)
# Korean first person: whole words ("제가 손을 데었어요", "내 손", "저는").
_KO_SELF = (
    "제가", "내가", "저는", "나는", "저도", "나도", "제", "내", "저", "나", "저의", "나의", "저를", "나를",
    "저한테", "나한테", "제게", "내게",
)

_SPLIT = re.compile(r"[\s,.!?;:()\"“”«»、，。！？；：]+")


def _words(text: str) -> list[str]:
    return [w for w in _SPLIT.split(text) if w]


def _en_word(word: str) -> str:
    return word[:-2] if word.endswith("'s") and word not in ("he's", "she's") else word


def detect_patient(text: str) -> Patient:
    lowered = text.lower().replace("’", "'").replace("ё", "е")
    words = _words(lowered)
    en_words = {_en_word(w) for w in words}
    compact = lowered
    for ignore in _ZH_IGNORE:
        compact = compact.replace(ignore, "")
    compact_ns = re.sub(r"\s+", "", compact)

    other = (
        bool(en_words & set(_EN_OTHER)) or {"he's", "she's"} & set(words)
        or bool(set(words) & {w.replace("ё", "е") for w in _RU_OTHER_WORDS})
        or any(w.startswith(stem.replace("ё", "е")) for w in words for stem in _RU_OTHER_STEMS)
        or any(t in compact_ns for t in _ZH_OTHER)
        or any(t in compact_ns for t in _KO_OTHER)
    )
    if other:
        return Patient.OTHER
    self_ = (
        bool(set(words) & set(_EN_SELF))
        or bool(set(words) & {w.replace("ё", "е") for w in _RU_SELF})
        or any(t in compact_ns for t in _ZH_SELF)
        or bool(set(words) & set(_KO_SELF))
    )
    return Patient.SELF if self_ else Patient.UNKNOWN
