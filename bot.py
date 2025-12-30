import os
import json
import re
import logging
from difflib import SequenceMatcher
from typing import Optional, Dict, Any, List, Tuple

from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TELEGRAM_TOKEN")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DISCLAIMER = (
    "⚠️ Ответ носит информационный характер и не является официальным юридическим заключением. "
    "Для индивидуальной ситуации используйте кнопку «✉️ Задать вопрос преподавателю»."
)

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

# Клавиатура (меню)
menu = ReplyKeyboardMarkup(resize_keyboard=True)
menu.add(KeyboardButton(SECTIONS[0]), KeyboardButton(SECTIONS[1]))
menu.add(KeyboardButton(SECTIONS[2]), KeyboardButton(SECTIONS[3]))
menu.add(KeyboardButton(SECTIONS[4]), KeyboardButton(SECTIONS[5]))
menu.add(KeyboardButton(SECTIONS[6]))
menu.add(KeyboardButton(SECTIONS[7]), KeyboardButton(SECTIONS[8]))

# Режимы (если всё же хочешь оставлять "экзамен-режим" кнопкой)
USER_MODE: Dict[int, str] = {}


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

    return p1


FAQ_PATH = resolve_path("FAQ_PATH", "faq.json")
EXAM_PATH = resolve_path("EXAM_PATH", "exam.json")


