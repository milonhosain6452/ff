import threading
from telethon import TelegramClient, events
from flask import Flask

# ====== Your Credentials ======
API_ID = 28179017
API_HASH = "3eccbcc092d1a95e5c633913bfe0d9e9"
BOT_TOKEN = "8080322939:AAG6sVck-WSdRFkPNJfBRe9-MGQwpO71kkM"
# ==============================

# Create Flask server (Render requires this)
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

# Telegram Bot Client
bot = TelegramClient("bot_session", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# Bot Command
@bot.on(events.NewMessage(pattern="/start"))
async def start_cmd(event):
    await event.reply("How can I help you?")

def run_bot():
    print("Bot started (Telethon)...")
    bot.run_until_disconnected()

def run_flask():
    print("Flask server running...")
    app.run(host="0.0.0.0", port=10000)   # Render auto-detects this port

# Run both Flask + Bot
if __name__ == "__main__":
    threading.Thread(target=run_bot).start()
    run_flask()
