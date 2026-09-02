import os
import asyncio
import logging
import sqlite3

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, RPCError
from telethon.tl.types import Message
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# CONFIG
# ============================================================

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

DB_FILE = os.getenv("DB_FILE", "lex_publisher.db")

SOURCE = int(
    os.getenv(
        "SOURCE",
        "-1004333211848"
    )
)

TARGETS_STRING = os.getenv(
    "TARGETS",
    "-1004407774851,-1002470205630,-1001869395971,-1003952714985,-1003026306104"
)

TARGETS = [
    int(x.strip())
    for x in TARGETS_STRING.split(",")
    if x.strip()
]

OWNER_IDS_STRING = os.getenv("OWNER_IDS", "")

OWNER_IDS = {
    int(x.strip())
    for x in OWNER_IDS_STRING.split(",")
    if x.strip()
}

# ============================================================
# LOG
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("LEX")

# ============================================================
# DATABASE
# ============================================================

db = sqlite3.connect(
    DB_FILE,
    check_same_thread=False
)

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
        (
            target_chat,
            target_msg
        )
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
        (
            source_chat,
            source_msg
        )
    ).fetchall()


def delete_records(source_chat, source_msg):

    db.execute(
        """
        DELETE FROM published
        WHERE source_chat = ?
        AND source_msg = ?
        """,
        (
            source_chat,
            source_msg
        )
    )

    db.commit()


# ============================================================
# TELEGRAM
# ============================================================

client = TelegramClient(
    "merchantads_bot",
    API_ID,
    API_HASH
)


# ============================================================
# CHECK OWNER
# ============================================================

async def is_allowed(event):

    if not OWNER_IDS:
        return False

    sender = await event.get_sender()

    if not sender:
        return False

    return sender.id in OWNER_IDS


# ============================================================
# COPY MESSAGE FUNCTION (بدون Forward)
# ============================================================

async def copy_message_without_forward(message, target):
    """
    تنسخ الرسالة بدون علامة Forwarded from
    """
    try:
        # الحصول على نص الرسالة
        text = message.text or message.caption or ""
        
        # التحقق من الرابط (إذا كان الرسالة موجودة فقط)
        if message.web_preview:
            # إذا كانت الرسالة تحتوي على رابط بمعاينة
            result = await client.send_message(
                entity=target,
                message=text,
                link_preview=True
            )
        elif message.media:
            # إذا كانت الرسالة تحتوي على وسائط (صور، فيديو، إلخ)
            result = await client.send_file(
                entity=target,
                file=message.media,
                caption=text
            )
        else:
            # رسالة نصية فقط
            result = await client.send_message(
                entity=target,
                message=text
            )
        
        return result

    except Exception as e:
        log.error("Error copying message: %s", e)
        return None


# ============================================================
# PUBLISH
# ============================================================

@client.on(events.NewMessage(chats=SOURCE))
async def publish_message(event):

    message = event.message

    # تجاهل أوامر /del
    if message.raw_text:

        text = message.raw_text.strip().lower()

        if text.startswith("/del"):
            return

    # تجاهل service messages
    if message.action:
        return

    log.info(
        "NEW MESSAGE | SOURCE=%s | MESSAGE=%s",
        SOURCE,
        message.id
    )

    for target in TARGETS:

        try:

            # نسخ الرسالة بدون Forward
            copied_message = await copy_message_without_forward(message, target)

            if not copied_message:
                continue

            save_copy(
                SOURCE,
                message.id,
                target,
                copied_message.id
            )

            log.info(
                "PUBLISHED | %s -> %s | %s -> %s",
                SOURCE,
                target,
                message.id,
                copied_message.id
            )

        except FloodWaitError as e:

            log.warning(
                "FloodWait: %s seconds",
                e.seconds
            )

            await asyncio.sleep(e.seconds)

        except RPCError as e:

            log.error(
                "Telegram error TARGET=%s : %s",
                target,
                e
            )

        except Exception as e:

            log.exception(
                "Publish error TARGET=%s : %s",
                target,
                e
            )


# ============================================================
# DELETE
# ============================================================

@client.on(
    events.NewMessage(
        pattern=r"^/del"
    )
)
async def delete_command(event):

    # ========================================================
    # OWNER ONLY
    # ========================================================

    if not await is_allowed(event):

        try:
            await event.delete()
        except Exception:
            pass

        return

    # ========================================================
    # لازم REPLY
    # ========================================================

    if not event.is_reply:

        await event.reply(
            "⚠️ لازم تدير Reply على المنشور ثم تكتب /del"
        )

        return

    replied = await event.get_reply_message()

    if not replied:

        await event.reply(
            "❌ لم أجد الرسالة."
        )

        return

    current_chat = event.chat_id
    current_message = replied.id

    source_chat = None
    source_message = None

    # ========================================================
    # إذا Reply على SOURCE
    # ========================================================

    if current_chat == SOURCE:

        source_chat = SOURCE
        source_message = current_message

    # ========================================================
    # إذا Reply على TARGET
    # ========================================================

    else:

        found = get_source_from_target(
            current_chat,
            current_message
        )

        if found:

            source_chat, source_message = found

    # ========================================================
    # غير معروف
    # ========================================================

    if source_chat is None:

        await event.reply(
            "❌ هذا المنشور غير مسجل عند البوت."
        )

        return

    log.info(
        "DELETE | SOURCE=%s | MESSAGE=%s",
        source_chat,
        source_message
    )

    # ========================================================
    # حذف الأصل من SOURCE
    # ========================================================

    try:

        await client.delete_messages(
            source_chat,
            source_message
        )

        log.info("SOURCE MESSAGE DELETED")

    except Exception as e:

        log.error(
            "SOURCE DELETE ERROR: %s",
            e
        )

    # ========================================================
    # جلب النسخ
    # ========================================================

    copies = get_copies(
        source_chat,
        source_message
    )

    # ========================================================
    # حذف النسخ من جميع TARGETS
    # ========================================================

    for target_chat, target_message in copies:

        try:

            await client.delete_messages(
                target_chat,
                target_message
            )

            log.info(
                "COPY DELETED | %s | %s",
                target_chat,
                target_message
            )

        except Exception as e:

            log.error(
                "COPY DELETE ERROR | %s | %s | %s",
                target_chat,
                target_message,
                e
            )

    # ========================================================
    # حذف سجل DB
    # ========================================================

    delete_records(
        source_chat,
        source_message
    )

    # ========================================================
    # حذف أمر /del من جميع الأماكن
    # ========================================================

    try:
        await event.delete()
    except Exception:
        pass

    # حذف الرد إذا كان موجود
    try:
        await replied.delete()
    except Exception:
        pass

    log.info("DELETE COMPLETE")


# ============================================================
# START
# ============================================================

async def main():

    log.info("===================================")
    log.info("LEX MERCHANT ADS")
    log.info("===================================")

    log.info("SOURCE  : %s", SOURCE)
    log.info("TARGETS : %s", TARGETS)
    log.info("OWNERS  : %s", OWNER_IDS)

    await client.start(
        bot_token=BOT_TOKEN
    )

    me = await client.get_me()

    log.info(
        "BOT STARTED: @%s | ID=%s",
        me.username,
        me.id
    )

    log.info("BOT IS RUNNING")

    await client.run_until_disconnected()


if __name__ == "__main__":

    asyncio.run(main())
 
