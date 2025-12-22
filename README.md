# medical_law_kz_bot

Telegram-бот кафедры медицинского права (MVP) для Render.

## Что делает
- Показывает меню разделов
- Отвечает на типовые вопросы по базе знаний `faq.json` (по ключевым словам)

## Переменные окружения (Render → Environment)
- `TELEGRAM_TOKEN` — токен бота от @BotFather
- `FAQ_PATH` — путь к базе знаний (по умолчанию `faq.json`)

## Render (Background Worker)
- Build Command: `pip install -r requirements.txt`
- Start Command: `python bot.py`
