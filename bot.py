from telethon import TelegramClient, events

# ====== Your Credentials ======
API_ID = 28179017
API_HASH = "3eccbcc092d1a95e5c633913bfe0d9e9"
BOT_TOKEN = "8080322939:AAG6sVck-WSdRFkPNJfBRe9-MGQwpO71kkM"
# ==============================

# Create bot client
bot = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# /start command
@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    await event.reply("How can I help you?")

print("Bot is running...")
bot.run_until_disconnected()
