import os
import logging
import random
from typing import Dict, Any

import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

"""
Telegram Bot: Оценка фильмов через ИИ-прокси

Функции:
- Команда /rate <название> — запрашивает у ИИ:
  - рейтинг IMDb и Кинопоиска (если найдены), с ссылками (если уверен)
  - год, оригинальное название
  - краткое описание и вердикт (интересный / стоит посмотреть / не стоит смотреть)
- Если фильм\сериал не найден — бот сообщает об этом и предлагает для разнообразия фильм с очень низким рейтингом (< 3).
- /start, /help — инструкция

Конфигурация через переменные окружения:
- TELEGRAM_BOT_TOKEN (обязательно) — токен Telegram бота от @BotFather
- PROXYAPI_KEY      (обязательно) — ключ прокси, используется как Bearer
- AI_BASE_URL       (опционально) — базовый URL, по умолчанию https://openai.api.proxyapi.ru/v1
- AI_MODEL          (опционально) — модель, по умолчанию anthropic/claude-sonnet-4-20250514
- AI_LANGUAGE       (опционально) — язык ответа (ru по умолчанию)
"""

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s [%(name)s] %(message)s')
logger = logging.getLogger("kaino_bot")


class AICompletionsService:
    def __init__(self, base_url: str, api_key: str, model: str, language: str = "ru"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.language = language
        self.session = requests.Session()

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_prompt_for_rating(self, title: str) -> Dict[str, Any]:
        system_msg = (
            "Вы — помощник-киновед. Ваша задача — найти и выдать пользователю аккуратную сводку по фильму или по сериалу. "
            f"Язык ответа — {self.language}. Строго соблюдайте формат ответа. "
            "Если не удаётся однозначно сопоставить фильм или сериал по названию — верните строго 'NOT_FOUND'."
        )
        user_msg = (
            "Название: " + title + "\n\n"
            "Нужно:")
        # Жесткие требования к формату, чтобы ответ был кратким и структурированным
        format_requirements = (
            "Формат ответа (на русском):\n"
            "Название: <локализованное название или 'не найдено'>\n"
            "Оригинальное название: <или 'не найдено'>\n"
            "Год: <или 'не найдено'>\n"
            "Рейтинги:\n"
            "  - IMDb: <оценка/10 или 'не найдено'> <ссылка если уверены>\n"
            "  - Кинопоиск: <оценка/10 или 'не найдено'> <ссылка если уверены>\n"
            "Кратко: <1–2 предложения, без спойлеров>\n"
            "Вердикт: <кратко �� по делу: 'интересный', 'стоит посмотреть', 'скорее не стоит' и т.п.>\n"
            "Правила:\n"
            "- Указывайте ссылки на IMDb и Кинопоиск только если уверены в корректности.\n"
            "- Если уверенности нет — ссылку не показывайте.\n"
            "- Если фильм не найден или невозможно уверенно сопоставить его, верните строго строку NOT_FOUND (без форматирования и комментариев).\n"
            "- Не добавляйте ничего, кроме указанного формата.\n"
        )
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg + "\n\n" + format_requirements},
            ],
            "temperature": 0.2,
        }

    def fetch_movie_rating_text(self, title: str) -> Dict[str, Any]:
        url = f"{self.base_url}/chat/completions"
        payload = self._build_prompt_for_rating(title)
        try:
            resp = self.session.post(url, headers=self._headers(), json=payload, timeout=40)
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices")
            if isinstance(choices, list) and choices:
                msg = choices[0].get("message") or {}
                content = msg.get("content") or ""
                if content.strip():
                    return {"ok": True, "text": content.strip()}
            return {"ok": False, "error": "Пустой ответ от ИИ"}
        except requests.HTTPError as e:
            try:
                err = e.response.json()
            except Exception:
                err = e.response.text if e.response is not None else str(e)
            logger.error("HTTP error from AI proxy: %s", err)
            return {"ok": False, "error": f"HTTP error: {err}"}
        except Exception as e:
            logger.exception("Error calling AI proxy")
            return {"ok": False, "error": str(e)}


