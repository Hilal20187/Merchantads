import os
import asyncio
import logging
import sqlite3

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, RPCError
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# CONFIG
# ============================================================

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

DB_FILE = os.getenv("DB_FILE", "lex_publisher.db")

# المجموعة الأصلية
SOURCE = int(os.environ["SOURCE"])

# المجموعات المستهدفة
TARGETS = [
    int(x.strip())
    for x in os.environ["TARGETS"].split(",")
    if x.strip()
]

# IDs المسموح لهم باستعمال /del
# مثال:
# OWNER_IDS=123456789,987654321
OWNER_IDS = {
    int(x.strip())
    for x in os.getenv("OWNER_IDS", "").split(",")
    if x.strip()
}

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("LEX")

# ============================================================
# DATABASE
# ============================================================

db = sqlite3.connect(DB_FILE, check_same_thread=False)
db.execute("""
CREATE TABLE IF NOT EXISTS published (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_chat INTEGER NOT NULL,
    source_msg INTEGER NOT NULL,
    target_chat INTEGER NOT NULL,
    target_msg INTEGER NOT NULL
)
""")

db.execute("""
CREATE INDEX IF NOT EXISTS idx_source
ON published(source_chat, source_msg)
""")

db.execute("""
CREATE INDEX IF NOT EXISTS idx_target
ON published(target_chat, target_msg)
""")

db.commit()


def save_copy(source_chat, source_msg, target_chat, target_msg):
    db.execute(
        """
        INSERT INTO published
        (source_chat, source_msg, target_chat, target_msg)
        VALUES (?, ?, ?, ?)
        """,
        (
            source_chat,
            source_msg,
            target_chat,
            target_msg
        )
    )
    db.commit()


def get_source_from_target(target_chat, target_msg):
    row = db.execute(
        """
        SELECT source_chat, source_msg
        FROM published
        WHERE target_chat = ?
        AND target_msg = ?
        LIMIT 1
        """,
        (target_chat, target_msg)
    ).fetchone()

    return row


def get_copies(source_chat, source_msg):
    return db.execute(
        """
        SELECT target_chat, target_msg
        FROM published
        WHERE source_chat = ?
        AND source_msg = ?
        """,
        (source_chat, source_msg)
    ).fetchall()


def delete_records(source_chat, source_msg):
    db.execute(
        """
        DELETE FROM published
        WHERE source_chat = ?
        AND source_msg = ?
        """,
        (source_chat, source_msg)
    )
    db.commit()


# ============================================================
# TELEGRAM CLIENT
# ============================================================

client = TelegramClient(
    "merchantads_bot",
    API_ID,
    API_HASH
)


# ============================================================
# PERMISSION
# ============================================================

async def is_allowed(event):
    """
    فقط OWNER_IDS يقدر يستعمل /del.
    """

    if not OWNER_IDS:
        return False

    sender = await event.get_sender()

    if not sender:
        return False

    return sender.id in OWNER_IDS


# ============================================================
# AUTO PUBLISH
# ============================================================

@client.on(events.NewMessage(chats=SOURCE))
async def publish_message(event):

    message = event.message

    # لا تنشر أوامر البوت
    if message.raw_text:
        text = message.raw_text.strip().lower()

        if text.startswith("/del"):
            return

    # تجاهل رسائل الخدمة
    if message.action:
        return

    log.info(
        "NEW MESSAGE | source=%s | msg=%s",
        SOURCE,
        message.id
    )

    for target in TARGETS:

        try:

            # Forward للرسالة
            result = await client.forward_messages(
                entity=target,
                messages=message,
                from_peer=SOURCE
            )

            # Telethon يرجع Message أو list
            if isinstance(result, list):
                if result:
                    target_message = result[0]
                else:
                    continue
            else:
                target_message = result

            save_copy(
                SOURCE,
                message.id,
                target,
                target_message.id
            )

            log.info(
                "PUBLISHED | %s -> %s | %s -> %s",
                SOURCE,
                target,
                message.id,
                target_message.id
            )

        except FloodWaitError as e:

            log.warning(
                "FloodWait: sleeping %s seconds",
                e.seconds
            )

            await asyncio.sleep(e.seconds)

        except RPCError as e:

            log.error(
                "Telegram error target=%s: %s",
                target,
                e
            )

        except Exception as e:

            log.exception(
                "Publish error target=%s: %s",
                target,
                e
            )


