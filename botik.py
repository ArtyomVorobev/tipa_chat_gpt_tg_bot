import logging
import requests
import redis
import json
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Логирование
logging.basicConfig(level=logging.INFO)

import os
from dotenv import load_dotenv
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
MISTRAL_ENDPOINT = "https://api.mistral.ai/v1/chat/completions"

# --- Redis ---
r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

# --- Вспомогательные функции ---
def get_history(user_id):
    data = r.get(f"history:{user_id}")
    return json.loads(data) if data else []


def save_history(user_id, history):
    r.set(f"history:{user_id}", json.dumps(history))


def clear_history(user_id):
    r.delete(f"history:{user_id}")


def mistral_reply(messages):
    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "mistral-tiny",  # можно заменить
        "messages": messages
    }
    resp = requests.post(MISTRAL_ENDPOINT, headers=headers, json=payload, timeout=60)
    data = resp.json()
    return data["choices"][0]["message"]["content"]


# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот с LLM. Напиши /new чтобы начать новый диалог или просто задай вопрос.\n"
        "Команды:\n/new — начать новый диалог\n/help — помощь"
    )


async def new_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_history(update.message.from_user.id)
    await update.message.reply_text("Новый диалог начат. Напиши свой вопрос:")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Я пересылаю твои сообщения в LLM и возвращаю ответы.\n"
        "/new — начать новый диалог (очистить историю)\n"
        "/help — показать справку"
    )


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text

    history = get_history(user_id)
    history.append({"role": "user", "content": text})
    save_history(user_id, history)

    # Показать индикатор набора текста
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    # Сообщение-заглушка
    thinking_msg = await update.message.reply_text("🤔 Думаю над ответом…")

    try:
        reply = mistral_reply(history)
    except Exception as e:
        logging.error(e)
        await thinking_msg.edit_text("⚠️ Ошибка при обращении к API.")
        return

    history.append({"role": "assistant", "content": reply})
    save_history(user_id, history)

    await thinking_msg.edit_text(reply)


# --- Main ---
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("new", new_dialog))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    app.run_polling()


if __name__ == "__main__":
    main()
