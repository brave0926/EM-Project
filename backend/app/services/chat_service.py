"""Small talk: a reply like an assistant when the message is only a greeting, thanks, "how are you",
"who are you" or a goodbye (EN/RU/ZH/KO).

Safety first: the WHOLE message must be small talk. Any word left over ("hi, my hand is burned")
or any keyword the classifier knows sends the message to triage as before. "help" alone is not
small talk: someone may be in trouble, so it stays an emergency (AMBER).
Pure: no I/O, no FastAPI. Not medical advice.
"""

from __future__ import annotations

import re

from backend.app.models.enums import Category, ChatKind, Language
from backend.app.services import classifier_service

MAX_CHARS = 60  # longer messages always go to triage

# Phrases per kind (EN, RU, ZH+KO). EN/RU match whole words, ZH/KO match with spaces removed.
# The first kind that matches names the reply, so ABOUT/HOW_ARE_YOU beat GREETING ("hi, who are you").
_PHRASES: dict[ChatKind, tuple[list[str], list[str], list[str]]] = {
    ChatKind.ABOUT: (
        ["who are you", "what are you", "what can you do", "what do you do", "how does this work",
         "what is this", "are you a bot", "are you ai", "are you an ai"],
        ["кто ты", "кто вы", "что ты умеешь", "что ты можешь", "что вы умеете", "что это", "ты бот"],
        ["你是谁", "你是誰", "你能做什么", "你能做什麼", "这是什么", "這是什麼",
         "누구세요", "누구야", "너는누구", "뭐할수있어", "무엇을할수있", "이게뭐야"],
    ),
    ChatKind.HOW_ARE_YOU: (
        ["how are you", "how are u", "how r u", "how're you", "how's it going", "how is it going", "how you doing",
         "how are you doing", "what's going on", "whats going on", "what's new", "how's life"],
        ["как дела", "как ты", "как вы", "как жизнь", "как поживаешь", "как поживаете", "что нового"],
        ["你好吗", "你好嗎", "你怎么样", "你怎麼樣", "最近怎么样", "最近怎麼樣", "잘지내", "잘지내요", "잘지냈어",
         "어떻게지내", "어떻게지내요", "기분어때"],
    ),
    ChatKind.THANKS: (
        ["thanks", "thank you", "thank u", "thx", "ty", "thanks a lot", "thank you very much", "many thanks"],
        ["спасибо", "спасибки", "спс", "благодарю", "большое спасибо"],
        ["谢谢", "謝謝", "多谢", "多謝", "感谢", "感謝", "감사합니다", "감사해요", "고마워", "고마워요", "고맙습니다"],
    ),
    ChatKind.BYE: (
        ["bye", "goodbye", "bye bye", "see you", "see ya", "good night", "take care"],
        ["пока", "до свидания", "спокойной ночи", "всего доброго"],
        ["再见", "再見", "拜拜", "晚安", "안녕히계세요", "안녕히가세요", "잘가", "잘자", "바이"],
    ),
    ChatKind.GREETING: (
        ["hi", "hello", "hey", "hey there", "hiya", "howdy", "yo", "sup", "what's up", "whats up", "wassup",
         "good morning", "good afternoon", "good evening"],
        ["привет", "приветик", "здравствуй", "здравствуйте", "добрый день", "доброе утро", "добрый вечер",
         "хай", "салют", "хэй"],
        ["你好", "您好", "嗨", "哈喽", "哈囉", "早上好", "下午好", "晚上好", "在吗", "在嗎",
         "안녕하세요", "안녕", "하이", "반가워", "반가워요", "반갑습니다", "좋은아침"],
    ),
}
# Words that may sit around small talk without changing it ("hey bro", "ok thanks", "привет, бот").
_FILLER_EN = ["ok", "okay", "oh", "so", "well", "and", "bro", "dude", "man", "buddy", "friend", "there", "again",
              "bot", "em-agent", "agent", "great", "cool", "nice", "lol", "hmm", "yes", "yeah", "you", "too"]
_FILLER_RU = ["ок", "окей", "ну", "и", "а", "бот", "друг", "бро", "тебе", "вам", "еще", "отлично", "класс"]
_FILLER_CJK = ["啊", "呀", "呢", "吧", "哦", "嗯", "好的", "요", "네", "응", "아", "ㅎㅎ", "ㅋㅋ"]

_PUNCT = re.compile(r"[\s\W_]+", re.UNICODE)


def _strip_words(text: str, words: list[str]) -> str:
    for w in sorted(words, key=len, reverse=True):
        text = re.sub(rf"(?<!\w){re.escape(w)}(?!\w)", " ", text)
    return text


def _has_word(text: str, w: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text) is not None


