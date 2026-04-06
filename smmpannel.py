import logging
import re
import time
import os
from flask import Flask
from threading import Thread
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
)

# --- FLASK SERVER FOR RENDER (KEEP-ALIVE) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    # Render provides the PORT environment variable automatically
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()

# --- BOT LOGIC ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# HARDCODED TOKENS (As requested)
MAIN_BOT_TOKEN = "8760884392:AAEUE_pGnAeif-XWEcunLXI8TKZaiaxxtzs"
ADMIN_CHAT_ID = 8598993143  # Your numeric Telegram ID

SERVICES = ["Followers", "Views", "Likes"]
user_requests = {}
MAX_REQUESTS_PER_HOUR = 3

CHOOSING_SERVICE, ENTERING_LINK, ENTERING_QUANTITY, WAITING_FOR_PAYMENT = range(4)

def rate_limit_check(user_id: int) -> bool:
    now = int(time.time())
    if user_id not in user_requests:
        user_requests[user_id] = []
    user_requests[user_id] = [t for t in user_requests[user_id] if now - t < 3600]
    if len(user_requests[user_id]) >= MAX_REQUESTS_PER_HOUR:
        return False
    user_requests[user_id].append(now)
    return True

def is_valid_url(url: str) -> bool:
    pattern = re.compile(r'^https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+', re.IGNORECASE)
    return bool(pattern.match(url))

def calculate_total_price(service: str, quantity: int) -> tuple[float, str]:
    limits = {"Followers": 50000, "Views": 1000000, "Likes": 50000}
    max_qty = limits.get(service, 10000)
    if quantity > max_qty:
        return 0.0, f"❌ Max {max_qty:,} for {service}"
    
    if service == "Followers":
        rate = 42.5 if quantity >= 20000 else 50.0 if quantity >= 5000 else 60.0
        return (quantity / 1000) * rate, "✅"
    elif service == "Views":
        return (quantity / 1000) * 3.0, "✅"
    elif service == "Likes":
        return (quantity / 1000) * 40.0, "✅"
    return 0.0, "❌ Invalid service"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not rate_limit_check(update.effective_user.id):
        await update.message.reply_text(f"⏳ Wait 1 hour (Max {MAX_REQUESTS_PER_HOUR}/hr)")
        return ConversationHandler.END
    
    markup = ReplyKeyboardMarkup([[s] for s in SERVICES], one_time_keyboard=True, resize_keyboard=True)
    await update.message.reply_text("🔥 *Welcome to SocialBoostPro*!\n\nChoose service:", reply_markup=markup, parse_mode="Markdown")
    return CHOOSING_SERVICE

async def choose_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    service = update.message.text.strip()
    if service not in SERVICES:
        return CHOOSING_SERVICE
    context.user_data['service'] = service
    await update.message.reply_text(f"✅ Selected: **{service}**\nEnter target link:", reply_markup=ReplyKeyboardRemove(), parse_mode="Markdown")
    return ENTERING_LINK

async def enter_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    link = update.message.text.strip()
    if not is_valid_url(link):
        await update.message.reply_text("❌ Invalid URL! Try again.")
        return ENTERING_LINK
    context.user_data['link'] = link
    await update.message.reply_text("🔢 Enter quantity (min 100):", parse_mode="Markdown")
    return ENTERING_QUANTITY

async def enter_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    qty_text = update.message.text.strip()
    if not qty_text.isdigit() or int(qty_text) < 100:
        await update.message.reply_text("❌ Minimum 100 (Numbers only)")
        return ENTERING_QUANTITY
        
    qty = int(qty_text)
    cost, status = calculate_total_price(context.user_data['service'], qty)
    if status != "✅":
        await update.message.reply_text(status)
        return ENTERING_QUANTITY
    
    context.user_data.update({'quantity': qty, 'total_cost': cost})
    summary = f"📊 *ORDER SUMMARY*\n\n🛒 {context.user_data['service']}\n🔗 `{link[:30]}...`\n🔢 {qty:,}\n💰 *₹{cost:.2f}*\n\n💳 Send payment screenshot:"
    
    try:
        await update.message.reply_photo(photo=open('qrcode.png', 'rb'), caption=summary, parse_mode="Markdown")
    except:
        await update.message.reply_text(f"{summary}\n\n⚠️ QR Error. Contact admin.")
    return WAITING_FOR_PAYMENT

async def receive_payment_ss(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message.photo:
        await update.message.reply_text("📸 Send a screenshot.")
        return WAITING_FOR_PAYMENT
        
    # Send confirmation to user
    await update.message.reply_text("✅ *Payment received!* Verifying now...", parse_mode="Markdown")
    
    # Forward to Admin
    order = context.user_data
    user = update.effective_user
    admin_msg = (
        f"🚨 *NEW ORDER*\nUser: {user.first_name} (@{user.username})\n"
        f"Service: {order['service']}\nLink: {order['link']}\n"
        f"Qty: {order['quantity']:,}\nPrice: ₹{order['total_cost']:.2f}"
    )
    
    try:
        await context.bot.send_photo(chat_id=ADMIN_CHAT_ID, photo=update.message.photo[-1].file_id, caption=admin_msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Admin forward failed: {e}")

    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

def main():
    keep_alive() # Start the Flask server
    app_bot = Application.builder().token(MAIN_BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            CHOOSING_SERVICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_service)],
            ENTERING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_link)],
            ENTERING_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_quantity)],
            WAITING_FOR_PAYMENT: [MessageHandler(filters.PHOTO, receive_payment_ss)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app_bot.add_handler(conv)
    app_bot.run_polling()

if __name__ == "__main__":
    main()
