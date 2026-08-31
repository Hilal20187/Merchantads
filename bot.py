import os
import asyncio
import logging
import sqlite3
from contextlib import closing

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, RPCError


# ============================================================
# LEX PUBLISHER PRO
# TEXT ONLY
#
# MAIN GROUP
#      ↓
# COPY TEXT
#      ↓
# TARGET GROUPS
#
# DELETE MAIN
#      ↓
# DELETE ALL COPIES
#
# EDIT MAIN
#      ↓
# EDIT ALL COPIES
#
# Includes backup deletion monitor.
# ============================================================


# ============================================================
# CONFIG
# ============================================================

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])

# Railway Volume recommended:
# DB_FILE=/data/lex_publisher.db
DB_FILE = os.getenv(
    "DB_FILE",
    "lex_publisher.db"
)

SESSION_FILE = os.getenv(
    "SESSION_FILE",
    "lex_publisher"
)

# How often the backup deletion monitor checks messages
DELETE_CHECK_INTERVAL = int(
    os.getenv(
        "DELETE_CHECK_INTERVAL",
        "30"
    )
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

logger = logging.getLogger("LEX-PUBLISHER")


# ============================================================
# DATABASE
# ============================================================

def get_db():

    return sqlite3.connect(
        DB_FILE,
        timeout=30
    )


def init_db():

    with closing(get_db()) as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS targets (
                chat_id INTEGER PRIMARY KEY,
                title TEXT,
                username TEXT,
                enabled INTEGER DEFAULT 1
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS message_map (
                source_chat_id INTEGER NOT NULL,
                source_message_id INTEGER NOT NULL,
                target_chat_id INTEGER NOT NULL,
                target_message_id INTEGER NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

                PRIMARY KEY (
                    source_chat_id,
                    source_message_id,
                    target_chat_id
                )
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_source_messages
            ON message_map (
                source_chat_id,
                source_message_id
            )
        """)

        conn.commit()


# ============================================================
# SETTINGS
# ============================================================

def set_setting(
    key,
    value
):

    with closing(get_db()) as conn:

        conn.execute("""
            INSERT INTO settings (
                key,
                value
            )

            VALUES (?, ?)

            ON CONFLICT(key)
            DO UPDATE SET
                value = excluded.value
        """, (
            key,
            str(value)
        ))

        conn.commit()


def get_setting(key):

    with closing(get_db()) as conn:

        row = conn.execute(
            """
            SELECT value
            FROM settings
            WHERE key = ?
            """,
            (key,)
        ).fetchone()

        if row:
            return row[0]

        return None


# ============================================================
# MAIN GROUP
# ============================================================

def get_main_id():

    value = get_setting(
        "main_chat_id"
    )

    if not value:
        return None

    try:
        return int(value)

    except ValueError:
        return None


# ============================================================
# TARGET GROUPS
# ============================================================

def add_target(
    chat_id,
    title,
    username
):

    with closing(get_db()) as conn:

        conn.execute("""
            INSERT INTO targets (
                chat_id,
                title,
                username,
                enabled
            )

            VALUES (?, ?, ?, 1)

            ON CONFLICT(chat_id)
            DO UPDATE SET
                title = excluded.title,
                username = excluded.username,
                enabled = 1
        """, (
            chat_id,
            title or "",
            username or ""
        ))

        conn.commit()


def remove_target(chat_id):

    with closing(get_db()) as conn:

        conn.execute(
            """
            DELETE FROM targets
            WHERE chat_id = ?
            """,
            (chat_id,)
        )

        conn.commit()


def get_targets():

    with closing(get_db()) as conn:

        return conn.execute("""
            SELECT
                chat_id,
                title,
                username

            FROM targets

            WHERE enabled = 1

            ORDER BY rowid ASC
        """).fetchall()


# ============================================================
# MESSAGE MAPPING
# ============================================================

def save_mapping(
    source_chat_id,
    source_message_id,
    target_chat_id,
    target_message_id
):

    with closing(get_db()) as conn:

        conn.execute("""
            INSERT OR REPLACE INTO message_map (
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


def get_mappings(
    source_chat_id,
    source_message_id
):

    with closing(get_db()) as conn:

        return conn.execute("""
            SELECT
                target_chat_id,
                target_message_id

            FROM message_map

            WHERE source_chat_id = ?
              AND source_message_id = ?
        """, (
            source_chat_id,
            source_message_id
        )).fetchall()


def delete_mappings(
    source_chat_id,
    source_message_id
):

    with closing(get_db()) as conn:

        conn.execute("""
            DELETE FROM message_map

            WHERE source_chat_id = ?
              AND source_message_id = ?
        """, (
            source_chat_id,
            source_message_id
        ))

        conn.commit()


def get_known_source_messages():

    with closing(get_db()) as conn:

        return conn.execute("""
            SELECT DISTINCT
                source_message_id

            FROM message_map

            WHERE source_chat_id = ?

            ORDER BY source_message_id DESC

            LIMIT 100
        """, (
            get_main_id(),
        )).fetchall()


# ============================================================
# TELEGRAM CLIENT
# ============================================================

client = TelegramClient(
    SESSION_FILE,
    API_ID,
    API_HASH
)


BOT_ID = None


# ============================================================
# OWNER CHECK
# ============================================================

def is_owner(event):

    return event.sender_id == OWNER_ID


# ============================================================
# FLOOD WAIT HELPER
# ============================================================

async def sleep_flood(e):

    seconds = int(
        getattr(
            e,
            "seconds",
            5
        )
    )

    logger.warning(
        "FloodWait: sleeping %s seconds",
        seconds
    )

    await asyncio.sleep(
        seconds + 1
    )


# ============================================================
# /start
# ============================================================

@client.on(
    events.NewMessage(
        pattern=r"^/start$"
    )
)
async def start_handler(event):

    if not is_owner(event):
        return

    await event.reply(
        "🤖 LEX PUBLISHER PRO\n\n"

        "📌 نظام نشر النصوص\n\n"

        "/setmain\n"
        "تعيين القروب الرئيسي\n\n"

        "/addgroup\n"
        "إضافة القروب الحالي\n\n"

        "/removegroup\n"
        "إزالة القروب الحالي\n\n"

        "/groups\n"
        "عرض القروبات\n\n"

        "/status\n"
        "حالة البوت"
    )


# ============================================================
# /setmain
# ============================================================

@client.on(
    events.NewMessage(
        pattern=r"^/setmain$"
    )
)
async def setmain_handler(event):

    if not is_owner(event):
        return

    chat = await event.get_chat()

    set_setting(
        "main_chat_id",
        chat.id
    )

    logger.info(
        "MAIN SET: %s",
        chat.id
    )

    await event.reply(
        "✅ تم تعيين هذا القروب كـ MAIN.\n\n"
        f"🆔 `{chat.id}`"
    )


# ============================================================
# /addgroup
# ============================================================

@client.on(
    events.NewMessage(
        pattern=r"^/addgroup$"
    )
)
async def addgroup_handler(event):

    if not is_owner(event):
        return

    chat = await event.get_chat()

    main = get_main_id()

    if main == chat.id:

        await event.reply(
            "❌ هذا القروب هو MAIN."
        )

        return

    title = getattr(
        chat,
        "title",
        ""
    )

    username = getattr(
        chat,
        "username",
        None
    )

    add_target(
        chat.id,
        title,
        username
    )

    logger.info(
        "TARGET ADDED: %s | %s",
        chat.id,
        title
    )

    await event.reply(
        "✅ تمت إضافة القروب للنشر.\n\n"
        f"📌 {title or 'بدون اسم'}\n"
        f"🆔 `{chat.id}`"
    )


# ============================================================
# /removegroup
# ============================================================

@client.on(
    events.NewMessage(
        pattern=r"^/removegroup$"
    )
)
async def removegroup_handler(event):

    if not is_owner(event):
        return

    chat = await event.get_chat()

    remove_target(
        chat.id
    )

    await event.reply(
        "✅ تم حذف القروب من قائمة النشر."
    )


# ============================================================
# /groups
# ============================================================

@client.on(
    events.NewMessage(
        pattern=r"^/groups$"
    )
)
async def groups_handler(event):

    if not is_owner(event):
        return

    targets = get_targets()

    if not targets:

        await event.reply(
            "📭 لا توجد قروبات مستهدفة."
        )

        return

    text = (
        "📋 القروبات المستهدفة:\n\n"
    )

    for i, (
        chat_id,
        title,
        username
    ) in enumerate(
        targets,
        1
    ):

        text += (
            f"{i}. {title or 'بدون اسم'}\n"
            f"🆔 `{chat_id}`\n"
        )

        if username:
            text += (
                f"🔗 @{username}\n"
            )

        text += "\n"

    await event.reply(
        text
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

    main = get_main_id()
    targets = get_targets()

    await event.reply(
        "🤖 LEX PUBLISHER PRO\n\n"

        "🟢 STATUS: ONLINE\n\n"

        f"🏠 MAIN:\n"
        f"`{main or 'غير محدد'}`\n\n"

        f"📤 TARGETS: `{len(targets)}`\n\n"

        "📝 MODE: TEXT ONLY\n"
        "🗑 DELETE SYNC: ON\n"
        "✏️ EDIT SYNC: ON\n"
        "🔎 DELETE WATCHDOG: ON"
    )


# ============================================================
# SEND TEXT COPY
# ============================================================

async def send_copy(
    target_chat_id,
    message
):

    text = message.raw_text or ""

    if not text.strip():
        return None

    try:

        copied = await client.send_message(
            target_chat_id,
            text,
            formatting_entities=message.entities
        )

        return copied.id

    except FloodWaitError as e:

        await sleep_flood(e)

        try:

            copied = await client.send_message(
                target_chat_id,
                text,
                formatting_entities=message.entities
            )

            return copied.id

        except Exception as retry_error:

            logger.error(
                "RETRY SEND FAILED: %s",
                retry_error
            )

            return None

    except RPCError as e:

        logger.error(
            "SEND RPC ERROR [%s]: %s",
            target_chat_id,
            e
        )

        return None

    except Exception as e:

        logger.exception(
            "SEND ERROR [%s]: %s",
            target_chat_id,
            e
        )

        return None


# ============================================================
# MAIN -> TARGETS
# ============================================================

@client.on(events.NewMessage)
async def publish_handler(event):

    main = get_main_id()

    if not main:
        return

    # Must be MAIN
    if event.chat_id != main:
        return

    # Ignore our own bot messages
    if BOT_ID is not None:
        if event.sender_id == BOT_ID:
            return

    message = event.message

    text = message.raw_text or ""

    # Ignore commands
    if text.startswith("/"):
        return

    # TEXT ONLY
    if not text.strip():
        return

    targets = get_targets()

    if not targets:
        logger.warning(
            "MAIN message received but no targets."
        )

        return

    logger.info(
        "NEW MAIN MESSAGE | id=%s",
        message.id
    )

    for (
        target_chat_id,
        title,
        username
    ) in targets:

        copied_id = await send_copy(
            target_chat_id,
            message
        )

        if copied_id is not None:

            save_mapping(
                main,
                message.id,
                target_chat_id,
                copied_id
            )

            logger.info(
                "COPIED | MAIN:%s -> TARGET:%s:%s",
                message.id,
                target_chat_id,
                copied_id
            )

        else:

            logger.error(
                "COPY FAILED | target=%s",
                target_chat_id
            )

        # Small delay between groups
        await asyncio.sleep(
            0.3
        )


# ============================================================
# DELETE FUNCTION
# ============================================================

async def delete_copies(
    source_message_id
):

    main = get_main_id()

    if not main:
        return

    mappings = get_mappings(
        main,
        source_message_id
    )

    if not mappings:

        logger.info(
            "NO MAPPING | source=%s",
            source_message_id
        )

        return

    logger.info(
        "DELETE SYNC | source=%s | copies=%s",
        source_message_id,
        len(mappings)
    )

    for (
        target_chat_id,
        target_message_id
    ) in mappings:

        try:

            await client.delete_messages(
                target_chat_id,
                [target_message_id]
            )

            logger.info(
                "COPY DELETED | target=%s | msg=%s",
                target_chat_id,
                target_message_id
            )

        except FloodWaitError as e:

            await sleep_flood(e)

            try:

                await client.delete_messages(
                    target_chat_id,
                    [target_message_id]
                )

            except Exception as retry_error:

                logger.error(
                    "DELETE RETRY FAILED: %s",
                    retry_error
                )

        except RPCError as e:

            logger.error(
                "DELETE RPC ERROR | target=%s | %s",
                target_chat_id,
                e
            )

        except Exception as e:

            logger.exception(
                "DELETE ERROR | target=%s | %s",
                target_chat_id,
                e
            )

        await asyncio.sleep(
            0.2
        )

    delete_mappings(
        main,
        source_message_id
    )


# ============================================================
# TELEGRAM DELETE EVENT
# ============================================================

@client.on(events.MessageDeleted)
async def message_deleted_handler(event):

    logger.info(
        "DELETE EVENT RECEIVED | chat_id=%s | ids=%s",
        event.chat_id,
        event.deleted_ids
    )

    main = get_main_id()

    if not main:
        return

    # IMPORTANT:
    # Do NOT rely on event.chat_id.
    #
    # We identify MAIN messages through the database mapping.
    # This also handles situations where Telegram doesn't
    # provide chat_id in the deletion update.

    for message_id in event.deleted_ids:

        mappings = get_mappings(
            main,
            message_id
        )

        if not mappings:
            continue

        await delete_copies(
            message_id
        )


# ============================================================
# EDIT FUNCTION
# ============================================================

async def edit_copies(
    source_message
):

    main = get_main_id()

    if not main:
        return

    mappings = get_mappings(
        main,
        source_message.id
    )

    if not mappings:
        return

    text = source_message.raw_text or ""

    logger.info(
        "EDIT SYNC | source=%s | copies=%s",
        source_message.id,
        len(mappings)
    )

    for (
        target_chat_id,
        target_message_id
    ) in mappings:

        try:

            await client.edit_message(
                target_chat_id,
                target_message_id,
                text,
                formatting_entities=source_message.entities
            )

            logger.info(
                "COPY EDITED | target=%s | msg=%s",
                target_chat_id,
                target_message_id
            )

        except FloodWaitError as e:

            await sleep_flood(e)

        except RPCError as e:

            logger.error(
                "EDIT RPC ERROR | %s",
                e
            )

        except Exception as e:

            logger.exception(
                "EDIT ERROR | %s",
                e
            )

        await asyncio.sleep(
            0.2
        )


# ============================================================
# TELEGRAM EDIT EVENT
# ============================================================

@client.on(events.MessageEdited)
async def message_edited_handler(event):

    main = get_main_id()

    if not main:
        return

    if event.chat_id != main:
        return

    message = event.message

    # Ignore commands
    text = message.raw_text or ""

    if text.startswith("/"):
        return

    await edit_copies(
        message
    )


# ============================================================
# BACKUP DELETE WATCHDOG
# ============================================================
#
# This is the important extra protection.
#
# If Telegram sends MessageDeleted:
#       delete immediately
#
# If Telegram DOES NOT send it:
#       this monitor checks known MAIN messages.
#
# If Telegram returns None for the source message:
#       it was deleted
#       ↓
#       delete all copies
#
# ============================================================

async def deletion_watchdog():

    await asyncio.sleep(
        10
    )

    while True:

        try:

            main = get_main_id()

            if not main:

                await asyncio.sleep(
                    DELETE_CHECK_INTERVAL
                )

                continue

            rows = get_known_source_messages()

            if not rows:

                await asyncio.sleep(
                    DELETE_CHECK_INTERVAL
                )

                continue

            source_ids = [
                row[0]
                for row in rows
            ]

            logger.debug(
                "WATCHDOG CHECK | %s messages",
                len(source_ids)
            )

            # Telegram allows requesting multiple IDs.
            messages = await client.get_messages(
                main,
                ids=source_ids
            )

            # For a list request, Telethon returns a list.
            if not isinstance(
                messages,
                list
            ):
                messages = [
                    messages
                ]

            for index, message in enumerate(
                messages
            ):

                if message is not None:
                    continue

                source_id = source_ids[index]

                logger.warning(
                    "WATCHDOG FOUND DELETED MESSAGE | %s",
                    source_id
                )

                await delete_copies(
                    source_id
                )

        except FloodWaitError as e:

            await sleep_flood(e)

        except RPCError as e:

            logger.error(
                "WATCHDOG RPC ERROR: %s",
                e
            )

        except Exception as e:

            logger.exception(
                "WATCHDOG ERROR: %s",
                e
            )

        await asyncio.sleep(
            DELETE_CHECK_INTERVAL
        )


# ============================================================
# START
# ============================================================

async def main():

    global BOT_ID

    init_db()

    logger.info(
        "===================================="
    )

    logger.info(
        "LEX PUBLISHER PRO STARTING"
    )

    logger.info(
        "===================================="
    )

    await client.start(
        bot_token=BOT_TOKEN
    )

    me = await client.get_me()

    BOT_ID = me.id

    logger.info(
        "BOT ID: %s",
        BOT_ID
    )

    logger.info(
        "BOT USERNAME: @%s",
        getattr(
            me,
            "username",
            ""
        )
    )

    logger.info(
        "MAIN ID: %s",
        get_main_id()
    )

    logger.info(
        "TARGETS: %s",
        len(get_targets())
    )

    logger.info(
        "DELETE WATCHDOG: %s seconds",
        DELETE_CHECK_INTERVAL
    )

    print()
    print("====================================")
    print("       LEX PUBLISHER PRO")
    print("====================================")
    print(f"BOT ID  : {BOT_ID}")
    print(
        f"USERNAME: @{getattr(me, 'username', '')}"
    )
    print(
        f"MAIN    : {get_main_id()}"
    )
    print(
        f"TARGETS : {len(get_targets())}"
    )
    print(
        f"DELETE CHECK: {DELETE_CHECK_INTERVAL}s"
    )
    print(
        "STATUS  : ONLINE"
    )
    print("====================================")
    print()

    # Start backup monitor
    asyncio.create_task(
        deletion_watchdog()
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
            "LEX Publisher stopped."
    ) 
