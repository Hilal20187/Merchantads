import os
import asyncio
import logging
import threading

from telethon import TelegramClient, events
from flask import Flask

# ============================================================
# CONFIG
# ============================================================

API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

AUTHORIZED_USER_IDS = {
    822007358,
    2065539959,
}

ADMIN_GROUP_ID = -1003963584914

TARGET_GROUP_IDS = [
    -1003952714985,
    -1002470205630,
    -1004407777777,  # <-- بدّل هذا بالـ ID الصحيح للمجموعة الثالثة
]

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("LEX-BOT")


# ============================================================
# CHECK VARIABLES
# ============================================================

if API_ID == 0:
    raise RuntimeError("API_ID غير موجود في Railway Variables")

if not API_HASH:
    raise RuntimeError("API_HASH غير موجود في Railway Variables")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN غير موجود في Railway Variables")


# ============================================================
# TELEGRAM CLIENT
# ============================================================

client = TelegramClient(
    "lex_bot",
    API_ID,
    API_HASH
)


# ============================================================
# MESSAGE HANDLER
# ============================================================

@client.on(events.NewMessage)
async def handle_message(event):

    try:

        sender = await event.get_sender()

        if not sender:
            return

        # فقط الأشخاص المسموح لهم
        if sender.id not in AUTHORIZED_USER_IDS:
            return

        text = (event.raw_text or "").strip()

        # ====================================================
        # DELETE COMMAND
        # ====================================================

        if text.startswith("/del"):

            try:

                if event.is_reply:

                    reply = await event.get_reply_message()

                    if reply:
                        await reply.delete()

                await event.delete()

                logger.info(
                    "DEL executed by user %s",
                    sender.id
                )

            except Exception as e:

                logger.error(
                    "DEL ERROR: %s",
                    e
                )

            return

        # ====================================================
        # GET CHAT
        # ====================================================

        chat = await event.get_chat()

        if not chat:
            return

        # ====================================================
        # ONLY ADMIN GROUP
        # ====================================================

        if chat.id != ADMIN_GROUP_ID:
            return

        logger.info(
            "Publication received from %s",
            sender.id
        )

        # ====================================================
        # PUBLISH
        # ====================================================

        for group_id in TARGET_GROUP_IDS:

            try:

                await client.send_message(
                    entity=group_id,
                    message=event.message
                )

                logger.info(
                    "Published -> %s",
                    group_id
                )

            except Exception as e:

                logger.error(
                    "Publish failed -> %s | %s",
                    group_id,
                    e
                )

    except Exception as e:

        logger.exception(
            "MESSAGE HANDLER ERROR: %s",
            e
        )


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


@app.route("/")
def home():

    return "LEX Telegram Publisher is running."


@app.route("/health")
def health():

    return "OK"


# ============================================================
# BOT
# ============================================================

def run_bot():

    async def start_bot():

        await client.start(
            bot_token=BOT_TOKEN
        )

        me = await client.get_me()

        logger.info("==============================")
        logger.info("LEX BOT STARTED")
        logger.info("BOT ID: %s", me.id)
        logger.info("BOT USERNAME: @%s", me.username)
        logger.info("ADMIN GROUP: %s", ADMIN_GROUP_ID)
        logger.info("TARGETS: %s", TARGET_GROUP_IDS)
        logger.info("AUTHORIZED: %s", list(AUTHORIZED_USER_IDS))
        logger.info("==============================")

        await client.run_until_disconnected()

    asyncio.run(start_bot())


# ============================================================
# WEB SERVER
# ============================================================

def run_server():

    port = int(
        os.environ.get("PORT", "8080")
    )

    app.run(
        host="0.0.0.0",
        port=port,
        use_reloader=False
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    bot_thread = threading.Thread(
        target=run_bot,
        daemon=True
    )

    bot_thread.start()

    run_server()
