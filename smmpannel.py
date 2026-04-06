import logging
import re
import time
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- TOKENS AND IDS (HARDcoded as requested) ---
MAIN_BOT_TOKEN = "8760884392:AAEUE_pGnAeif-XWEcunLXI8TKZaiaxxtzs"
ADMIN_BOT_TOKEN = "8760415886:AAH-JhrbqKGtfyc_-zJ4ewGedle2Q-vvJj0"
ADMIN_CHAT_ID = "8598993143"

# --- SERVICES LIST ---
SERVICES = ["Followers", "Views", "Likes"]

# Rate limiting storage
user_requests = {}
MAX_REQUESTS_PER_HOUR = 3

# Conversation states
CHOOSING_SERVICE, ENTERING_LINK, ENTERING_QUANTITY, WAITING_FOR_PAYMENT = range(4)

def rate_limit_check(user_id: int) -> bool:
    """Rate limiting - max 3 requests per hour per user."""
    now = int(time.time())
    if user_id not in user_requests:
        user_requests[user_id] = []
    
    # Clean old requests (1 hour = 3600 seconds)
    user_requests[user_id] = [t for t in user_requests[user_id] if now - t < 3600]
    
    if len(user_requests[user_id]) >= MAX_REQUESTS_PER_HOUR:
        return False
    
    user_requests[user_id].append(now)
    return True

def is_valid_url(url: str) -> bool:
    """Validate URL format."""
    url = url.strip()
    pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain
        r'localhost|'  # localhost
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # IP
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S*)$', re.IGNORECASE)
    return bool(pattern.match(url))

def calculate_total_price(service: str, quantity: int) -> tuple[float, str]:
    """Calculates price with limits and validation."""
    MAX_QUANTITIES = {
        "Followers": 50000,
        "Views": 1000000,
        "Likes": 50000
    }
    
    max_qty = MAX_QUANTITIES.get(service, 10000)
    if quantity > max_qty:
        return 0.0, f"❌ Max {max_qty:,} for {service}"
    
    if service == "Followers":
        if quantity >= 20000:
            rate_per_k = 42.5
        elif quantity >= 10000:
            rate_per_k = 50.0
        elif quantity >= 5000:
            rate_per_k = 50.0
        else:
            rate_per_k = 60.0
        return (quantity / 1000) * rate_per_k, "✅"
    
    elif service == "Views":
        return (quantity / 1000) * 3.0, "✅"
    
    elif service == "Likes":
        return (quantity / 1000) * 40.0, "✅"
    
    return 0.0, "❌ Invalid service"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Enhanced start with rate limiting."""
    user_id = update.effective_user.id
    
    if not rate_limit_check(user_id):
        await update.message.reply_text(
            f"⏳ Too many requests. Wait 1 hour (Max {MAX_REQUESTS_PER_HOUR}/hour)"
        )
        return ConversationHandler.END
    
    reply_keyboard = [[service] for service in SERVICES]
    markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    
    welcome_text = (
        "🔥 *Welcome to SocialBoostPro*! 🚀\n\n"
        "✨ *Fast • Safe • Reliable*\n\n"
        f"📊 *Limits:*\n"
        f"• Followers: Max 50K\n"
        f"• Views: Max 1M\n"
        f"• Likes: Max 50K\n\n"
        "Choose service:"
    )
    
    await update.message.reply_text(welcome_text, reply_markup=markup, parse_mode="Markdown")
    return CHOOSING_SERVICE

async def choose_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Service selection with validation."""
    service = update.message.text.strip()
    
    if service not in SERVICES:
        await update.message.reply_text(
            "❌ Invalid service. Choose from keyboard below:",
            reply_markup=ReplyKeyboardMarkup([[s] for s in SERVICES], resize_keyboard=True)
        )
        return CHOOSING_SERVICE
        
    context.user_data['service'] = service
    await update.message.reply_text(
        f"✅ Selected: **{service}**\n\n"
        "📎 Enter target link:\n"
        "*Profile URL / Video Link*",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="Markdown"
    )
    return ENTERING_LINK

