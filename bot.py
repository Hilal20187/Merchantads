import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from flask import Flask
import threading

TOKEN = os.getenv("BOT_TOKEN")

# ==================== (تعديل المتغيرات هنا حسب رغبتك) ====================
# معرفات الأشخاص المسموح لهم فقط بنشر الإعلانات أو التحكم
AUTHORIZED_USER_IDS = [822007358, 2065539959]

# معرف مجموعة الإدارة الخاص بك
ADMIN_GROUP_ID = -1003963584914

# المجموعات المستهدفة للنشر
TARGET_GROUP_IDS = [-1003952714985, -1002470205630, -1004407774851]
# =========================================================================

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

async def handle_announcement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    message = update.effective_message
    
    if not chat or not message:
        return

    user = update.effective_user
    if not user or user.id not in AUTHORIZED_USER_IDS:
        return

    text = message.text or message.caption or ""

    # معالجة أمر الحذف /del (سواء كتب وحده أو متبوعاً بمعرف البوت)
    if text.strip().startswith('/del'):
        try:
            if message.reply_to_message:
                await context.bot.delete_message(chat_id=chat.id, message_id=message.reply_to_message.message_id)
            await context.bot.delete_message(chat_id=chat.id, message_id=message.message_id)
            logging.info("تم تنفيذ أمر الحذف بنجاح.")
        except Exception as e:
            logging.error(f"فشل تنفيذ أمر الحذف: {e}")
        return

    # منطق نشر الإعلانات (يقتصر حصرياً على مجموعة الإدارة)
    if chat.id != ADMIN_GROUP_ID:
        return

    text_to_send = message.text or message.caption
    photo = message.photo

    for group_id in TARGET_GROUP_IDS:
        try:
            if photo:
                await context.bot.send_photo(
                    chat_id=group_id,
                    photo=photo[-1].file_id,
                    caption=text_to_send or ""
                )
            elif text_to_send:
                await context.bot.send_message(
                    chat_id=group_id,
                    text=text_to_send
                )
            logging.info(f"تم بنجاح نشر الإعلان في المجموعة: {group_id}")
        except Exception as e:
            logging.error(f"فشل النشر إلى المجموعة {group_id}: {e}")

def run_bot():
    if not TOKEN:
        print("خطأ: لم يتم العثور على BOT_TOKEN!")
        return
    
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(MessageHandler(filters.ALL, handle_announcement))
    
    print("البوت يعمل ويتلتقط كافة الرسائل والأوامر الآن...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

app = Flask(__name__)

@app.route('/')
def home():
    return "البوت يعمل بنجاح!"

def run_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    run_server()
 
