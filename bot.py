import os
import asyncio
import logging
import sqlite3

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, RPCError
from telethon.tl import types


# ============================================================
# LEX AUTO PUBLISHER PRO
# ============================================================
#
# MAIN:
# -1004333211848
#
# TARGET:
# -1004407774851
#
# OWNER:
# 822007358
#
# FUNCTION:
#
# MAIN MESSAGE
#       ↓
# COPY TO TARGET
#
# DELETE MAIN
#       ↓
# DELETE COPY
#
# EDIT MAIN
#       ↓
# EDIT COPY
#
# TEXT ONLY
# ============================================================


# ============================================================
# TELEGRAM CREDENTIALS
# ============================================================

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]


# ============================================================
# FIXED IDs
# ============================================================

OWNER_ID = 822007358

MAIN_CHAT_ID = -1004333211848

TARGET_CHAT_ID = -1004407774851


# Telegram channel ID without -100
MAIN_CHANNEL_ID = 4333211848


# ============================================================
# DATABASE
# ============================================================

DB_FILE = os.getenv(
    "DB_FILE",
    "lex_publisher.db"
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("LEX")


# ============================================================
# DATABASE INIT
# ============================================================

def init_db():

    conn = sqlite3.connect(
        DB_FILE,
        timeout=30
    )

    try:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS message_map (

                source_chat_id INTEGER NOT NULL,

                source_message_id INTEGER NOT NULL,

                target_chat_id INTEGER NOT NULL,

                target_message_id INTEGER NOT NULL,

                created_at DATETIME
                    DEFAULT CURRENT_TIMESTAMP,

                PRIMARY KEY (
                    source_chat_id,
                    source_message_id
                )
            )
        """)

        conn.commit()

    finally:

        conn.close()


# ============================================================
# SAVE MESSAGE MAPPING
# ============================================================

def save_mapping(
    source_message_id,
    target_message_id
):

    conn = sqlite3.connect(
        DB_FILE,
        timeout=30
    )

    try:

        conn.execute("""
            INSERT OR REPLACE INTO message_map (

                source_chat_id,

                source_message_id,

                target_chat_id,

                target_message_id

            )

            VALUES (?, ?, ?, ?)
        """, (
            MAIN_CHAT_ID,
            source_message_id,
            TARGET_CHAT_ID,
            target_message_id
        ))

        conn.commit()

    finally:

        conn.close()


# ============================================================
# GET TARGET MESSAGE
# ============================================================

def get_mapping(
    source_message_id
):

    conn = sqlite3.connect(
        DB_FILE,
        timeout=30
    )

    try:

        row = conn.execute("""
            SELECT target_message_id

            FROM message_map

            WHERE source_chat_id = ?

              AND source_message_id = ?

              AND target_chat_id = ?

        """, (
            MAIN_CHAT_ID,
            source_message_id,
            TARGET_CHAT_ID
        )).fetchone()

        if row:
            return row[0]

        return None

    finally:

        conn.close()


# ============================================================
# DELETE MAPPING
# ============================================================

def delete_mapping(
    source_message_id
):

    conn = sqlite3.connect(
        DB_FILE,
        timeout=30
    )

    try:

        conn.execute("""
            DELETE FROM message_map

            WHERE source_chat_id = ?

              AND source_message_id = ?

              AND target_chat_id = ?

        """, (
            MAIN_CHAT_ID,
            source_message_id,
            TARGET_CHAT_ID
        ))

        conn.commit()

    finally:

        conn.close()


# ============================================================
# TELETHON CLIENT
# ============================================================

client = TelegramClient(
    "lex_publisher",
    API_ID,
    API_HASH
)


BOT_ID = None


# ============================================================
# CHECK OWNER
# ============================================================

def is_owner(event):

    return event.sender_id == OWNER_ID


# ============================================================
# SEND MESSAGE
# ============================================================

async def send_to_target(
    message
):

    text = message.raw_text or ""

    if not text.strip():
        return None

    try:

        sent = await client.send_message(
            TARGET_CHAT_ID,
            text,
            formatting_entities=message.entities
        )

        return sent.id

    except FloodWaitError as e:

        logger.warning(
            "FloodWait: %s seconds",
            e.seconds
        )

        await asyncio.sleep(
            e.seconds + 1
        )

        try:

            sent = await client.send_message(
                TARGET_CHAT_ID,
                text,
                formatting_entities=message.entities
            )

            return sent.id

        except Exception as retry_error:

            logger.error(
                "SEND RETRY ERROR: %s",
                retry_error
            )

            return None

    except RPCError as e:

        logger.error(
            "SEND TELEGRAM ERROR: %s",
            e
        )

        return None

    except Exception as e:

        logger.exception(
            "SEND ERROR: %s",
            e
        )

        return None


# ============================================================
# MAIN -> TARGET
# ============================================================

@client.on(events.NewMessage)
async def main_message_handler(event):

    # Only MAIN
    if event.chat_id != MAIN_CHAT_ID:
        return

    message = event.message

    # Ignore bot's own messages
    if BOT_ID is not None:

        if event.sender_id == BOT_ID:
            return

    text = message.raw_text or ""

    # Ignore commands
    if text.startswith("/"):
        return

    # TEXT ONLY
    if not text.strip():
        return

    logger.info(
        "NEW MAIN MESSAGE | id=%s",
        message.id
    )

    # Send to target
    target_message_id = await send_to_target(
        message
    )

    if target_message_id is None:

        logger.error(
            "COPY FAILED | MAIN:%s",
            message.id
        )

        return

    # Save relation
    save_mapping(
        message.id,
        target_message_id
    )

    logger.info(
        "COPIED | MAIN:%s -> TARGET:%s",
        message.id,
        target_message_id
    )


# ============================================================
# DELETE TARGET COPY
# ============================================================

async def delete_copy(
    source_message_id
):

    target_message_id = get_mapping(
        source_message_id
    )

    if target_message_id is None:

        logger.warning(
            "NO MAPPING FOR DELETED MESSAGE | MAIN:%s",
            source_message_id
        )

        return

    logger.info(
        "DELETE SYNC | MAIN:%s -> TARGET:%s",
        source_message_id,
        target_message_id
    )

    try:

        await client.delete_messages(
            TARGET_CHAT_ID,
            [target_message_id]
        )

        logger.info(
            "TARGET MESSAGE DELETED | TARGET:%s",
            target_message_id
        )

        delete_mapping(
            source_message_id
        )

    except FloodWaitError as e:

        logger.warning(
            "DELETE FLOODWAIT: %s seconds",
            e.seconds
        )

        await asyncio.sleep(
            e.seconds + 1
        )

        try:

            await client.delete_messages(
                TARGET_CHAT_ID,
                [target_message_id]
            )

            logger.info(
                "TARGET MESSAGE DELETED AFTER RETRY | TARGET:%s",
                target_message_id
            )

            delete_mapping(
                source_message_id
            )

        except Exception as retry_error:

            logger.error(
                "DELETE RETRY ERROR: %s",
                retry_error
            )

    except RPCError as e:

        logger.error(
            "DELETE TELEGRAM ERROR: %s",
            e
        )

    except Exception as e:

        logger.exception(
            "DELETE ERROR: %s",
            e
        )


# ============================================================
# RAW TELEGRAM DELETE UPDATE
# ============================================================
#
# THIS IS THE IMPORTANT PART
#
# Telegram Supergroup deletion:
#
# UpdateDeleteChannelMessages
#
# contains:
#
# channel_id
# messages
#
# We compare channel_id with:
#
# 4333211848
#
# which belongs to:
#
# -1004333211848
#
# ============================================================

@client.on(events.Raw)
async def raw_update_handler(update):

    try:

        # ----------------------------------------------------
        # SUPERGROUP / CHANNEL
        # ----------------------------------------------------

        if isinstance(
            update,
            types.UpdateDeleteChannelMessages
        ):

            channel_id = update.channel_id

            deleted_ids = update.messages

            logger.info(
                "RAW DELETE EVENT | channel_id=%s | ids=%s",
                channel_id,
                deleted_ids
            )

            # Only MAIN
            if channel_id != MAIN_CHANNEL_ID:

                logger.info(
                    "DELETE IGNORED | not MAIN"
                )

                return

            logger.info(
                "MAIN DELETE DETECTED | ids=%s",
                deleted_ids
            )

            for message_id in deleted_ids:

                await delete_copy(
                    message_id
                )

                await asyncio.sleep(
                    0.2
                )

    except Exception as e:

        logger.exception(
            "RAW DELETE HANDLER ERROR: %s",
            e
        )


# ============================================================
# EDIT COPY
# ============================================================

async def edit_copy(
    message
):

    target_message_id = get_mapping(
        message.id
    )

    if target_message_id is None:

        logger.warning(
            "NO MAPPING FOR EDIT | MAIN:%s",
            message.id
        )

        return

    text = message.raw_text or ""

    try:

        await client.edit_message(
            TARGET_CHAT_ID,
            target_message_id,
            text,
            formatting_entities=message.entities
        )

        logger.info(
            "EDIT SYNC | MAIN:%s -> TARGET:%s",
            message.id,
            target_message_id
        )

    except FloodWaitError as e:

        logger.warning(
            "EDIT FLOODWAIT: %s seconds",
            e.seconds
        )

        await asyncio.sleep(
            e.seconds + 1
        )

    except RPCError as e:

        logger.error(
            "EDIT TELEGRAM ERROR: %s",
            e
        )

    except Exception as e:

        logger.exception(
            "EDIT ERROR: %s",
            e
        )


# ============================================================
# MAIN MESSAGE EDIT
# ============================================================

@client.on(events.MessageEdited)
async def edited_message_handler(event):

    if event.chat_id != MAIN_CHAT_ID:
        return

    message = event.message

    text = message.raw_text or ""

    if not text.strip():
        return

    if text.startswith("/"):
        return

    await edit_copy(
        message
    )


# ============================================================
# /status
# ============================================================

@client.on(
    events.NewMessage(
        pattern=r"^/status$"
    )
)
async def status_handler(event):

    if not is_owner(event):
        return

    await event.reply(
        "🤖 LEX AUTO PUBLISHER PRO\n\n"

        "🟢 STATUS: ONLINE\n\n"

        f"👤 OWNER:\n"
        f"`{OWNER_ID}`\n\n"

        f"🏠 MAIN:\n"
        f"`{MAIN_CHAT_ID}`\n\n"

        f"📤 TARGET:\n"
        f"`{TARGET_CHAT_ID}`\n\n"

        "📝 MODE: TEXT ONLY\n"
        "📤 AUTO COPY: ON\n"
        "🗑 DELETE SYNC: ON\n"
        "✏️ EDIT SYNC: ON\n"
        "⚡ RAW DELETE: ON"
    )


# ============================================================
# /id
# ============================================================

@client.on(
    events.NewMessage(
        pattern=r"^/id$"
    )
)
async def id_handler(event):

    if not is_owner(event):
        return

    await event.reply(
        f"🆔 CHAT ID:\n`{event.chat_id}`"
    )


# ============================================================
# START
# ============================================================

async def main():

    global BOT_ID

    init_db()

    logger.info(
        "=========================================="
    )

    logger.info(
        "LEX AUTO PUBLISHER PRO"
    )

    logger.info(
        "=========================================="
    )

    logger.info(
        "OWNER     : %s",
        OWNER_ID
    )

    logger.info(
        "MAIN      : %s",
        MAIN_CHAT_ID
    )

    logger.info(
        "TARGET    : %s",
        TARGET_CHAT_ID
    )

    logger.info(
        "CHANNEL ID: %s",
        MAIN_CHANNEL_ID
    )

    await client.start(
        bot_token=BOT_TOKEN
    )

    me = await client.get_me()

    BOT_ID = me.id

    logger.info(
        "BOT ID    : %s",
        BOT_ID
    )

    logger.info(
        "USERNAME  : @%s",
        getattr(
            me,
            "username",
            ""
        )
    )

    logger.info(
        "STATUS    : ONLINE"
    )

    logger.info(
        "=========================================="
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
            "LEX STOPPED"
    ) 