# ============================================================
# DELETE COMMAND
# ============================================================

@client.on(events.NewMessage(pattern=r"^/del(?:@\w+)?$", chats=None))
async def delete_command(event):

    # تحقق من صاحب الأمر
    if not await is_allowed(event):

        await event.reply(
            "❌ ما عندكش صلاحية استعمال /del"
        )

        return

    # لازم Reply
    if not event.is_reply:

        await event.reply(
            "⚠️ دير Reply على المنشور اللي حاب تحذفو ثم اكتب:\n\n"
            "/del"
        )

        return

    replied = await event.get_reply_message()

    if not replied:

        await event.reply(
            "❌ ما قدرتش نلقى الرسالة."
        )

        return

    current_chat = event.chat_id
    current_msg = replied.id

    source_chat = None
    source_msg = None

    # ========================================================
    # الحالة 1:
    # Reply على المنشور الأصلي في SOURCE
    # ========================================================

    if current_chat == SOURCE:

        source_chat = SOURCE
        source_msg = current_msg

    # ========================================================
    # الحالة 2:
    # Reply على نسخة منشورة في TARGET
    # ========================================================

    else:

        found = get_source_from_target(
            current_chat,
            current_msg
        )

        if found:

            source_chat, source_msg = found

    # ========================================================
    # إذا ما لقيناش المنشور
    # ========================================================

    if source_chat is None:

        await event.reply(
            "❌ هذي الرسالة ما عندهاش نسخة مسجلة عند البوت."
        )

        return

    log.info(
        "DELETE REQUEST | source=%s | msg=%s",
        source_chat,
        source_msg
    )

    # ========================================================
    # حذف الأصل
    # ========================================================

    try:

        await client.delete_messages(
            source_chat,
            source_msg
        )

        log.info(
            "DELETED SOURCE | %s | %s",
            source_chat,
            source_msg
        )

    except Exception as e:

        log.error(
            "Could not delete source: %s",
            e
        )

    # ========================================================
    # جلب النسخ
    # ========================================================

    copies = get_copies(
        source_chat,
        source_msg
    )

    deleted = 0

    # ========================================================
    # حذف جميع النسخ
    # ========================================================

    for target_chat, target_msg in copies:

        try:

            await client.delete_messages(
                target_chat,
                target_msg
            )

            deleted += 1

            log.info(
                "DELETED COPY | %s | %s",
                target_chat,
                target_msg
            )

        except Exception as e:

            log.error(
                "Could not delete copy %s/%s: %s",
                target_chat,
                target_msg,
                e
            )

    # ========================================================
    # حذف معلومات SQLite
    # ========================================================

    delete_records(
        source_chat,
        source_msg
    )

    # ========================================================
    # حذف أمر /del نفسه
    # ========================================================

    try:

        await event.delete()

    except Exception:
        pass

    log.info(
        "DELETE COMPLETE | source=%s | msg=%s | copies=%s",
        source_chat,
        source_msg,
        deleted
    )


# ============================================================
# START
# ============================================================

async def main():

    log.info("========================================")
    log.info("LEX MERCHANT ADS BOT")
    log.info("========================================")

    log.info("SOURCE: %s", SOURCE)
    log.info("TARGETS: %s", TARGETS)
    log.info("OWNER_IDS: %s", OWNER_IDS)

    await client.start(
        bot_token=BOT_TOKEN
    )

    me = await client.get_me()

    log.info(
        "BOT STARTED: @%s (%s)",
        me.username,
        me.id
    )

    log.info("Bot is running...")

    await client.run_until_disconnected()


if __name__ == "__main__":

    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        log.info("Bot stopped.")
