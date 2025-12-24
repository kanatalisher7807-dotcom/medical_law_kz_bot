import os
import json
import logging
from typing import Optional, Dict, Any, List

from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

logging.basicConfig(level=logging.INFO)

# ====== ENV ======
TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN is not set.")

# Путь к faq.json — всегда рядом с bot.py (на Render/Docker это важно)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FAQ_PATH = os.getenv("FAQ_PATH", os.path.join(BASE_DIR, "faq.json"))

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

# Что именно “подставлять” в поиск по FAQ при нажатии кнопки
SECTION_TO_QUERY = {
    "⚖️ Медицинские ошибки": "медицинская ошибка",
    "🚨 Инциденты": "инцидент",
    "🏥 Жалобы пациента": "жалоба",
    "✍️ Информированное согласие": "информированное согласие",
    "🔒 Врачебная тайна": "врачебная тайна",
    "👮 Ответственность медработников": "ответственность",
}

# ====== MENU ======
menu = ReplyKeyboardMarkup(resize_keyboard=True)
menu.add(KeyboardButton(SECTIONS[0]), KeyboardButton(SECTIONS[1]))
menu.add(KeyboardButton(SECTIONS[2]), KeyboardButton(SECTIONS[3]))
menu.add(KeyboardButton(SECTIONS[4]), KeyboardButton(SECTIONS[5]))
menu.add(KeyboardButton(SECTIONS[6]))
menu.add(KeyboardButton(SECTIONS[7]), KeyboardButton(SECTIONS[8]))

# ====== FAQ ======
FAQ: List[Dict[str, Any]] = []

def load_faq() -> List[Dict[str, Any]]:
    try:
        with open(FAQ_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            logging.error("faq.json is not a list. Got: %s", type(data))
            return []
        return data
    except Exception as e:
        logging.exception("Failed to load FAQ from %s: %s", FAQ_PATH, e)
        return []

def reload_faq() -> int:
    global FAQ
    FAQ = load_faq()
    logging.info("FAQ loaded: %d entries (path=%s)", len(FAQ), FAQ_PATH)
    return len(FAQ)

def find_answer(user_text: str) -> Optional[Dict[str, Any]]:
    text = (user_text or "").lower().strip()
    if not text:
        return None

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

# Загружаем при старте
reload_faq()

# ====== BOT ======
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

# Тех-команды для проверки
@dp.message_handler(commands=["faqcount"])
async def faqcount(message: types.Message):
    await message.answer(f"FAQ записей: {len(FAQ)}", reply_markup=menu)

@dp.message_handler(commands=["reload"])
async def reload_cmd(message: types.Message):
    n = reload_faq()
    await message.answer(f"Перезагрузил FAQ: {n} записей.", reply_markup=menu)

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
    await message.answer(
        "Мини-тесты подключим на следующем шаге.\n"
        "Пока можете написать вопрос текстом — я отвечу по базе знаний.",
        reply_markup=menu
    )

# Кнопки-разделы (кроме Нормативной базы / Вопрос преподавателю / Мини-тестов)
@dp.message_handler(lambda m: (m.text or "").strip() in SECTION_TO_QUERY)
async def handle_section_buttons(message: types.Message):
    key = (message.text or "").strip()
    query = SECTION_TO_QUERY.get(key, "")

   entry = next(
    (e for e in FAQ if e.get("section") == key),
    None
)
    if entry:
        answer = (entry.get("answer") or entry.get("a") or "").strip()
        law = entry.get("law")

        if law:
            answer += f"\n\n🔷 Нормативная база: {law}"

        answer += f"\n\n{DISCLAIMER}"
        await message.answer(answer, reply_markup=menu)
        return

    await message.answer(
        "Информация по этому разделу пока не найдена в базе.\n"
        "Попробуйте задать вопрос текстом (1–2 ключевых слова).",
        reply_markup=menu
    )

# Любой текст (кроме команд и кроме нажатий кнопок меню)
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
        reply_markup=menu
    )

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
