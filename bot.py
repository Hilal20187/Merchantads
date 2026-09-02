import os
import asyncio
import logging
import sqlite3
import re

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, RPCError
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# LEX AUTO PUBLISHER PRO
# SOURCE -> TARGETS
# ============================================================

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

BOT_NAME = os.getenv("BOT_NAME", "BOT_2")

OWNER_ID = os.getenv("OWNER_ID", "")
OWNER_IDS = {
    int(x.strip())
    for x in OWNER_ID.split(",")
    if x.strip()
}

SOURCE_CHAT_ID = int(os.environ["SOURCE_CHAT_ID"])

TARGET_CHAT_IDS = [
    int(x.strip())
    for x in os.environ["TARGET_CHAT_IDS"].split(",")
    if x.strip()
]

# ============================================================
# DATABASE
# ============================================================

DB_FILE = os.getenv(
    "DB_FILE",
    "lex_publisher.db"
)

# ============================================================
# SPECIAL CHANNELS
# channel_id -> owner_id
# ============================================================

SPECIAL_CHANNELS = {
    -1002239341307: 5578623360,
    -1002895996910: 1760181851,
}

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("LEX-PUBLISHER")

# ============================================================
# DATABASE INIT
# ============================================================

def db_connect():
    return sqlite3.connect(
        DB_FILE,
        timeout=30
    )