def detect_chat(text: str) -> ChatKind | None:
    """The kind of small talk when the whole message is small talk, else None (triage it)."""
    lowered = text.lower().replace("ё", "е").replace("\u2019", "'").strip()
    if not lowered or len(lowered) > MAX_CHARS:
        return None
    if classifier_service.classify(text).category is not Category.OTHER:
        return None  # any known emergency word: triage
    compact = _PUNCT.sub("", lowered)
    kind = next(
        (k for k, (en, ru, cjk) in _PHRASES.items()
         if any(_has_word(lowered, w) for w in en + ru) or any(w in compact for w in cjk)),
        None,
    )
    if kind is None:
        return None
    words = [w for en, ru, _ in _PHRASES.values() for w in en + ru]
    rest = _PUNCT.sub("", _strip_words(lowered, words + _FILLER_EN + _FILLER_RU))
    for w in sorted([w for *_, cjk in _PHRASES.values() for w in cjk] + _FILLER_CJK, key=len, reverse=True):
        rest = rest.replace(w, "")
    return kind if not rest else None  # anything left over: not only small talk


_HINT = {
    Language.EN: "If someone is hurt or sick, tell me what happened and where you are, and I will find the nearest "
                 "ER and open pharmacy. In an emergency call 119.",
    Language.RU: "Если кто-то пострадал или заболел, опишите, что случилось и где вы находитесь, и я найду "
                 "ближайшую больницу и открытую аптеку. В экстренном случае звоните 119.",
    Language.ZH: "如果有人受伤或生病，请告诉我发生了什么以及您在哪里，我会帮您找到最近的急诊室和营业中的药店。紧急情况请拨打119。",
    Language.KO: "다치거나 아픈 사람이 있으면 무슨 일이 있었는지, 어디에 계신지 알려 주세요. 가장 가까운 응급실과 "
                 "문을 연 약국을 찾아 드릴게요. 응급 상황에서는 119에 전화하세요.",
}
_OPENING: dict[ChatKind, dict[Language, str]] = {
    ChatKind.GREETING: {
        Language.EN: "Hi! I'm EM-Agent. Is everything okay? Do you need help?",
        Language.RU: "Привет! Я EM-Agent. У вас всё в порядке? Нужна помощь?",
        Language.ZH: "你好！我是 EM-Agent。一切还好吗？需要帮助吗？",
        Language.KO: "안녕하세요! 저는 EM-Agent예요. 괜찮으세요? 도움이 필요하신가요?",
    },
    ChatKind.HOW_ARE_YOU: {
        Language.EN: "I'm fine, thanks for asking, and ready to help. How are you? Is something wrong?",
        Language.RU: "У меня всё хорошо, спасибо, и я готов помочь. А как вы? Что-то случилось?",
        Language.ZH: "我很好，谢谢关心，随时可以帮忙。您呢？发生什么事了吗？",
        Language.KO: "저는 잘 지내요, 물어봐 주셔서 고마워요. 언제든 도와드릴게요. 괜찮으세요? 무슨 일 있으세요?",
    },
    ChatKind.THANKS: {
        Language.EN: "You're welcome! I hope everyone is okay.",
        Language.RU: "Пожалуйста! Надеюсь, все в порядке.",
        Language.ZH: "不客气！希望大家都平安。",
        Language.KO: "천만에요! 모두 괜찮으시길 바라요.",
    },
    ChatKind.ABOUT: {
        Language.EN: "I'm EM-Agent, an emergency assistant for Chungju. I rate how urgent a problem is, find the "
                     "nearest ER with free beds and the nearest open pharmacy, and give first-aid steps. "
                     "I don't give medical diagnoses.",
        Language.RU: "Я EM-Agent, помощник в экстренных ситуациях в Чхунджу. Я оцениваю срочность, нахожу ближайшую "
                     "больницу со свободными местами и открытую аптеку и подсказываю первую помощь. Диагнозы я не ставлю.",
        Language.ZH: "我是 EM-Agent，忠州的紧急情况助手。我会判断情况有多紧急，找到最近有空床位的急诊室和营业中的药店，"
                     "并提供急救步骤。我不做医疗诊断。",
        Language.KO: "저는 충주 지역 응급 도우미 EM-Agent예요. 얼마나 급한 상황인지 판단하고, 빈 병상이 있는 가장 가까운 "
                     "응급실과 문을 연 약국을 찾고, 응급처치 방법을 알려 드려요. 의학적 진단은 하지 않아요.",
    },
    ChatKind.BYE: {
        Language.EN: "Take care! I'm here if you need me.",
        Language.RU: "Берегите себя! Я здесь, если понадоблюсь.",
        Language.ZH: "保重！需要时我随时都在。",
        Language.KO: "몸조심하세요! 필요하면 언제든 불러 주세요.",
    },
}


def reply(kind: ChatKind, language: Language) -> str:
    """Assistant reply in the user's language, always ending with how to get help."""
    return f"{_OPENING[kind][language]}\n{_HINT[language]}"
