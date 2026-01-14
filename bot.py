import os
import json
import re
import logging
import asyncio
from difflib import SequenceMatcher
from typing import Optional, Dict, Any, List, Tuple

from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# OpenAI (fallback brain)
try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # если пакет не установлен

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # добавим в Render позже

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DISCLAIMER = (
    "⚠️ Ответ носит информационный характер и не является официальным юридическим заключением. "
    "Для индивидуальной ситуации используйте кнопку «✉️ Задать вопрос преподавателю»."

   )
 AI_SYSTEM_PROMPT = """
Ты — ассистент кафедры медицинского права Республики Казахстан.

Отвечай:
• официально-деловым стилем;
• нейтрально, без оценок и эмоций;
• с учётом законодательства Республики Казахстан;
• кратко и структурировано.

Алгоритм ответа:
1) Кратко объясни суть ситуации (1–2 предложения).
2) Укажи, к какому разделу медицинского права относится вопрос.
3) Дай общий алгоритм действий (пункты).
4) При необходимости упомяни нормативные акты (без цитирования статей).

НЕ давай персональных советов и категоричных выводов.

Всегда завершай ответ дисклеймером:
«Ответ носит информационный характер и не является официальным юридическим заключением. Для индивидуальной ситуации используйте кнопку “Задать вопрос преподавателю”.»
"""
SECTIONS = [
    "⚖️ Медицинские ошибки",
    "🚨 Инциденты",
    "🏥 Жалобы пациента",
    "✍️ Информированное согласие",
    "🔒 Врачебная тайна",
    "👮 Ответственность медработников",
    "📄 Нормативная база",
    "✉️ Задать вопрос преподавателю",
    "🧪 Мини-тесты",
]

# ---------- UI ----------
menu = ReplyKeyboardMarkup(resize_keyboard=True)
menu.add(KeyboardButton(SECTIONS[0]), KeyboardButton(SECTIONS[1]))
menu.add(KeyboardButton(SECTIONS[2]), KeyboardButton(SECTIONS[3]))
menu.add(KeyboardButton(SECTIONS[4]), KeyboardButton(SECTIONS[5]))
menu.add(KeyboardButton(SECTIONS[6]))
menu.add(KeyboardButton(SECTIONS[7]), KeyboardButton(SECTIONS[8]))

# ---------- Modes ----------
USER_MODE: Dict[int, str] = {}  # "exam" or ""

# ---------- Paths ----------
def resolve_path(env_var: str, filename: str) -> str:
    env_path = os.getenv(env_var)
    if env_path and os.path.exists(env_path):
        return env_path

    p1 = os.path.join(BASE_DIR, filename)
    if os.path.exists(p1):
        return p1

    p2 = os.path.join(os.getcwd(), filename)
    if os.path.exists(p2):
        return p2

    p3 = os.path.join(os.getcwd(), "medical_law_kz_bot", filename)
    if os.path.exists(p3):
        return p3

    return p1  # самый вероятный

FAQ_PATH = resolve_path("FAQ_PATH", "faq.json")
EXAM_PATH = resolve_path("EXAM_PATH", "exam.json")

def load_json_list(path: str, label: str) -> List[Dict[str, Any]]:
    try:
        logging.info(f"Loading {label} from: {path} (exists={os.path.exists(path)})")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            logging.warning(f"{label} is not a list -> empty.")
            return []
        logging.info(f"{label} loaded: {len(data)} entries")
        return data
    except Exception as e:
        logging.exception(f"Failed to load {label}: %s", e)
        return []

FAQ = load_json_list(FAQ_PATH, "FAQ")
EXAM = load_json_list(EXAM_PATH, "EXAM")

# ---------- Normalization / fuzzy ----------
_WORD_RE = re.compile(r"[a-zа-я0-9]+", re.IGNORECASE)