def require_config() -> Dict[str, Any]:
    cfg = {
        "TELEGRAM_BOT_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN"),
        "PROXYAPI_KEY": os.getenv("PROXYAPI_KEY"),
        "AI_BASE_URL": os.getenv("AI_BASE_URL", "https://openai.api.proxyapi.ru/v1"),
        "AI_MODEL": os.getenv("AI_MODEL", "anthropic/claude-sonnet-4-20250514"),
        "AI_LANGUAGE": os.getenv("AI_LANGUAGE", "ru"),
    }
    missing = [k for k in ("TELEGRAM_BOT_TOKEN", "PROXYAPI_KEY") if not cfg.get(k)]
    if missing:
        logger.error("Missing required environment variables: %s", ", ".join(missing))
        logger.error("Set them, for example (Windows PowerShell):")
        logger.error("$env:TELEGRAM_BOT_TOKEN='YOUR_TOKEN_HERE'")
        logger.error("$env:PROXYAPI_KEY='YOUR_PROXYAPI_KEY_HERE'")
    return cfg


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = (
        "Используйте команду:\n"
        "/rate <название фильма>\n\n"
        "Я верну рейтинги IMDb и Кинопоиска, краткое описание и лаконичный вердикт.\n"
        "Если фильм не найден — сообщу об этом и посоветую 'что-нибудь очень плохое' (рейтинг < 3)."
    )
    await context.bot.send_message(chat_id=update.effective_chat.id, text=msg)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


async def cmd_rate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = context.application.bot_data.get("cfg")
    ai_service: AICompletionsService = context.application.bot_data.get("ai_service")
    title = " ".join(context.args or []).strip()
    if not title:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Укажите название фильма: /rate Название фильма",
        )
        return

    result = ai_service.fetch_movie_rating_text(title)
    text = (result.get("text") or "").strip()
    if result.get("ok") and text and text.upper() != "NOT_FOUND":
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text, disable_web_page_preview=False)
    elif result.get("ok"):
        # Фильм не найден — отправляем уведомление и совет с фильмом с очень низким рейтингом (<3)
        suggestions = [
            ("Birdemic: Shock and Terror", 1.8),
            ("Disaster Movie", 2.0),
            ("Superbabies: Baby Geniuses 2", 1.9),
            ("Manos: The Hands of Fate", 1.6),
            ("Troll 2", 2.9),
        ]
        name, rating = random.choice(suggestions)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=(
                f"Фильм по запросу \"{title}\" не найден.\n"
                f"Совет: попробуйте что-то для разнообразия — \"{name}\" (рейтинг {rating}/10 < 3)."
            ),
            disable_web_page_preview=False,
        )
    else:
        err = result.get("error", "unknown")
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Ошибка: {err}")


async def on_startup(app: Application) -> None:
    logger.info("Bot started.")


def main() -> None:
    cfg = require_config()
    if not cfg.get("TELEGRAM_BOT_TOKEN") or not cfg.get("PROXYAPI_KEY"):
        logger.error("Cannot start without required configuration.")
        return

    ai_service = AICompletionsService(
        base_url=cfg["AI_BASE_URL"],
        api_key=cfg["PROXYAPI_KEY"],
        model=cfg["AI_MODEL"],
        language=cfg["AI_LANGUAGE"],
    )

    application = Application.builder().token(cfg["TELEGRAM_BOT_TOKEN"]).build()

    # Attach config and services to application
    application.bot_data["cfg"] = cfg
    application.bot_data["ai_service"] = ai_service

    # Handlers
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("rate", cmd_rate))

    application.post_init = on_startup

    logger.info("Starting polling...")
    application.run_polling(allowed_updates=None, close_loop=False)


if __name__ == "__main__":
    main()