async def enter_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Enhanced URL validation."""
    link = update.message.text.strip()
    
    if len(link) > 2000:  # Telegram max message length protection
        await update.message.reply_text("❌ Link too long (max 2000 chars)")
        return ENTERING_LINK
    
    if not is_valid_url(link):
        await update.message.reply_text(
            "❌ Invalid URL!\n"
            "✅ Use: `https://example.com/post/123`\n"
            "✅ Or: `http://t.me/username`",
            parse_mode="Markdown"
        )
        return ENTERING_LINK
    
    context.user_data['link'] = link
    await update.message.reply_text(
        f"✅ Link saved: `{link[:50]}...`\n\n"
        "🔢 Enter quantity (min 100):\n"
        "*Numbers only*",
        parse_mode="Markdown"
    )
    return ENTERING_QUANTITY

async def enter_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Enhanced quantity validation with pricing."""
    quantity_text = update.message.text.strip()
    
    if not quantity_text.isdigit():
        await update.message.reply_text("❌ Enter numbers only (e.g. `5000`)")
        return ENTERING_QUANTITY
        
    quantity = int(quantity_text)
    
    if quantity < 100:
        await update.message.reply_text("❌ Minimum 100")
        return ENTERING_QUANTITY
    
    service = context.user_data['service']
    total_cost, status = calculate_total_price(service, quantity)
    
    if status != "✅":
        await update.message.reply_text(status)
        return ENTERING_QUANTITY
    
    context.user_data.update({
        'quantity': quantity,
        'total_cost': total_cost
    })
    
    # Format numbers with commas
    summary = (
        f"📊 *ORDER SUMMARY* 📊\n\n"
        f"🛒 **{service}**\n"
        f"🔗 `{context.user_data['link'][:50]}...`\n"
        f"🔢 **{quantity:,}**\n"
        f"💰 *₹{total_cost:.2f}*\n\n"
        f"💳 Scan QR → Send payment **screenshot**"
    )
    
    try:
        with open('qrcode.png', 'rb') as qr_photo:
            await update.message.reply_photo(
                photo=qr_photo, 
                caption=summary,
                parse_mode="Markdown"
            )
    except FileNotFoundError:
        logger.error("qrcode.png not found")
        await update.message.reply_text(
            "⚠️ *Payment QR unavailable*\nContact @admin",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    return WAITING_FOR_PAYMENT

async def receive_payment_ss(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Enhanced payment handler with retry logic."""
    user = update.effective_user
    
    if not update.message.photo:
        await update.message.reply_text(
            "📸 Upload **payment screenshot only**",
            parse_mode="Markdown"
        )
        return WAITING_FOR_PAYMENT
        
    photo_file_id = update.message.photo[-1].file_id
    
    # Customer confirmation
    await update.message.reply_text(
        "✅ *Payment received!*\n\n"
        "🔄 Verifying... (1-5 mins)\n"
        "📦 Order processing soon!",
        parse_mode="Markdown"
    )
    
    # Admin notification
    order_data = context.user_data
    admin_msg = (
        f"🚨 *NEW ORDER* 🚨\n\n"
        f"👤 {user.first_name or ''} @{user.username or 'N/A'} (ID: `{user.id}`)\n"
        f"⏰ {time.strftime('%Y-%m-%d %H:%M')}\n\n"
        f"🛒 **{order_data['service']}**\n"
        f"🔗 {order_data['link']}\n"
        f"🔢 {order_data['quantity']:,}\n"
        f"💰 ₹{order_data['total_cost']:.2f}\n"
        f"📸 Payment attached"
    )
    
    admin_bot = Bot(token=ADMIN_BOT_TOKEN)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            await admin_bot.send_photo(
                chat_id=ADMIN_CHAT_ID,
                photo=photo_file_id,
                caption=admin_msg,
                parse_mode="Markdown"
            )
            logger.info(f"Order forwarded to admin from user {user.id}")
            break
        except Exception as e:
            logger.error(f"Admin send attempt {attempt+1} failed: {e}")
            if attempt == max_retries - 1:
                logger.error("Failed to notify admin after all retries")
    
    # Clear user data
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Improved cancel handler."""
    await update.message.reply_text(
        "❌ Order cancelled\n\n"
        "🔄 /start for new order",
        reply_markup=ReplyKeyboardRemove()
    )
    if context.user_data:
        context.user_data.clear()
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global error handler."""
    logger.error(f"Update {update} caused error {context.error}")
    
    if update and hasattr(update, 'message') and update.message:
        try:
            await update.message.reply_text(
                "⚠️ System error occurred\n"
                "Try /start again or contact support"
            )
        except:
            pass

def main() -> None:
    """Enhanced main function."""
    try:
        application = Application.builder().token(MAIN_BOT_TOKEN).build()

        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start)],
            states={
                CHOOSING_SERVICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_service)],
                ENTERING_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_link)],
                ENTERING_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_quantity)],
                WAITING_FOR_PAYMENT: [MessageHandler(filters.PHOTO, receive_payment_ss)],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
        )

        application.add_handler(conv_handler)
        application.add_error_handler(error_handler)

        logger.info("🚀 SocialBoostPro Bot starting...")
        print("🤖 Bot running... Press Ctrl+C to stop")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")

if __name__ == "__main__":
    main()