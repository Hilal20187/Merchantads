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

try:
    API_ID = int(os.environ.get("API_ID", "0"))
    API_HASH = os.environ.get("API_HASH", "")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    
    if not API_ID or not API_HASH or not BOT_TOKEN:
        raise ValueError("API_ID, API_HASH, and BOT_TOKEN are required!")
        
except Exception as e:
    print(f"ERROR: Configuration missing - {e}")
    exit(1)

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
    """تنسخ الرسالة بدون علامة Forwarded from"""
    try:
        text = message.text or message.caption or ""
        
        if message.media:
            result = await client.send_file(
                entity=target,
                file=message.media,
                caption=text
            )
        else:
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

    log.info("DELETE COMMAND TRIGGERED")

    # ========================================================
    # OWNER ONLY
    # ========================================================

    if not await is_allowed(event):
        log.warning("DELETE DENIED - NOT OWNER")
        
        try:
            await event.reply("❌ أنت لست من المالكين!")
            await event.delete()
        except Exception as e:
            log.error("Error deleting unauthorized command: %s", e)

        return

    # ========================================================
    # لازم REPLY
    # ========================================================

    if not event.is_reply:
        log.warning("DELETE - NO REPLY")
        
        await event.reply(
            "⚠️ لازم تدير Reply على المنشور ثم تكتب /del"
        )

        return

    replied = await event.get_reply_message()

    if not replied:
        log.warning("DELETE - REPLY NOT FOUND")
        
        await event.reply(
            "❌ لم أجد الرسالة."
        )

        return
    
    log.info("DELETE - FOUND REPLY: %s", replied.id)

    current_chat = event.chat_id
    current_message = replied.id

    source_chat = None
    source_message = None

    log.info("DELETE - CURRENT CHAT: %s, CURRENT MESSAGE: %s", current_chat, current_message)
    log.info("DELETE - SOURCE CHAT: %s", SOURCE)

    # ========================================================
    # إذا Reply على SOURCE
    # ========================================================

    if current_chat == SOURCE:
        log.info("DELETE - REPLYING TO SOURCE")
        
        source_chat = SOURCE
        source_message = current_message

    # ========================================================
    # إذا Reply على TARGET
    # ========================================================

    else:
        log.info("DELETE - REPLYING TO TARGET, SEARCHING IN DB")
        
        found = get_source_from_target(
            current_chat,
            current_message
        )

        if found:
            source_chat, source_message = found
            log.info("DELETE - FOUND IN DB: SOURCE_CHAT=%s, SOURCE_MSG=%s", source_chat, source_message)
        else:
            log.warning("DELETE - NOT FOUND IN DB")

    # ========================================================
    # غير معروف
    # ========================================================

    if source_chat is None:
        log.error("DELETE - SOURCE CHAT IS NONE")
        
        await event.reply(
            "❌ هذا المنشور غير مسجل عند البوت."
        )

        return

    log.info(
        "DELETE | SOURCE=%s | MESSAGE=%s",
        source_chat,
        source_message
    )

    deleted_count = 0
    error_count = 0

    # ========================================================
    # حذف الأصل من SOURCE
    # ========================================================

    try:
        await client.delete_messages(
            source_chat,
            source_message
        )

        log.info("✅ SOURCE MESSAGE DELETED")
        deleted_count += 1

    except Exception as e:
        log.error("❌ SOURCE DELETE ERROR: %s", e)
        error_count += 1

    # ========================================================
    # جلب النسخ
    # ========================================================

    copies = get_copies(
        source_chat,
        source_message
    )

    log.info("FOUND %s COPIES TO DELETE", len(copies))

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
                "✅ COPY DELETED | %s | %s",
                target_chat,
                target_message
            )
            
            deleted_count += 1

        except Exception as e:
            log.error(
                "❌ COPY DELETE ERROR | %s | %s | %s",
                target_chat,
                target_message,
                e
            )
            
            error_count += 1

    # ========================================================
    # حذف سجل DB
    # ========================================================

    try:
        delete_records(
            source_chat,
            source_message
        )
        log.info("✅ DATABASE RECORDS DELETED")
    except Exception as e:
        log.error("❌ ERROR DELETING DATABASE RECORDS: %s", e)

    # ========================================================
    # إرسال رسالة نجاح للمستخدم
    # ========================================================

    try:
        message_text = f"✅ تم حذف المنشور!\n"
        message_text += f"📊 تم حذف {deleted_count} رسالة\n"
        
        if error_count > 0:
            message_text += f"⚠️ حدثت {error_count} أخطاء"
        
        await event.reply(message_text)
    except Exception as e:
        log.error("ERROR SENDING REPLY: %s", e)

    # ========================================================
    # حذف أمر /del من جميع الأماكن
    # ========================================================

    try:
        await event.delete()
        log.info("✅ DELETE COMMAND DELETED")
    except Exception as e:
        log.error("ERROR DELETING COMMAND: %s", e)

    # حذف الرد إذا كان موجود
    try:
        await replied.delete()
        log.info("✅ REPLIED MESSAGE DELETED")
    except Exception as e:
        log.error("ERROR DELETING REPLIED MESSAGE: %s", e)

    log.info("✅ DELETE COMPLETE - DELETED: %s, ERRORS: %s", deleted_count, error_count)


# ============================================================
# START
# ============================================================

async def main():

    log.info("===================================")
    log.info("LEX MERCHANT ADS BOT")
    log.info("===================================")

    log.info("API_ID  : %s", API_ID)
    log.info("SOURCE  : %s", SOURCE)
    log.info("TARGETS : %s", TARGETS)
    log.info("OWNERS  : %s", OWNER_IDS)

    try:
        log.info("Starting bot...")
        await client.start(bot_token=BOT_TOKEN)

        me = await client.get_me()

        log.info(
            "✅ BOT STARTED: @%s | ID=%s",
            me.username,
            me.id
        )

        log.info("✅ BOT IS RUNNING")

        await client.run_until_disconnected()

    except FloodWaitError as e:
        log.error("❌ FloodWait Error: %s seconds required", e.seconds)
        await asyncio.sleep(e.seconds)
        await main()

    except Exception as e:
        log.error("❌ FATAL ERROR: %s", e)
        raise


if __name__ == "__main__":
    asyncio.run(main())
 
