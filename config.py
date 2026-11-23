"""Sozlamalar (muhit o'zgaruvchilari). Boshqa hammasi — Mini App ichidagi admin panelda."""
import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.strip().isdigit()}
WEBAPP_URL = os.getenv("WEBAPP_URL") or os.getenv("RENDER_EXTERNAL_URL", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "")          # @siz; bo'sh bo'lsa bot o'zi aniqlaydi
DB_PATH = os.getenv("DB_PATH", "kinobot.sqlite3")
PORT = int(os.getenv("PORT", "8080"))
AUTH_MAX_AGE = 3 * 24 * 3600
# Ixtiyoriy: o'z Bot API serveri (telegram-bot-api --local). U bilan katta (20 MB dan ortiq) kinolarni ham Mini App ichida ko'rsatish mumkin.
BOT_API_URL = os.getenv("BOT_API_URL", "").rstrip("/")      # masalan http://127.0.0.1:8081