def init_db():

    conn = db_connect()

    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS message_map (
            source_chat_id INTEGER NOT NULL,
            source_message_id INTEGER NOT NULL,
            target_chat_id INTEGER NOT NULL,
            target_message_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (
                source_chat_id,
                source_message_id,
                target_chat_id
            )
        )
    """)

    conn.commit()
    conn.close()

    logger.info(
        "DATABASE READY: %s",
        DB_FILE
    )


# ============================================================
# DATABASE FUNCTIONS
# ============================================================

def save_mapping(
    source_chat_id,
    source_message_id,
    target_chat_id,
    target_message_id
):

    conn = db_connect()

    cur = conn.cursor()

    cur.execute("""
        INSERT OR REPLACE INTO message_map
        (
            source_chat_id,
            source_message_id,
            target_chat_id,
            target_message_id
        )
        VALUES (?, ?, ?, ?)
    """, (
        source_chat_id,
        source_message_id,
        target_chat_id,
        target_message_id
    ))

    conn.commit()
    conn.close()


def get_mappings(
    source_message_id,
    source_chat_id
):

    conn = db_connect()

    cur = conn.cursor()

    cur.execute("""
        SELECT
            target_chat_id,
            target_message_id
        FROM message_map
        WHERE
            source_chat_id = ?
            AND source_message_id = ?
    """, (
        source_chat_id,
        source_message_id
    ))

    rows = cur.fetchall()

    conn.close()

    return rows


def get_parent_mapping(
    source_chat_id,
    source_message_id,
    target_chat_id
):

    conn = db_connect()

    cur = conn.cursor()

    cur.execute("""
        SELECT target_message_id
        FROM message_map
        WHERE
            source_chat_id = ?
            AND source_message_id = ?
            AND target_chat_id = ?
    """, (
        source_chat_id,
        source_message_id,
        target_chat_id
    ))

    row = cur.fetchone()

    conn.close()

    if row:
        return row[0]

    return None


def delete_mappings(
    source_message_id,
    source_chat_id
):

    conn = db_connect()

    cur = conn.cursor()

    cur.execute("""
        DELETE FROM message_map
        WHERE
            source_chat_id = ?
            AND source_message_id = ?
    """, (
        source_chat_id,
        source_message_id
    ))

    conn.commit()
    conn.close()


# ============================================================
# PERMISSION
# ============================================================

def is_allowed(user_id):

    if not OWNER_IDS:
        return False

    return user_id in OWNER_IDS


# ============================================================
# TELEGRAM CLIENT
# ============================================================

client = TelegramClient(
    "lex_publisher_session_2",
    API_ID,
    API_HASH
)


# ============================================================
# RETRY SYSTEM
# ============================================================

async def run_with_retry(
    func,
    *args,
    **kwargs
):

    while True:

        try:

            return await func(
                *args,
                **kwargs
            )

        except FloodWaitError as e:

            logger.warning(
                "FLOOD WAIT: sleeping %s seconds",
                e.seconds
            )

            await asyncio.sleep(
                e.seconds + 2
            )

        except RPCError as e:

            logger.warning(
                "RPC ERROR: %s",
                e
            )

            await asyncio.sleep(2)

        except Exception as e:

            logger.exception(
                "RETRY ERROR: %s",
                e
            )

            await asyncio.sleep(2)


# ============================================================
# SOURCE NEW MESSAGE
# ============================================================

@client.on(
    events.NewMessage(
        chats=SOURCE_CHAT_ID
    )
)
async def source_new_message(event):

    try:

        text = event.raw_text or ""

        # لا نعالج أوامر البوت هنا
        if text.startswith("/"):
            return

        source_message_id = event.id

        logger.info(
            "NEW SOURCE MESSAGE: %s",
            source_message_id
        )

        # ----------------------------------------------------
        # نشر في جميع TARGETS
        # ----------------------------------------------------

        for target_chat_id in TARGET_CHAT_IDS:

            reply_to = None

            # إذا الرسالة Reply
            if event.is_reply:

                replied = await event.get_reply_message()

                if replied:

                    reply_to = get_parent_mapping(
                        SOURCE_CHAT_ID,
                        replied.id,
                        target_chat_id
                    )

            # ------------------------------------------------
            # إرسال النسخة
            # ------------------------------------------------

            sent = await run_with_retry(
                client.send_message,
                target_chat_id,
                event.message,
                reply_to=reply_to
            )

            if sent:

                save_mapping(
                    SOURCE_CHAT_ID,
                    source_message_id,
                    target_chat_id,
                    sent.id
                )

                logger.info(
                    "PUBLISHED | SOURCE=%s | TARGET=%s | MSG=%s",
                    source_message_id,
                    target_chat_id,
                    sent.id
                )

            await asyncio.sleep(0.3)

    except Exception as e:

        logger.exception(
            "SOURCE NEW MESSAGE ERROR: %s",
            e
        )


# ============================================================
# SOURCE EDIT
# ============================================================

@client.on(
    events.MessageEdited(
        chats=SOURCE_CHAT_ID
    )
)
async def source_message_edited(event):

    try:

        text = event.raw_text or ""

        if text.startswith("/"):
            return

        mappings = get_mappings(
            event.id,
            SOURCE_CHAT_ID
        )

        if not mappings:
            return

        for target_chat_id, target_message_id in mappings:

            try:

                await run_with_retry(
                    client.edit_message,
                    target_chat_id,
                    target_message_id,
                    event.message
                )

                logger.info(
                    "EDITED | SOURCE=%s | TARGET=%s | MSG=%s",
                    event.id,
                    target_chat_id,
                    target_message_id
                )

            except Exception as e:

                logger.warning(
                    "EDIT FAILED | TARGET=%s | %s",
                    target_chat_id,
                    e
                )

            await asyncio.sleep(0.3)

    except Exception as e:

        logger.exception(
            "SOURCE EDIT ERROR: %s",
            e
        )


# ============================================================
# SOURCE DELETE
# ============================================================

@client.on(
    events.MessageDeleted(
        chats=SOURCE_CHAT_ID
    )
)
async def source_message_deleted(event):

    try:

        for source_message_id in event.deleted_ids:

            mappings = get_mappings(
                source_message_id,
                SOURCE_CHAT_ID
            )

            if not mappings:
                continue

            for target_chat_id, target_message_id in mappings:

                try:

                    await run_with_retry(
                        client.delete_messages,
                        target_chat_id,
                        [target_message_id]
                    )

                    logger.info(
                        "DELETED | SOURCE=%s | TARGET=%s | MSG=%s",
                        source_message_id,
                        target_chat_id,
                        target_message_id
                    )

                except Exception as e:

                    logger.warning(
                        "TARGET DELETE FAILED: %s",
                        e
                    )

                await asyncio.sleep(0.3)

            delete_mappings(
                source_message_id,
                SOURCE_CHAT_ID
            )

    except Exception as e:

        logger.exception(
            "SOURCE DELETE ERROR: %s",
            e
        )


# ============================================================
# MANUAL DELETE
#
# يعمل مع:
# /del
# /del@Merchantadss_bot
#
# ============================================================

@client.on(
    events.NewMessage(
        chats=SOURCE_CHAT_ID
    )
)
async def manual_delete_handler(event):

    try:

        text = (event.raw_text or "").strip()

        # ----------------------------------------------------
        # التحقق من الأمر
        #
        # /del
        # /del@Merchantadss_bot
        # ----------------------------------------------------

        if not re.fullmatch(
            r"/del(?:@[A-Za-z0-9_]+)?",
            text,
            re.IGNORECASE
        ):
            return

        # ----------------------------------------------------
        # صلاحيات المستخدم
        # ----------------------------------------------------

        if not is_allowed(
            event.sender_id
        ):
            return

        # ----------------------------------------------------
        # لازم يكون Reply
        # ----------------------------------------------------

        if not event.is_reply:

            await event.reply(
                "⚠️ خاصك تدير Reply على الرسالة "
                "اللي تحب تحذفها وتكتب:\n\n"
                "/del\n"
                "أو\n"
                "/del@Merchantadss_bot"
            )

            return

        replied = await event.get_reply_message()

        if replied is None:
            return

        source_message_id = replied.id

        logger.info(
            "MANUAL DELETE REQUEST | SOURCE=%s | USER=%s",
            source_message_id,
            event.sender_id
        )

        # ----------------------------------------------------
        # البحث عن النسخ
        # ----------------------------------------------------

        mappings = get_mappings(
            source_message_id,
            SOURCE_CHAT_ID
        )

        if not mappings:

            await event.reply(
                f"❌ ما لقيتش نسخ للرسالة "
                f"(ID: {source_message_id})"
            )

            return

        deleted_count = 0

        # ----------------------------------------------------
        # حذف جميع النسخ
        # ----------------------------------------------------

        for target_chat_id, target_message_id in mappings:

            try:

                result = await run_with_retry(
                    client.delete_messages,
                    target_chat_id,
                    [target_message_id]
                )

                if result is not None:
                    deleted_count += 1

                logger.info(
                    "MANUAL DELETE TARGET | TARGET=%s | MSG=%s",
                    target_chat_id,
                    target_message_id
                )

            except Exception as e:

                logger.warning(
                    "MANUAL TARGET DELETE FAILED | TARGET=%s | %s",
                    target_chat_id,
                    e
                )

            await asyncio.sleep(0.3)

        # ----------------------------------------------------
        # حذف DB mapping
        # ----------------------------------------------------

        delete_mappings(
            source_message_id,
            SOURCE_CHAT_ID
        )

        # ----------------------------------------------------
        # حذف الرسالة الأصلية
        # ----------------------------------------------------

        try:

            await run_with_retry(
                client.delete_messages,
                SOURCE_CHAT_ID,
                [source_message_id]
            )

        except Exception as e:

            logger.warning(
                "SOURCE MESSAGE DELETE FAILED: %s",
                e
            )

        # ----------------------------------------------------
        # حذف أمر /del نفسه
        # ----------------------------------------------------

        try:

            await event.delete()

        except Exception as e:

            logger.warning(
                "COMMAND DELETE FAILED: %s",
                e
            )

        logger.info(
            "MANUAL DELETE COMPLETE | SOURCE=%s | DELETED=%s/%s",
            source_message_id,
            deleted_count,
            len(mappings)
        )

    except Exception as e:

        logger.exception(
            "MANUAL DELETE ERROR: %s",
            e
        )


# ============================================================
# STATUS
# ============================================================

@client.on(
    events.NewMessage(
        chats=SOURCE_CHAT_ID,
        pattern=r"^/status$"
    )
)
async def status_handler(event):

    if not is_allowed(
        event.sender_id
    ):
        return

    await event.reply(
        "🟢 LEX AUTO PUBLISHER PRO\n\n"
        f"Bot: {BOT_NAME}\n"
        f"Source: {SOURCE_CHAT_ID}\n"
        f"Targets: {len(TARGET_CHAT_IDS)}\n"
        f"Database: {DB_FILE}"
    )


# ============================================================
# ID COMMAND
# ============================================================

@client.on(
    events.NewMessage(
        chats=SOURCE_CHAT_ID,
        pattern=r"^/id$"
    )
)
async def id_handler(event):

    if not is_allowed(
        event.sender_id
    ):
        return

    await event.reply(
        f"👤 Your ID:\n"
        f"`{event.sender_id}`\n\n"
        f"💬 Chat ID:\n"
        f"`{SOURCE_CHAT_ID}`"
    )


# ============================================================
# SPECIAL CHANNEL HANDLER
# ============================================================

def register_special_channel(
    channel_id,
    owner_id
):

    @client.on(
        events.NewMessage(
            chats=channel_id
        )
    )
    async def special_new(event):

        try:

            text = event.raw_text or ""

            if text.startswith("/"):
                return

            source_message_id = event.id

            logger.info(
                "SPECIAL NEW | CHANNEL=%s | OWNER=%s | MSG=%s",
                channel_id,
                owner_id,
                source_message_id
            )

            # نشر في TARGETS
            for target_chat_id in TARGET_CHAT_IDS:

                reply_to = None

                if event.is_reply:

                    replied = await event.get_reply_message()

                    if replied:

                        reply_to = get_parent_mapping(
                            channel_id,
                            replied.id,
                            target_chat_id
                        )

                sent = await run_with_retry(
                    client.send_message,
                    target_chat_id,
                    event.message,
                    reply_to=reply_to
                )

                if sent:

                    save_mapping(
                        channel_id,
                        source_message_id,
                        target_chat_id,
                        sent.id
                    )

                await asyncio.sleep(0.3)

        except Exception as e:

            logger.exception(
                "SPECIAL NEW ERROR: %s",
                e
            )

    @client.on(
        events.MessageEdited(
            chats=channel_id
        )
    )
    async def special_edit(event):

        try:

            mappings = get_mappings(
                event.id,
                channel_id
            )

            for target_chat_id, target_message_id in mappings:

                await run_with_retry(
                    client.edit_message,
                    target_chat_id,
                    target_message_id,
                    event.message
                )

                await asyncio.sleep(0.3)

        except Exception as e:

            logger.exception(
                "SPECIAL EDIT ERROR: %s",
                e
            )

    @client.on(
        events.MessageDeleted(
            chats=channel_id
        )
    )
    async def special_delete(event):

        try:

            for source_message_id in event.deleted_ids:

                mappings = get_mappings(
                    source_message_id,
                    channel_id
                )

                for target_chat_id, target_message_id in mappings:

                    try:

                        await run_with_retry(
                            client.delete_messages,
                            target_chat_id,
                            [target_message_id]
                        )

                    except Exception as e:

                        logger.warning(
                            "SPECIAL TARGET DELETE ERROR: %s",
                            e
                        )

                    await asyncio.sleep(0.3)

                delete_mappings(
                    source_message_id,
                    channel_id
                )

        except Exception as e:

            logger.exception(
                "SPECIAL DELETE ERROR: %s",
                e
            )


# ============================================================
# REGISTER SPECIAL CHANNELS
# ============================================================

for special_channel_id, special_owner_id in SPECIAL_CHANNELS.items():

    register_special_channel(
        special_channel_id,
        special_owner_id
    )


# ============================================================
# START
# ============================================================

async def main():

    init_db()

    logger.info(
        "=================================================="
    )

    logger.info(
        "LEX AUTO PUBLISHER PRO STARTING..."
    )

    logger.info(
        "BOT NAME: %s",
        BOT_NAME
    )

    logger.info(
        "SOURCE: %s",
        SOURCE_CHAT_ID
    )

    logger.info(
        "TARGETS: %s",
        TARGET_CHAT_IDS
    )

    logger.info(
        "DATABASE: %s",
        DB_FILE
    )

    logger.info(
        "SPECIAL CHANNELS: %s",
        SPECIAL_CHANNELS
    )

    logger.info(
        "=================================================="
    )

    await client.start(
        bot_token=BOT_TOKEN
    )

    me = await client.get_me()

    logger.info(
        "BOT CONNECTED: @%s | ID=%s",
        me.username,
        me.id
    )

    logger.info(
        "LEX AUTO PUBLISHER PRO IS ONLINE 🟢"
    )

    await client.run_until_disconnected()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        logger.info(
            "BOT STOPPED"
            ) 