ALIASES = {
    # твои частые "обрубки/опечатки"
    "жлба": "жалоба",
    "жлб": "жалоба",
    "жба": "жалоба",
    "жалоб": "жалоба",
    "хам": "грубость",
    "хамит": "грубость",
    "грубит": "грубость",
    "конфл": "конфликт",
    "скандал": "конфликт",
    "диагн": "диагноз",
    "диаг": "диагноз",
    "тайна": "врачебная тайна",
    "согласие": "информированное согласие",
    "ошибка": "медицинская ошибка",
    "ответственность": "ответственность медработников",
}

STOP_WORDS = {"и", "в", "во", "на", "по", "за", "к", "ко", "о", "об", "от", "это", "что", "как", "ли"}

def clean_text(s: str) -> str:
    s = (s or "").lower().replace("ё", "е").strip()
    s = re.sub(r"[^0-9a-zа-я\s-]+", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def normalize_query(s: str) -> str:
    s = clean_text(s)
    if s in ALIASES:
        s = ALIASES[s]
    return s

def tokens(s: str) -> List[str]:
    s = normalize_query(s)
    tks = _WORD_RE.findall(s)
    return [t for t in tks if t and t not in STOP_WORDS]

def sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

def score_entry(entry: Dict[str, Any], user_text: str, keyword_field: str = "keywords") -> float:
    """
    Баллы:
      +3.0 если keyword (фраза) входит в текст
      +1.6 если похожесть токена >= 0.78
      +1.1 если обрубок входит (tk in kw or kw in tk) при длине >= 4
    """
    text = normalize_query(user_text)
    tks = tokens(text)
    kws = entry.get(keyword_field) or []
    if not isinstance(kws, list):
        return 0.0

    total = 0.0
    for kw in kws:
        if not isinstance(kw, str) or not kw.strip():
            continue
        kw_n = normalize_query(kw)

        if kw_n and kw_n in text:
            total += 3.0
            continue

        # fuzzy по словам
        best_local = 0.0
        for tk in tks:
            if not tk or not kw_n:
                continue
            r = sim(tk, kw_n)
            if r > best_local:
                best_local = r
            # обрубки
            if len(tk) >= 4 and len(kw_n) >= 4 and (tk in kw_n or kw_n in tk):
                best_local = max(best_local, 0.80)

        if best_local >= 0.78:
            total += 1.6
        elif best_local >= 0.70:
            total += 0.9

    # маленький бонус, если это "card" (чтобы ответы чаще находились)
    if entry.get("type") in ("card", "answer"):
        total += 0.1

    return total

def best_match(entries: List[Dict[str, Any]], user_text: str, keyword_field: str = "keywords") -> Tuple[Optional[Dict[str, Any]], float]:
    best = None
    best_score = 0.0
    for e in entries:
        sc = score_entry(e, user_text, keyword_field=keyword_field)
        if sc > best_score:
            best_score = sc
            best = e
    return best, best_score

# ---------- Formatters ----------
def format_faq(entry: Dict[str, Any]) -> str:
    answer = (entry.get("answer") or entry.get("a") or "").strip()
    law = (entry.get("law") or "").strip()
    if law:
        answer += f"\n\n🔷 Нормативная база: {law}"
    answer += f"\n\n{DISCLAIMER}"
    return answer

def format_exam(entry: Dict[str, Any]) -> str:
    q = (entry.get("question") or "").strip()
    ideal = (entry.get("ideal_answer") or "").strip()
    comment = (entry.get("comment") or "").strip()
    mistake = (entry.get("common_mistake") or "").strip()
    law = (entry.get("law") or "").strip()

    out = "🎓 Экзаменационная карточка"
    if q:
        out += f"\n\n📌 Вопрос:\n{q}"
    if ideal:
        out += f"\n\n✅ Эталонный ответ:\n{ideal}"
    if comment:
        out += f"\n\n💡 Комментарий:\n{comment}"
    if mistake:
        out += f"\n\n⚠️ Типичная ошибка:\n{mistake}"
    if law:
        out += f"\n\n🔷 Нормативная база:\n{law}"
    out += f"\n\n{DISCLAIMER}"
    return out

def find_intro(section_key: str) -> Optional[Dict[str, Any]]:
    return next((e for e in FAQ if e.get("section") == section_key and e.get("type") == "intro"), None)

def find_definition(section_key: str) -> Optional[Dict[str, Any]]:
    # поддерживаем оба варианта: type="def" или role="lead"
    lead = next((e for e in FAQ if e.get("section") == section_key and e.get("type") in ("def",) ), None)
    if lead:
        return lead
    lead2 = next((e for e in FAQ if e.get("section") == section_key and e.get("type") in ("card", "answer") and e.get("role") == "lead"), None)
    return lead2

# ---------- OpenAI fallback ----------
client = OpenAI(api_key=OPENAI_API_KEY) if (OpenAI and OPENAI_API_KEY) else None

def _openai_sync_answer(user_text: str) -> Optional[str]:
    if not client:
        return None

    system_rules = (
        "Ты помощник кафедры медицинского права (Казахстан). "
        "Стиль: официально-деловой, кратко, по шагам. "
        "Не придумывай номера статей/приказов и точные реквизиты, если их нет. "
        "Если требуется уточнение — задай 2-3 коротких уточняющих вопроса. "
        "В конце предложи кнопку «✉️ Задать вопрос преподавателю» для индивидуального кейса."
    )

    # Responses API (рекомендуемый)
    resp = client.responses.create(
        model="gpt-4o-mini",
        input=[
            {"role": "system", "content": system_rules},
            {"role": "user", "content": user_text},
        ],
        # store по умолчанию не обязателен; оставляем false-логикой (без сохранения контекста)
        store=False,
    )
    return (resp.output_text or "").strip() or None

async def openai_answer(user_text: str, timeout_s: int = 18) -> Optional[str]:
    if not client:
        return None
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(loop.run_in_executor(None, _openai_sync_answer, user_text), timeout=timeout_s)
    except Exception as e:
        logging.warning(f"OpenAI fallback failed: {e}")
        return None

# ---------- Aiogram ----------
if not TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is not set.")

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    text = (
        "Здравствуйте! Я бот кафедры медицинского права.\n\n"
        "Я помогаю с типовыми вопросами: медицинские ошибки, инциденты, жалобы, "
        "информированное согласие, врачебная тайна, ответственность.\n\n"
        "Выберите раздел кнопками ниже или просто напишите вопрос текстом."
    )
    await message.answer(text, reply_markup=menu)

@dp.message_handler(commands=["help", "menu"])
async def help_cmd(message: types.Message):
    await message.answer("Выберите раздел кнопками или напишите вопрос текстом.", reply_markup=menu)

@dp.message_handler(lambda m: (m.text or "").strip() == "📄 Нормативная база")
async def law_base(message: types.Message):
    text = (
        "📄 Нормативная база (ориентиры):\n"
        "• Кодекс РК «О здоровье народа и системе здравоохранения»\n"
        "• УК / КоАП / ГК / ТК РК — по ситуации\n"
        "• Внутренние регламенты медорганизации и приказы уполномоченного органа\n\n"
        "Если напишете тему (например, «врачебная тайна»), я подскажу типовой блок норм."
    )
    await message.answer(text, reply_markup=menu)

@dp.message_handler(lambda m: (m.text or "").strip() == "✉️ Задать вопрос преподавателю")
async def ask_teacher(message: types.Message):
    await message.answer(
        "Напишите ваш вопрос одним сообщением.\n"
        "Формат: *Тема* → *Суть вопроса*.\n"
        "Не указывайте лишние персональные данные.",
        parse_mode="Markdown",
        reply_markup=menu,
    )

@dp.message_handler(lambda m: (m.text or "").strip() == "🧪 Мини-тесты")
async def mini_tests(message: types.Message):
    USER_MODE[message.from_user.id] = "exam"
    await message.answer(
        "🧪 Экзаменационный режим включён.\n\n"
        "Пишите тему/ключевые слова. Чтобы выйти — напишите: выход",
        reply_markup=menu,
    )

# Кнопка раздела: intro + def (если есть)
@dp.message_handler(lambda m: (m.text or "").strip() in SECTIONS)
async def handle_section_buttons(message: types.Message):
    key = (message.text or "").strip()

    # для трёх спец-кнопок уже есть отдельные хэндлеры выше
    if key in ("📄 Нормативная база", "✉️ Задать вопрос преподавателю", "🧪 Мини-тесты"):
        return

    intro = find_intro(key)
    definition = find_definition(key)

    parts = []
    if intro:
        parts.append((intro.get("answer") or "").strip())
    if definition and definition is not intro:
        parts.append((definition.get("answer") or "").strip())

    if parts:
        out = "\n\n".join([p for p in parts if p])
        out += f"\n\n{DISCLAIMER}"
        await message.answer(out, reply_markup=menu)
        return

    await message.answer(
        "Раздел открыт. Напишите 1–2 ключевых слова по теме (например: «жалоба», «отказали», «тайна»).",
        reply_markup=menu
    )

# ЕДИНСТВЕННЫЙ текстовый хэндлер (чтобы не было тишины/конфликтов)
@dp.message_handler(lambda m: m.text and (not m.text.startswith("/")) and ((m.text or "").strip() not in SECTIONS))
async def handle_text(message: types.Message):
    uid = message.from_user.id
    raw = (message.text or "").strip()

    # выход из экзамен-режима
    if USER_MODE.get(uid) == "exam" and raw.lower() in ("выход", "выйти", "exit"):
        USER_MODE.pop(uid, None)
        await message.answer("Экзаменационный режим выключён. Можете задавать обычные вопросы.", reply_markup=menu)
        return

    # 1) если включен exam-режим — сначала EXAM
    if USER_MODE.get(uid) == "exam":
        exam_entry, exam_score = best_match(EXAM, raw, keyword_field="keywords")
        if exam_entry and exam_score >= 1.0:
            await message.answer(format_exam(exam_entry), reply_markup=menu)
            return
        await message.answer(
            "По этому запросу экзаменационная карточка не найдена.\n"
            "Попробуйте проще: «ответственность», «дисциплинарная», «уголовная».",
            reply_markup=menu,
        )
        return

    # 2) обычный режим: сравним FAQ и EXAM и выберем лучшее автоматически
    faq_entry, faq_score = best_match(FAQ, raw, keyword_field="keywords")
    exam_entry, exam_score = best_match(EXAM, raw, keyword_field="keywords")

    # Порог, чтобы не стрелять в мусор
    faq_ok = faq_entry is not None and faq_score >= 0.9
    exam_ok = exam_entry is not None and exam_score >= 0.9

    # Автовыбор: если EXAM явно лучше — отдаем EXAM, иначе FAQ
    if faq_ok or exam_ok:
        if exam_ok and (exam_score > faq_score + 0.5):
            await message.answer(format_exam(exam_entry), reply_markup=menu)
            return

        # FAQ ответ + дефиниция сверху, если есть
        section = (faq_entry.get("section") or "").strip()
        definition = find_definition(section) if section else None

        parts = []
        if definition and definition is not faq_entry:
            parts.append((definition.get("answer") or "").strip())

        parts.append((faq_entry.get("answer") or faq_entry.get("a") or "").strip())

        out = "\n\n".join([p for p in parts if p])
        law = (faq_entry.get("law") or "").strip()
        if law:
            out += f"\n\n🔷 Нормативная база: {law}"
        out += f"\n\n{DISCLAIMER}"

        await message.answer(out, reply_markup=menu)
        return

    # 3) если базы не нашли — подключаем меня (AI-fallback), если ключ задан
    ai_text = await openai_answer(raw)
    if ai_text:
        out = ai_text.strip() + f"\n\n{DISCLAIMER}"
        await message.answer(out, reply_markup=menu)
        return

    # 4) совсем ничего
    await message.answer(
        "Не нашёл точного ответа в базе знаний.\n"
        "Попробуйте проще (1–2 ключевых слова) или нажмите «✉️ Задать вопрос преподавателю».",
        reply_markup=menu,
    )

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)

