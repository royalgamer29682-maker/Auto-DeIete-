import os
import asyncio
import sqlite3
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
DB_FILE = "bot.db"
DEFAULT_DELETE_TIME = 60

def db():
    return sqlite3.connect(DB_FILE)

def init_db():
    con = db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS groups_data (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            enabled INTEGER DEFAULT 1,
            delete_time INTEGER DEFAULT 60
        )
    """)
    con.commit()
    con.close()

def add_group(chat_id, title):
    con = db()
    con.execute("""
        INSERT OR IGNORE INTO groups_data
        (chat_id, title, enabled, delete_time)
        VALUES (?, ?, 1, ?)
    """, (chat_id, title, DEFAULT_DELETE_TIME))
    con.commit()
    con.close()

def update_group(chat_id, enabled=None, delete_time=None):
    con = db()
    if enabled is not None:
        con.execute("UPDATE groups_data SET enabled=? WHERE chat_id=?", (enabled, chat_id))
    if delete_time is not None:
        con.execute("UPDATE groups_data SET delete_time=? WHERE chat_id=?", (delete_time, chat_id))
    con.commit()
    con.close()

def get_group(chat_id):
    con = db()
    result = con.execute(
        "SELECT enabled, delete_time FROM groups_data WHERE chat_id=?", (chat_id,)
    ).fetchone()
    con.close()
    return result

def get_all_groups():
    con = db()
    result = con.execute("SELECT chat_id, title FROM groups_data").fetchall()
    con.close()
    return result

async def is_admin(update, context):
    try:
        member = await context.bot.get_chat_member(
            update.effective_chat.id, update.effective_user.id
        )
        return member.status in ("administrator", "creator")
    except Exception:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Auto Delete Bot\n\n"
        "मुझे अपने ग्रुप में Admin बनाइए।\n\n"
        "/on - Auto Delete ON\n"
        "/off - Auto Delete OFF\n"
        "/settime 60 - 60 सेकंड\n"
        "/status - वर्तमान सेटिंग"
    )

async def my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.my_chat_member.chat
    if chat.type not in ("group", "supergroup"):
        return

    status = update.my_chat_member.new_chat_member.status
    if status in ("administrator", "member"):
        add_group(chat.id, chat.title or "Unknown Group")
        try:
            await context.bot.send_message(
                chat.id,
                "✅ Auto Delete Bot सक्रिय है!\n\n"
                "Default timer: 60 सेकंड\n\n"
                "/on\n/off\n/settime 60\n/status"
            )
        except Exception:
            pass

async def on_command(update, context):
    if update.effective_chat.type not in ("group", "supergroup"):
        return
    if not await is_admin(update, context):
        return
    update_group(update.effective_chat.id, enabled=1)
    await update.message.reply_text("✅ Auto Delete ON")

async def off_command(update, context):
    if update.effective_chat.type not in ("group", "supergroup"):
        return
    if not await is_admin(update, context):
        return
    update_group(update.effective_chat.id, enabled=0)
    await update.message.reply_text("❌ Auto Delete OFF")

async def settime_command(update, context):
    if update.effective_chat.type not in ("group", "supergroup"):
        return
    if not await is_admin(update, context):
        return
    if not context.args:
        await update.message.reply_text("उदाहरण: /settime 60")
        return
    try:
        seconds = int(context.args[0])
        if seconds < 5:
            await update.message.reply_text("कम से कम 5 सेकंड रखें।")
            return
        if seconds > 172800:
            await update.message.reply_text("अधिकतम 48 घंटे रखें।")
            return
        update_group(update.effective_chat.id, delete_time=seconds)
        await update.message.reply_text(f"✅ Delete time: {seconds} सेकंड")
    except ValueError:
        await update.message.reply_text("सही format: /settime 60")

async def status_command(update, context):
    if update.effective_chat.type not in ("group", "supergroup"):
        return
    if not await is_admin(update, context):
        return
    data = get_group(update.effective_chat.id)
    if not data:
        await update.message.reply_text("Bot की setting नहीं मिली।")
        return
    enabled, delete_time = data
    await update.message.reply_text(
        f"Status: {'ON ✅' if enabled else 'OFF ❌'}\n"
        f"Delete Time: {delete_time} seconds"
    )

async def delete_later(context):
    job = context.job
    try:
        await context.bot.delete_message(
            chat_id=job.data["chat_id"],
            message_id=job.data["message_id"]
        )
    except Exception:
        pass

async def message_handler(update, context):
    if not update.message:
        return
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        return

    data = get_group(chat.id)
    if not data:
        return

    enabled, delete_time = data
    if not enabled:
        return

    context.job_queue.run_once(
        delete_later,
        delete_time,
        data={"chat_id": chat.id, "message_id": update.message.message_id}
    )

async def stats_command(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    groups = get_all_groups()
    text = f"📊 Total Groups: {len(groups)}\n\n"
    for i, (_, title) in enumerate(groups, 1):
        text += f"{i}. {title}\n"
    await update.message.reply_text(text[:4096])

async def broadcast_command(update, context):
    if update.effective_user.id != OWNER_ID:
        return
    if not update.message.reply_to_message:
        await update.message.reply_text(
            "जिस message को broadcast करना है, उसके ऊपर /broadcast reply करें।"
        )
        return

    groups = get_all_groups()
    success = failed = 0

    for chat_id, _ in groups:
        try:
            await context.bot.copy_message(
                chat_id=chat_id,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.reply_to_message.message_id
            )
            success += 1
            await asyncio.sleep(0.1)
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"📢 Broadcast Complete\n\n✅ Success: {success}\n❌ Failed: {failed}"
    )

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN missing")

    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("on", on_command))
    app.add_handler(CommandHandler("off", off_command))
    app.add_handler(CommandHandler("settime", settime_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))

    app.add_handler(
        MessageHandler(filters.StatusUpdate.ALL, my_chat_member)
    )
    app.add_handler(
        MessageHandler(filters.ALL & ~filters.COMMAND, message_handler)
    )

    print("Bot Started...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
