import os
import asyncio
import logging
import sqlite3
from contextlib import closing
from typing import Optional

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, RPCError


# ============================================================
# LEX AUTO PUBLISHER PRO
# ============================================================
#
# MAIN GROUP
#      │
#      ├── Copy → GROUP 1
#      ├── Copy → GROUP 2
#      ├── Copy → GROUP 3
#      └── ...
#
# Delete MAIN message
#      ↓
# Delete all copies
#
# Edit MAIN message
#      ↓
# Edit all copies when possible
#
# ============================================================


# ============================================================
# CONFIG
# ============================================================

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

DB_FILE = os.getenv("DB_FILE", "publisher.db")
SESSION_FILE = os.getenv("SESSION_FILE", "lex_publisher")

if not API_ID:
    raise RuntimeError("API_ID is missing")

if not API_HASH:
    raise RuntimeError("API_HASH is missing")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

if not OWNER_ID:
    raise RuntimeError("OWNER_ID is missing")


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger("LEX-PUBLISHER")


# ============================================================
# DATABASE
# ============================================================

def get_db():
    return sqlite3.connect(
        DB_FILE,
        timeout=30,
        check_same_thread=False
    )


def init_db():

    with closing(get_db()) as conn:

        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS targets (
                chat_id INTEGER PRIMARY KEY,
                title TEXT,
                username TEXT,
                enabled INTEGER DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
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

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_source_message
            ON message_map(
                source_chat_id,
                source_message_id
            )
        """)

        conn.commit()


# ============================================================
# SETTINGS
# ============================================================

def set_setting(key: str, value):

    with closing(get_db()) as conn:

        conn.execute("""
            INSERT INTO settings(key, value)
            VALUES (?, ?)

            ON CONFLICT(key)
            DO UPDATE SET value = excluded.value
        """, (key, str(value)))

        conn.commit()


def get_setting(key: str) -> Optional[str]:

    with closing(get_db()) as conn:

        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,)
        ).fetchone()

        return row[0] if row else None


# ============================================================
# TARGET GROUPS
# ============================================================

def add_target(chat_id, title, username):

    with closing(get_db()) as conn:

        conn.execute("""
            INSERT INTO targets(
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
            "DELETE FROM targets WHERE chat_id = ?",
            (chat_id,)
        )

        conn.commit()


def get_targets():

    with closing(get_db()) as conn:

        return conn.execute("""
            SELECT chat_id, title, username
            FROM targets
            WHERE enabled = 1
            ORDER BY created_at ASC
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
            INSERT OR REPLACE INTO message_map(
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


# ============================================================
# TELEGRAM CLIENT
# ============================================================

client = TelegramClient(
    SESSION_FILE,
    API_ID,
    API_HASH
)


# ============================================================
# OWNER CHECK
# ============================================================

def is_owner(event):

    sender = event.sender_id

    return sender == OWNER_ID


# ============================================================
# GET MAIN CHAT
# ============================================================

def get_main_chat_id():

    value = get_setting("main_chat_id")

    if not value:
        return None

    try:
        return int(value)
    except ValueError:
        return None


# ============================================================
# START
# ============================================================

@client.on(events.NewMessage(pattern=r"^/start$"))
async def start_handler(event):

    if not is_owner(event):
        return

    await event.reply(
        "🤖 LEX Publisher PRO\n\n"
        "البوت خدام.\n\n"

        "الأوامر:\n"
        "/setmain — تعيين القروب الرئيسي\n"
        "/addgroup — إضافة القروب الحالي\n"
        "/removegroup — إزالة القروب الحالي\n"
        "/groups — عرض القروبات\n"
        "/status — حالة النظام\n"
    )


# ============================================================
# SET MAIN
# ============================================================

@client.on(events.NewMessage(pattern=r"^/setmain$"))
async def setmain_handler(event):

    if not is_owner(event):
        return

    chat = await event.get_chat()

    set_setting(
        "main_chat_id",
        chat.id
    )

    await event.reply(
        "✅ تم تعيين هذا القروب كـ MAIN.\n\n"
        f"🆔 `{chat.id}`"
    )


# ============================================================
# ADD GROUP
# ============================================================

@client.on(events.NewMessage(pattern=r"^/addgroup$"))
async def addgroup_handler(event):

    if not is_owner(event):
        return

    chat = await event.get_chat()

    # لا نسمح بإضافة الرئيسي كهدف
    main_id = get_main_chat_id()

    if main_id and chat.id == main_id:

        await event.reply(
            "❌ هذا هو القروب الرئيسي."
        )

        return

    try:

        me = await client.get_me()

        participant = await client.get_permissions(
            chat,
            me
        )

        # إذا لم تكن هناك صلاحيات كافية،
        # سيظهر الخطأ هنا أو عند النشر.
        logger.info(
            "Permissions for %s: %s",
            chat.id,
            participant
        )

    except Exception as exc:

        logger.warning(
            "Permission check failed: %s",
            exc
        )

    username = getattr(
        chat,
        "username",
        None
    )

    title = getattr(
        chat,
        "title",
        ""
    )

    add_target(
        chat.id,
        title,
        username
    )

    await event.reply(
        "✅ تمت إضافة القروب.\n\n"
        f"📌 {title or 'بدون اسم'}\n"
        f"🆔 `{chat.id}`"
    )


# ============================================================
# REMOVE GROUP
# ============================================================

@client.on(events.NewMessage(pattern=r"^/removegroup$"))
async def removegroup_handler(event):

    if not is_owner(event):
        return

    chat = await event.get_chat()

    remove_target(chat.id)

    await event.reply(
        "✅ تم حذف القروب من قائمة النشر."
    )


# ============================================================
# LIST GROUPS
# ============================================================

@client.on(events.NewMessage(pattern=r"^/groups$"))
async def groups_handler(event):

    if not is_owner(event):
        return

    targets = get_targets()

    if not targets:

        await event.reply(
            "📭 لا توجد قروبات مستهدفة."
        )

        return

    text = "📋 القروبات المستهدفة:\n\n"

    for index, (
        chat_id,
        title,
        username
    ) in enumerate(targets, 1):

        text += (
            f"{index}. {title or 'بدون اسم'}\n"
            f"🆔 `{chat_id}`\n"
        )

        if username:
            text += f"🔗 @{username}\n"

        text += "\n"

    await event.reply(text)


# ============================================================
# STATUS
# ============================================================

@client.on(events.NewMessage(pattern=r"^/status$"))
async def status_handler(event):

    if not is_owner(event):
        return

    main_id = get_main_chat_id()
    targets = get_targets()

    await event.reply(
        "🤖 LEX Publisher PRO\n\n"
        f"MAIN: `{main_id or 'غير محدد'}`\n"
        f"TARGETS: `{len(targets)}`\n\n"
        "🟢 النظام يعمل."
    )


# ============================================================
# COPY MESSAGE
# ============================================================

async def copy_message(
    source_chat_id,
    message,
    target_chat_id
):

    try:

        # Telethon يدعم إرسال نسخة بدون
        # Forward header.
        result = await client.forward_messages(
            target_chat_id,
            message,
            from_peer=source_chat_id,
            drop_author=True
        )

        if not result:
            return None

        if isinstance(result, list):
            copied = result[0]
        else:
            copied = result

        return copied.id

    except FloodWaitError as exc:

        logger.warning(
            "FloodWait: sleeping %s seconds",
            exc.seconds
        )

        await asyncio.sleep(
            exc.seconds + 1
        )

        return await copy_message(
            source_chat_id,
            message,
            target_chat_id
        )

    except RPCError as exc:

        logger.error(
            "Telegram RPC error: %s",
            exc
        )

        return None

    except Exception as exc:

        logger.exception(
            "Copy failed: %s",
            exc
        )

        return None


# ============================================================
# MAIN PUBLISHER
# ============================================================

@client.on(events.NewMessage)
async def main_message_handler(event):

    if event.sender_id == (await client.get_me()).id:
        return

    main_id = get_main_chat_id()

    if not main_id:
        return

    if event.chat_id != main_id:
        return

    message = event.message

    # تجاهل أوامر الإدارة
    if message.raw_text:
        if message.raw_text.startswith("/"):
            return

    targets = get_targets()

    if not targets:
        logger.info(
            "MAIN message received but no targets."
        )
        return

    logger.info(
        "MAIN message detected: %s",
        message.id
    )

    for (
        target_chat_id,
        title,
        username
    ) in targets:

        copied_id = await copy_message(
            main_id,
            message,
            target_chat_id
        )

        if copied_id:

            save_mapping(
                main_id,
                message.id,
                target_chat_id,
                copied_id
            )

            logger.info(
                "Copied %s -> %s:%s",
                message.id,
                target_chat_id,
                copied_id
            )

        await asyncio.sleep(0.25)


# ============================================================
# DELETE SYNCHRONIZATION
# ============================================================

@client.on(events.MessageDeleted)
async def deleted_handler(event):

    main_id = get_main_chat_id()

    if not main_id:
        return

    # MessageDeleted event may contain chat_id
    # for channel/supergroup messages.
    if event.chat_id != main_id:
        return

    deleted_ids = event.deleted_ids

    if not deleted_ids:
        return

    logger.info(
        "MAIN deletion detected: %s",
        deleted_ids
    )

    for source_message_id in deleted_ids:

        mappings = get_mappings(
            main_id,
            source_message_id
        )

        if not mappings:
            continue

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
                    "Deleted copy %s from %s",
                    target_message_id,
                    target_chat_id
                )

            except FloodWaitError as exc:

                logger.warning(
                    "Delete FloodWait: %s",
                    exc.seconds
                )

                await asyncio.sleep(
                    exc.seconds + 1
                )

            except RPCError as exc:

                logger.error(
                    "Delete error: %s",
                    exc
                )

            except Exception as exc:

                logger.exception(
                    "Delete copy failed: %s",
                    exc
                )

        delete_mappings(
            main_id,
            source_message_id
        )


# ============================================================
# EDIT SYNCHRONIZATION
# ============================================================

@client.on(events.MessageEdited)
async def edited_handler(event):

    main_id = get_main_chat_id()

    if not main_id:
        return

    if event.chat_id != main_id:
        return

    message = event.message

    mappings = get_mappings(
        main_id,
        message.id
    )

    if not mappings:
        return

    logger.info(
        "MAIN message edited: %s",
        message.id
    )

    # النصوص يمكن تعديلها مباشرة.
    # للوسائط، Telegram قد يحتاج إعادة نشر
    # حسب نوع التعديل.
    for (
        target_chat_id,
        target_message_id
    ) in mappings:

        try:

            if message.message is not None:

                await client.edit_message(
                    target_chat_id,
                    target_message_id,
                    message.message,
                    formatting_entities=message.entities
                )

                logger.info(
                    "Edited copy %s in %s",
                    target_message_id,
                    target_chat_id
                )

        except FloodWaitError as exc:

            logger.warning(
                "Edit FloodWait: %s",
                exc.seconds
            )

            await asyncio.sleep(
                exc.seconds + 1
            )

        except RPCError as exc:

            logger.error(
                "Edit error: %s",
                exc
            )

        except Exception as exc:

            logger.exception(
                "Edit copy failed: %s",
                exc
            )


# ============================================================
# START CLIENT
# ============================================================

async def main():

    init_db()

    logger.info(
        "Starting LEX Publisher..."
    )

    await client.start(
        bot_token=BOT_TOKEN
    )

    me = await client.get_me()

    logger.info(
        "Logged in as @%s (%s)",
        getattr(me, "username", None),
        me.id
    )

    logger.info(
        "MAIN = %s",
        get_main_chat_id()
    )

    logger.info(
        "TARGETS = %s",
        len(get_targets())
    )

    print(
        "\n"
        "====================================\n"
        "      LEX PUBLISHER PRO\n"
        "====================================\n"
        f"BOT ID: {me.id}\n"
        f"USERNAME: @{getattr(me, 'username', '')}\n"
        f"MAIN: {get_main_chat_id()}\n"
        f"TARGETS: {len(get_targets())}\n"
        "STATUS: ONLINE\n"
        "====================================\n"
    )

    await client.run_until_disconnected()


if __name__ == "__main__":

    try:
        asyncio.run(main())

    except KeyboardInterrupt:

        logger.info(
            "LEX Publisher stopped."
        )