def load_json_list(path: str, label: str) -> List[Dict[str, Any]]:
    try:
        logging.info(f"Loading {label} from: {path}")
        logging.info(f"{label} exists: {os.path.exists(path)}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            logging.warning(f"{label} is not a list. Using empty list.")
            return []
        logging.info(f"{label} loaded: {len(data)} entries")
        return data
    except Exception as e:
        logging.exception(f"Failed to load {label}: %s", e)
        return []


FAQ = load_json_list(FAQ_PATH, "FAQ")
EXAM = load_json_list(EXAM_PATH, "EXAM")


# ---------------------------
#  Шаг 1: нормализация + опечатки
# ---------------------------

ALIASES = {
    "жлба": "жалоба",
    "жалоб": "жалоба",
    "хамит": "грубость",
    "хам": "грубость",
    "врач хам": "грубость",
    "диагн": "диагноз",
    "диаг": "диагноз",
    "конфл": "конфликт",
    "конфликт с врачом": "конфликт",
    "отказ": "отказали",
    "не приняли": "отказали",
    "не принял": "отказали",
    "тайна": "врачебная тайна",
    "согласие": "информированное согласие",
    "ошибка": "медицинская ошибка",
    "ответственность": "ответственность медработников",
}

STOP_WORDS = {"и", "в", "во", "на", "по", "за", "к", "ко", "о", "об", "от", "это", "что", "как", "ли"}


def clean_text(s: str) -> str:
    s = (s or "").strip().lower()
    # убрать эмодзи/служебное: оставляем буквы/цифры/пробел
    s = re.sub(r"[^0-9a-zа-яё\s-]+", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_query(s: str) -> str:
    s = clean_text(s)
    # алиасы по всей строке
    if s in ALIASES:
        s = ALIASES[s]
    return s


def tokens(s: str) -> List[str]:
    s = normalize_query(s)
    parts = [p for p in s.split() if p and p not in STOP_WORDS]
    return parts


def sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def best_match(entries: List[Dict[str, Any]], user_text: str, keyword_field: str = "keywords") -> Optional[Dict[str, Any]]:
    """
    Возвращает лучший entry по:
    1) точным вхождениям kw в текст
    2) fuzzy-совпадениям (опечатки/обрезки)
    """
    text = normalize_query(user_text)
    tks = tokens(text)

    best: Optional[Dict[str, Any]] = None
    best_score: float = 0.0

    for e in entries:
        kws = e.get(keyword_field) or []
        if not isinstance(kws, list):
            continue

        score = 0.0

        for kw in kws:
            if not isinstance(kw, str):
                continue
            kw_n = normalize_query(kw)

            # 1) точное вхождение фразы
            if kw_n and kw_n in text:
                score += 3.0
                continue

            # 2) fuzzy: сравниваем kw с каждым токеном пользователя
            for tk in tks:
                if not tk or not kw_n:
                    continue

                # короткие токены типа "диагн" — тоже ловим
                r = sim(tk, kw_n)
                if r >= 0.82:
                    score += 1.6
                elif len(tk) >= 4 and len(kw_n) >= 4 and (tk in kw_n or kw_n in tk):
                    score += 1.1

        # бонус, если entry в нужной секции (опционально)
        if score > best_score:
            best_score = score
            best = e

    # порог: чтобы не ловил мусор
    return best if best_score >= 1.2 else None


def format_faq_answer(entry: Dict[str, Any]) -> str:
    answer = (entry.get("answer") or entry.get("a") or "").strip()
    law = (entry.get("law") or "").strip()
    if law:
        answer += f"\n\n🔷 Нормативная база: {law}"
    answer += f"\n\n{DISCLAIMER}"
    return answer


def format_exam_answer(entry: Dict[str, Any]) -> str:
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


# ---------------------------
#  Aiogram init
# ---------------------------

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


# Хардкод: Нормативная база
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


# Хардкод: Вопрос преподавателю
@dp.message_handler(lambda m: (m.text or "").strip() == "✉️ Задать вопрос преподавателю")
async def ask_teacher(message: types.Message):
    await message.answer(
        "Напишите ваш вопрос одним сообщением.\n"
        "Формат: *Тема* → *Суть вопроса*.\n"
        "Не указывайте лишние персональные данные.",
        parse_mode="Markdown",
        reply_markup=menu,
    )


# Кнопка: Мини-тесты (оставим режим, но EXAM будет работать и без него)
@dp.message_handler(lambda m: (m.text or "").strip() == "🧪 Мини-тесты")
async def mini_tests(message: types.Message):
    USER_MODE[message.from_user.id] = "exam"
    await message.answer(
        "🧪 Экзаменационный режим включён.\n\n"
        "Пишите тему/ключевые слова. Чтобы выйти — напишите: выход",
        reply_markup=menu,
    )


# Кнопки разделов: показываем intro, если есть (type="intro")
@dp.message_handler(lambda m: (m.text or "").strip() in SECTIONS)
async def handle_section_buttons(message: types.Message):
    key = (message.text or "").strip()

    intro = next((e for e in FAQ if e.get("section") == key and e.get("type") == "intro"), None)
    if intro:
        await message.answer(format_faq_answer(intro), reply_markup=menu)
        return

    # если intro нет — просто покажем базовую подсказку
    await message.answer(
        "Раздел открыт. Напишите 1–2 ключевых слова по теме (например: «отказали», «жалоба», «врачебная тайна»).",
        reply_markup=menu
    )


# ЕДИНСТВЕННЫЙ обработчик текстовых сообщений (важно!)
@dp.message_handler(lambda m: m.text and (not m.text.startswith("/")) and ((m.text or "").strip() not in SECTIONS))
async def handle_text(message: types.Message):
    uid = message.from_user.id
    raw = (message.text or "").strip()

    # выход из экзамен-режима
    if USER_MODE.get(uid) == "exam" and raw.lower() in ("выход", "выйти", "exit"):
        USER_MODE.pop(uid, None)
        await message.answer("Экзаменационный режим выключён. Можете задавать обычные вопросы.", reply_markup=menu)
        return

    # 1) если пользователь в exam-режиме — сначала EXAM
    if USER_MODE.get(uid) == "exam":
        exam_entry = best_match(EXAM, raw, keyword_field="keywords")
        if exam_entry:
            await message.answer(format_exam_answer(exam_entry), reply_markup=menu)
            return
        await message.answer(
            "По этому запросу экзаменационная карточка не найдена.\n"
            "Попробуйте проще: «ответственность», «дисциплинарная», «уголовная».",
            reply_markup=menu,
        )
        return

    # 2) обычный режим: сначала FAQ (с fuzzy)
    faq_entry = best_match(FAQ, raw, keyword_field="keywords")
    if faq_entry:
        await message.answer(format_faq_answer(faq_entry), reply_markup=menu)
        return

    # 3) если в FAQ не нашли — пробуем EXAM автоматически (Шаг 2)
    exam_entry = best_match(EXAM, raw, keyword_field="keywords")
    if exam_entry:
        await message.answer(format_exam_answer(exam_entry), reply_markup=menu)
        return

    # 4) совсем ничего
    await message.answer(
        "Не нашёл точного ответа в базе знаний.\n"
        "Попробуйте проще (1–2 ключевых слова) или нажмите «✉️ Задать вопрос преподавателю».",
        reply_markup=menu,
    )


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
