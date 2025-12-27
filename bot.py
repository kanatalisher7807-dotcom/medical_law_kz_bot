import os
import json
import logging
from typing import Optional, Dict, Any, List

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

# режим пользователя: обычный / exam
USER_MODE: Dict[int, str] = {}


def resolve_faq_path() -> str:
    env_path = os.getenv("FAQ_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    p1 = os.path.join(BASE_DIR, "faq.json")
    if os.path.exists(p1):
        return p1

    p2 = os.path.join(os.getcwd(), "faq.json")
    if os.path.exists(p2):
        return p2

    p3 = os.path.join(os.getcwd(), "medical_law_kz_bot", "faq.json")
    if os.path.exists(p3):
        return p3

    return p1


def resolve_exam_path() -> str:
    env_path = os.getenv("EXAM_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    p1 = os.path.join(BASE_DIR, "exam.json")
    if os.path.exists(p1):
        return p1

    p2 = os.path.join(os.getcwd(), "exam.json")
    if os.path.exists(p2):
        return p2

    p3 = os.path.join(os.getcwd(), "medical_law_kz_bot", "exam.json")
    if os.path.exists(p3):
        return p3

    return p1


FAQ_PATH = resolve_faq_path()
EXAM_PATH = resolve_exam_path()

# Клавиатура
menu = ReplyKeyboardMarkup(resize_keyboard=True)
menu.add(KeyboardButton(SECTIONS[0]), KeyboardButton(SECTIONS[1]))
menu.add(KeyboardButton(SECTIONS[2]), KeyboardButton(SECTIONS[3]))
menu.add(KeyboardButton(SECTIONS[4]), KeyboardButton(SECTIONS[5]))
menu.add(KeyboardButton(SECTIONS[6]))
menu.add(KeyboardButton(SECTIONS[7]), KeyboardButton(SECTIONS[8]))


def load_json_list(path: str, label: str) -> List[Dict[str, Any]]:
    try:
        logging.info(f"Loading {label} from: {path}")
        logging.info(f"{label} exists: {os.path.exists(path)}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            logging.warning(f"{label} is not a list. Using empty {label}.")
            return []

        logging.info(f"{label} loaded: {len(data)} entries")
        return data

    except Exception as e:
        logging.exception(f"Failed to load {label}: %s", e)
        try:
            logging.info(f"cwd={os.getcwd()}")
            logging.info(f"listdir(cwd)={os.listdir(os.getcwd())}")
            logging.info(f"listdir(BASE_DIR)={os.listdir(BASE_DIR)}")
        except Exception:
            pass
        return []


FAQ = load_json_list(FAQ_PATH, "FAQ")
EXAM = load_json_list(EXAM_PATH, "EXAM")


def find_answer(user_text: str) -> Optional[Dict[str, Any]]:
    text = (user_text or "").lower()
    best = None
    best_score = 0

    for entry in FAQ:
        keywords = entry.get("keywords") or []
        score = 0
        for kw in keywords:
            if isinstance(kw, str) and kw.lower() in text:
                score += 1
        if score > best_score:
            best_score = score
            best = entry

    return best if best_score > 0 else None


def find_exam_card(user_text: str) -> Optional[Dict[str, Any]]:
    text = (user_text or "").lower()
    best = None
    best_score = 0

    for entry in EXAM:
        keywords = entry.get("keywords") or []
        score = 0
        for kw in keywords:
            if isinstance(kw, str) and kw.lower() in text:
                score += 1
        if score > best_score:
            best_score = score
            best = entry

    return best if best_score > 0 else None


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


# Мини-тесты: включаем exam-режим
@dp.message_handler(lambda m: (m.text or "").strip() == "🧪 Мини-тесты")
async def mini_tests(message: types.Message):
    USER_MODE[message.from_user.id] = "exam"
    await message.answer(
        "🧪 Экзаменационный режим включён.\n\n"
        "Напишите тему или ключевые слова, например:\n"
        "• ответственность\n"
        "• дисциплинарная ответственность\n"
        "• врачебная тайна\n\n"
        "Чтобы выйти из режима — напишите: выход",
        reply_markup=menu,
    )


@dp.message_handler(lambda m: (m.text or "").strip() in SECTIONS)
async def handle_section_buttons(message: types.Message):
    key = (message.text or "").strip()

    entry = next(
        (e for e in FAQ if e.get("section") == key and e.get("type") == "intro"),
        None
    )

    if entry:
        answer = (entry.get("answer") or "").strip()
        law = entry.get("law")

        if law:
            answer += f"\n\n🔷 Нормативная база: {law}"

        answer += f"\n\n{DISCLAIMER}"
        await message.answer(answer, reply_markup=menu)
        return

    await message.answer(
        "Информация по этому разделу пока готовится.\n"
        "Попробуйте задать вопрос текстом (1–2 ключевых слова).",
        reply_markup=menu
    )



# EXAM-режим: ловим ТОЛЬКО когда USER_MODE == "exam"
@dp.message_handler(lambda m: USER_MODE.get(m.from_user.id) == "exam" and m.text and (not (m.text or "").startswith("/")))
async def handle_exam_mode(message: types.Message):
    uid = message.from_user.id
    user_text = (message.text or "").strip()

    if user_text.lower() in ("выход", "выйти", "exit"):
        USER_MODE.pop(uid, None)
        await message.answer("Экзаменационный режим выключён. Можете задавать обычные вопросы.", reply_markup=menu)
        return

    entry = find_exam_card(user_text)
    if not entry:
        await message.answer(
            "По этому запросу экзаменационная карточка не найдена.\n"
            "Попробуйте проще: «ответственность», «дисциплинарная», «уголовная».",
            reply_markup=menu,
        )
        return

    q = (entry.get("question") or "").strip()
    ideal = (entry.get("ideal_answer") or "").strip()
    comment = (entry.get("comment") or "").strip()
    mistake = (entry.get("common_mistake") or "").strip()
    law = (entry.get("law") or "").strip()

    out = f"🎓 Экзаменационная карточка\n\n📌 Вопрос:\n{q}\n\n✅ Эталонный ответ:\n{ideal}"
    if comment:
        out += f"\n\n💡 Комментарий:\n{comment}"
    if mistake:
        out += f"\n\n⚠️ Типичная ошибка:\n{mistake}"
    if law:
        out += f"\n\n🔷 Нормативная база:\n{law}"

    out += f"\n\n{DISCLAIMER}"
    await message.answer(out, reply_markup=menu)


# Обычные текстовые вопросы (FAQ)
@dp.message_handler(lambda m: m.text and (not (m.text or "").startswith("/")) and ((m.text or "").strip() not in SECTIONS))
async def handle_text(message: types.Message):
    user_text = (message.text or "").strip()
    entry = find_answer(user_text)

    if entry:
        answer = (entry.get("answer") or entry.get("a") or "").strip()
        law = entry.get("law")
        if law:
            answer += f"\n\n🔷 Нормативная база: {law}"
        answer += f"\n\n{DISCLAIMER}"
        await message.answer(answer, reply_markup=menu)
        return

    await message.answer(
        "Не нашёл точного ответа в базе знаний.\n"
        "Попробуйте переформулировать вопрос проще (1–2 ключевых слова) "
        "или нажмите «✉️ Задать вопрос преподавателю».",
        reply_markup=menu,
    )


@dp.errors_handler()
async def global_error_handler(update, exception):
    logging.exception("Update caused error: %s", exception)
    return True


if __name__ == "__main__":
    logging.info("BOT STARTED OK")
    executor.start_polling(dp, skip_updates=True)
