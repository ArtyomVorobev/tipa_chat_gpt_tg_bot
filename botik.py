import logging
import requests
import redis
import json
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import os
from dotenv import load_dotenv

# Логирование
logging.basicConfig(level=logging.INFO)

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY_CHAT = os.getenv("OPENAI_API_KEY_CHAT")
OPENAI_API_KEY_SUMMARIZE = os.getenv("OPENAI_API_KEY_SUMMARIZE")

MISTRAL_ENDPOINT = "https://api.mistral.ai/v1/chat/completions"
MAX_CONTEXT_LEN = 6

# --- Redis ---
r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

class ClientChatBot:
    def __init__(self, chat_model, summarize_model):
        # Для чата
        self.chat_headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY_CHAT}",
            "Content-Type": "application/json"
        }
        self.chat_model = chat_model

        # Для саммари
        self.summarize_headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY_SUMMARIZE}",
            "Content-Type": "application/json"
        }
        self.summarize_model = summarize_model

    def summarize_context(self, user_context): 
        summarize_prompt = self._get_summarize_prompt(user_context)
        summarize_payload = {
            "model": self.summarize_model,
            "messages": summarize_prompt
        }
        resp = requests.post(MISTRAL_ENDPOINT, headers=self.summarize_headers, json=summarize_payload, timeout=60)
        data = resp.json()
        summary = data["choices"][0]["message"]["content"]
        return [{"role": "system", "content": f"Summary of previous dialogue: {summary}"}]

    def _get_summarize_prompt(self, context):
        summary_prompt = [
            {"role": "system", "content": "You are a conversation summarizer."},
            {"role": "user", "content": f"Summarize the following conversation briefly, keeping only the essential facts:\n\n{context}"}
        ]
        return summary_prompt

    def chat(self, user_input):
        chat_payload = {
            "model": self.chat_model,
            "messages": user_input
        }
        resp = requests.post(MISTRAL_ENDPOINT, headers=self.chat_headers, json=chat_payload, timeout=60)
        reply = resp.json()
        return reply["choices"][0]["message"]["content"]

chat_bot = ClientChatBot(
    chat_model="mistral-tiny",
    summarize_model="mistral-tiny",
)

# --- Вспомогательные функции ---
def get_history(user_id):
    data = r.get(f"history:{user_id}")
    return json.loads(data) if data else []

def save_history(user_id, history):
    r.set(f"history:{user_id}", json.dumps(history, ensure_ascii=False))

def clear_history(user_id):
    r.delete(f"history:{user_id}")

def mistral_reply(messages):
    return chat_bot.chat(messages)

def summarize_history(history):
    return chat_bot.summarize_context(history)

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

    if len(history) >= MAX_CONTEXT_LEN:
        history = summarize_history(history)

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
