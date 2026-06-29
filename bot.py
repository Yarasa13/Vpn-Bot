import os
import json
import logging
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "123456789").split(",")))  # آیدی عددی ادمین‌ها
CARD_NUMBER = os.getenv("CARD_NUMBER", "6037-XXXX-XXXX-XXXX")
CARD_OWNER = os.getenv("CARD_OWNER", "نام صاحب کارت")
PRICE_PER_GB = 4000  # تومان

DB_FILE = "db.json"

# ─── Conversation States ───────────────────────────────────────────────────────
(
    MAIN_MENU, BUY_GB, BUY_DURATION, BUY_CONFIRM, BUY_RECEIPT,
    WALLET_MENU, WALLET_AMOUNT, WALLET_RECEIPT,
    SUPPORT_MSG,
    ADMIN_MENU, ADMIN_CHARGE_USER, ADMIN_CHARGE_AMOUNT
) = range(12)

# ─── Database ─────────────────────────────────────────────────────────────────
def load_db():
    if not os.path.exists(DB_FILE):
        return {"users": {}, "orders": [], "pending_wallets": []}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def get_user(db, uid):
    uid = str(uid)
    if uid not in db["users"]:
        db["users"][uid] = {"balance": 0, "orders": [], "username": ""}
    return db["users"][uid]

# ─── Keyboards ────────────────────────────────────────────────────────────────
def main_keyboard():
    return ReplyKeyboardMarkup([
        ["🛒 خرید سرویس جدید", "📋 سرویس‌های من"],
        ["💰 کیف پول", "👤 حساب کاربری"],
        ["📞 پشتیبانی"]
    ], resize_keyboard=True)

def admin_keyboard():
    return ReplyKeyboardMarkup([
        ["👥 کاربران", "📦 سفارشات"],
        ["💳 شارژ کیف پول کاربر", "📊 آمار"],
        ["🔙 خروج از پنل ادمین"]
    ], resize_keyboard=True)

# ─── /start ───────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db = load_db()
    user = get_user(db, uid)
    user["username"] = update.effective_user.username or ""
    save_db(db)

    name = update.effective_user.first_name or "کاربر"
    await update.message.reply_text(
        f"🔒 به فروشگاه VPN خوش آمدید، {name} عزیز!\n\n"
        "از منوی زیر گزینه مورد نظر را انتخاب کنید:",
        reply_markup=main_keyboard()
    )
    return MAIN_MENU

# ─── Buy Flow ─────────────────────────────────────────────────────────────────
async def buy_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📡 *خرید سرویس VPN*\n\n"
        f"💵 قیمت: *{PRICE_PER_GB:,} تومان* به ازای هر گیگابایت\n\n"
        f"چند گیگابایت می‌خواهید؟\n"
        f"_(مثال: 10، 20، 50)_",
        parse_mode="Markdown"
    )
    return BUY_GB

async def buy_gb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("❌ لطفاً یک عدد صحیح مثبت وارد کنید:")
        return BUY_GB

    context.user_data["gb"] = int(text)
    await update.message.reply_text(
        f"⏳ مدت زمان سرویس را وارد کنید:\n"
        f"_(بین ۳۰ تا ۹۰ روز - مثال: 30، 60، 90)_",
        parse_mode="Markdown"
    )
    return BUY_DURATION

async def buy_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit() or not (30 <= int(text) <= 90):
        await update.message.reply_text("❌ لطفاً عددی بین ۳۰ تا ۹۰ وارد کنید:")
        return BUY_DURATION

    gb = context.user_data["gb"]
    days = int(text)
    total = gb * PRICE_PER_GB
    context.user_data["days"] = days
    context.user_data["total"] = total

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأیید و پرداخت", callback_data="buy_confirm")],
        [InlineKeyboardButton("❌ انصراف", callback_data="cancel")]
    ])
    await update.message.reply_text(
        f"📋 *خلاصه سفارش:*\n\n"
        f"📦 حجم: *{gb} گیگابایت*\n"
        f"📅 مدت: *{days} روز*\n"
        f"💰 مبلغ: *{total:,} تومان*\n\n"
        "آیا تأیید می‌کنید؟",
        parse_mode="Markdown", reply_markup=kb
    )
    return BUY_CONFIRM

async def buy_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ سفارش لغو شد.")
        await query.message.reply_text("به منوی اصلی بازگشتید.", reply_markup=main_keyboard())
        return MAIN_MENU

    uid = query.from_user.id
    db = load_db()
    user = get_user(db, uid)
    total = context.user_data["total"]

    if user["balance"] >= total:
        # پرداخت از کیف پول
        user["balance"] -= total
        order_id = len(db["orders"]) + 1
        order = {
            "id": order_id, "user_id": str(uid),
            "gb": context.user_data["gb"], "days": context.user_data["days"],
            "total": total, "status": "pending_activation",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        db["orders"].append(order)
        user["orders"].append(order_id)
        save_db(db)

        await query.edit_message_text(
            f"✅ *پرداخت موفق از کیف پول*\n\n"
            f"🆔 شماره سفارش: `#{order_id}`\n"
            f"📦 {context.user_data['gb']} گیگابایت | {context.user_data['days']} روز\n"
            f"💰 {total:,} تومان از کیف پول کسر شد\n\n"
            f"⏳ سرویس شما در حال آماده‌سازی است. ادمین به زودی اطلاع می‌دهد.",
            parse_mode="Markdown"
        )
        # اطلاع به ادمین
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    admin_id,
                    f"🛒 *سفارش جدید #{order_id}*\n"
                    f"👤 کاربر: {query.from_user.first_name} | ID: `{uid}`\n"
                    f"📦 {context.user_data['gb']} GB | {context.user_data['days']} روز\n"
                    f"💰 {total:,} تومان (از کیف پول)\n"
                    f"📅 {order['date']}",
                    parse_mode="Markdown"
                )
            except:
                pass
        return MAIN_MENU
    else:
        need = total - user["balance"]
        save_db(db)
        context.user_data["order_pending"] = True
        await query.edit_message_text(
            f"💳 *پرداخت کارت به کارت*\n\n"
            f"💰 مبلغ: *{total:,} تومان*\n"
            f"🏦 شماره کارت:\n`{CARD_NUMBER}`\n"
            f"👤 به نام: *{CARD_OWNER}*\n\n"
            f"پس از واریز، **تصویر رسید** را ارسال کنید:",
            parse_mode="Markdown"
        )
        return BUY_RECEIPT

async def buy_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("📷 لطفاً تصویر رسید پرداخت را ارسال کنید:")
        return BUY_RECEIPT

    uid = update.effective_user.id
    db = load_db()
    order_id = len(db["orders"]) + 1
    order = {
        "id": order_id, "user_id": str(uid),
        "gb": context.user_data["gb"], "days": context.user_data["days"],
        "total": context.user_data["total"], "status": "pending_payment",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    db["orders"].append(order)
    user = get_user(db, uid)
    user["orders"].append(order_id)
    save_db(db)

    await update.message.reply_text(
        f"✅ رسید شما دریافت شد!\n\n"
        f"🆔 شماره سفارش: `#{order_id}`\n"
        f"⏳ در حال بررسی توسط ادمین...",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )

    # ارسال رسید به ادمین
    photo_id = update.message.photo[-1].file_id
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_photo(
                admin_id, photo_id,
                caption=f"💳 *رسید سفارش #{order_id}*\n"
                        f"👤 {update.effective_user.first_name} | ID: `{uid}`\n"
                        f"📦 {context.user_data['gb']} GB | {context.user_data['days']} روز\n"
                        f"💰 {context.user_data['total']:,} تومان\n\n"
                        f"برای تأیید: /approve_{order_id}\n"
                        f"برای رد: /reject_{order_id}",
                parse_mode="Markdown"
            )
        except:
            pass
    return MAIN_MENU

# ─── Wallet Flow ──────────────────────────────────────────────────────────────
async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db = load_db()
    user = get_user(db, uid)
    save_db(db)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ شارژ کیف پول", callback_data="wallet_charge")]
    ])
    await update.message.reply_text(
        f"💰 *کیف پول شما*\n\n"
        f"💵 موجودی: *{user['balance']:,} تومان*",
        parse_mode="Markdown", reply_markup=kb
    )
    return WALLET_MENU

async def wallet_charge_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        f"💳 *شارژ کیف پول*\n\n"
        f"چه مبلغی می‌خواهید واریز کنید؟\n"
        f"_(مثال: 50000، 100000)_ تومان",
        parse_mode="Markdown"
    )
    return WALLET_AMOUNT

async def wallet_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", "")
    if not text.isdigit() or int(text) < 10000:
        await update.message.reply_text("❌ حداقل مبلغ ۱۰,۰۰۰ تومان است:")
        return WALLET_AMOUNT

    amount = int(text)
    context.user_data["wallet_amount"] = amount
    await update.message.reply_text(
        f"💳 *اطلاعات پرداخت*\n\n"
        f"💰 مبلغ: *{amount:,} تومان*\n"
        f"🏦 شماره کارت:\n`{CARD_NUMBER}`\n"
        f"👤 به نام: *{CARD_OWNER}*\n\n"
        f"پس از واریز، **تصویر رسید** را ارسال کنید:",
        parse_mode="Markdown"
    )
    return WALLET_RECEIPT

async def wallet_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("📷 لطفاً تصویر رسید را ارسال کنید:")
        return WALLET_RECEIPT

    uid = update.effective_user.id
    amount = context.user_data["wallet_amount"]
    db = load_db()
    pending = {
        "user_id": str(uid), "amount": amount,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "id": len(db["pending_wallets"]) + 1
    }
    db["pending_wallets"].append(pending)
    save_db(db)

    await update.message.reply_text(
        f"✅ رسید شارژ کیف پول دریافت شد!\n"
        f"💰 مبلغ: {amount:,} تومان\n"
        f"⏳ پس از تأیید ادمین، موجودی شما افزایش می‌یابد.",
        reply_markup=main_keyboard()
    )

    photo_id = update.message.photo[-1].file_id
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_photo(
                admin_id, photo_id,
                caption=f"💰 *درخواست شارژ کیف پول*\n"
                        f"👤 {update.effective_user.first_name} | ID: `{uid}`\n"
                        f"💵 مبلغ: {amount:,} تومان\n\n"
                        f"برای تأیید: /addbalance_{uid}_{amount}",
                parse_mode="Markdown"
            )
        except:
            pass
    return MAIN_MENU

# ─── My Services ──────────────────────────────────────────────────────────────
async def my_services(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db = load_db()
    user = get_user(db, uid)
    save_db(db)

    if not user["orders"]:
        await update.message.reply_text("📭 هنوز سرویسی خریداری نکرده‌اید.")
        return MAIN_MENU

    orders = [o for o in db["orders"] if o["id"] in user["orders"]]
    text = "📋 *سرویس‌های شما:*\n\n"
    for o in orders[-5:]:  # آخرین ۵ سفارش
        status_map = {
            "pending_payment": "⏳ در انتظار تأیید پرداخت",
            "pending_activation": "⚙️ در حال فعال‌سازی",
            "active": "✅ فعال",
            "rejected": "❌ رد شده"
        }
        status = status_map.get(o["status"], o["status"])
        text += f"🆔 #{o['id']} | {o['gb']}GB | {o['days']}روز\n{status}\n📅 {o['date']}\n\n"

    await update.message.reply_text(text, parse_mode="Markdown")
    return MAIN_MENU

# ─── Account ──────────────────────────────────────────────────────────────────
async def account_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db = load_db()
    user = get_user(db, uid)
    save_db(db)

    await update.message.reply_text(
        f"👤 *حساب کاربری*\n\n"
        f"🆔 آیدی: `{uid}`\n"
        f"💰 موجودی: {user['balance']:,} تومان\n"
        f"📦 تعداد سفارشات: {len(user['orders'])}",
        parse_mode="Markdown"
    )
    return MAIN_MENU

# ─── Support ──────────────────────────────────────────────────────────────────
async def support_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📞 *پشتیبانی*\n\nپیام خود را بنویسید، در اسرع وقت پاسخ داده می‌شود:",
        parse_mode="Markdown"
    )
    return SUPPORT_MSG

async def support_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msg = update.message.text
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"📞 *پیام پشتیبانی*\n"
                f"👤 {update.effective_user.first_name} | ID: `{uid}`\n\n"
                f"💬 {msg}\n\n"
                f"برای پاسخ: /reply_{uid}",
                parse_mode="Markdown"
            )
        except:
            pass
    await update.message.reply_text("✅ پیام شما ارسال شد. به زودی پاسخ می‌گیرید.", reply_markup=main_keyboard())
    return MAIN_MENU

# ─── Admin Commands ───────────────────────────────────────────────────────────
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        return
    await update.message.reply_text("🔑 *پنل مدیریت*\n\nخوش آمدید!", parse_mode="Markdown", reply_markup=admin_keyboard())
    return ADMIN_MENU

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        return
    db = load_db()
    total_users = len(db["users"])
    total_orders = len(db["orders"])
    pending = sum(1 for o in db["orders"] if o["status"] == "pending_payment")
    active = sum(1 for o in db["orders"] if o["status"] == "active")

    await update.message.reply_text(
        f"📊 *آمار سیستم*\n\n"
        f"👥 کل کاربران: {total_users}\n"
        f"📦 کل سفارشات: {total_orders}\n"
        f"⏳ در انتظار تأیید: {pending}\n"
        f"✅ سرویس فعال: {active}",
        parse_mode="Markdown"
    )

async def admin_list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        return
    db = load_db()
    if not db["users"]:
        await update.message.reply_text("هنوز کاربری ثبت نشده.")
        return
    text = "👥 *لیست کاربران:*\n\n"
    for uid_str, u in list(db["users"].items())[-10:]:
        text += f"🆔 `{uid_str}` | 💰 {u['balance']:,}T | 📦 {len(u['orders'])} سفارش\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def admin_exit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        return
    await update.message.reply_text("✅ از پنل ادمین خارج شدید.", reply_markup=main_keyboard())
    return MAIN_MENU

# /approve_ID - تأیید سفارش
async def approve_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        return
    try:
        order_id = int(update.message.text.split("_")[1])
    except:
        await update.message.reply_text("فرمت اشتباه. مثال: /approve_5")
        return

    db = load_db()
    for o in db["orders"]:
        if o["id"] == order_id:
            o["status"] = "active"
            save_db(db)
            await update.message.reply_text(f"✅ سفارش #{order_id} تأیید شد.")
            try:
                await context.bot.send_message(
                    int(o["user_id"]),
                    f"🎉 *سرویس شما فعال شد!*\n\n"
                    f"🆔 سفارش #{order_id}\n"
                    f"📦 {o['gb']} گیگابایت | {o['days']} روز\n\n"
                    f"به زودی اطلاعات اتصال ارسال می‌شود.",
                    parse_mode="Markdown"
                )
            except:
                pass
            return
    await update.message.reply_text(f"❌ سفارش #{order_id} پیدا نشد.")

# /reject_ID - رد سفارش
async def reject_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        return
    try:
        order_id = int(update.message.text.split("_")[1])
    except:
        await update.message.reply_text("فرمت اشتباه. مثال: /reject_5")
        return

    db = load_db()
    for o in db["orders"]:
        if o["id"] == order_id:
            o["status"] = "rejected"
            save_db(db)
            await update.message.reply_text(f"❌ سفارش #{order_id} رد شد.")
            try:
                await context.bot.send_message(
                    int(o["user_id"]),
                    f"❌ متأسفانه سفارش #{order_id} تأیید نشد.\n"
                    f"برای پیگیری با پشتیبانی تماس بگیرید.",
                )
            except:
                pass
            return
    await update.message.reply_text(f"❌ سفارش #{order_id} پیدا نشد.")

# /addbalance_USERID_AMOUNT - شارژ کیف پول
async def add_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        return
    try:
        parts = update.message.text.split("_")
        target_uid = parts[1]
        amount = int(parts[2])
    except:
        await update.message.reply_text("فرمت اشتباه. مثال: /addbalance_123456_50000")
        return

    db = load_db()
    user = get_user(db, target_uid)
    user["balance"] += amount
    save_db(db)
    await update.message.reply_text(f"✅ {amount:,} تومان به کیف پول {target_uid} اضافه شد.\nموجودی جدید: {user['balance']:,} تومان")
    try:
        await context.bot.send_message(
            int(target_uid),
            f"💰 *کیف پول شارژ شد!*\n\n"
            f"➕ مبلغ: {amount:,} تومان\n"
            f"💵 موجودی فعلی: {user['balance']:,} تومان",
            parse_mode="Markdown"
        )
    except:
        pass

# /reply_USERID - پاسخ به کاربر
async def reply_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        return
    try:
        target_uid = int(update.message.text.split("_")[1])
        context.user_data["reply_to"] = target_uid
        await update.message.reply_text(f"✏️ پیام خود را برای کاربر {target_uid} بنویسید:")
    except:
        await update.message.reply_text("فرمت اشتباه. مثال: /reply_123456789")

# ─── Fallback text handler ────────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    # پاسخ ادمین به کاربر
    if uid in ADMIN_IDS and "reply_to" in context.user_data:
        target = context.user_data.pop("reply_to")
        try:
            await context.bot.send_message(target, f"📨 *پیام از پشتیبانی:*\n\n{text}", parse_mode="Markdown")
            await update.message.reply_text("✅ پیام ارسال شد.")
        except:
            await update.message.reply_text("❌ کاربر ربات را بلاک کرده یا آیدی اشتباه است.")
        return

    if text == "🛒 خرید سرویس جدید":
        return await buy_start(update, context)
    elif text == "📋 سرویس‌های من":
        return await my_services(update, context)
    elif text == "💰 کیف پول":
        return await wallet_menu(update, context)
    elif text == "👤 حساب کاربری":
        return await account_info(update, context)
    elif text == "📞 پشتیبانی":
        return await support_start(update, context)
    elif text == "👥 کاربران" and uid in ADMIN_IDS:
        return await admin_list_users(update, context)
    elif text == "📊 آمار" and uid in ADMIN_IDS:
        return await admin_stats(update, context)
    elif text == "🔙 خروج از پنل ادمین" and uid in ADMIN_IDS:
        return await admin_exit(update, context)
    else:
        await update.message.reply_text("لطفاً از منو استفاده کنید.", reply_markup=main_keyboard())

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
                        CallbackQueryHandler(wallet_charge_callback, pattern="wallet_charge")],
            BUY_GB: [MessageHandler(filters.TEXT & ~filters.COMMAND, buy_gb)],
            BUY_DURATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, buy_duration)],
            BUY_CONFIRM: [CallbackQueryHandler(buy_confirm_callback)],
            BUY_RECEIPT: [MessageHandler(filters.PHOTO, buy_receipt),
                          MessageHandler(filters.TEXT, lambda u, c: u.message.reply_text("📷 لطفاً تصویر رسید ارسال کنید."))],
            WALLET_MENU: [CallbackQueryHandler(wallet_charge_callback, pattern="wallet_charge"),
                          MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)],
            WALLET_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_amount)],
            WALLET_RECEIPT: [MessageHandler(filters.PHOTO, wallet_receipt),
                             MessageHandler(filters.TEXT, lambda u, c: u.message.reply_text("📷 لطفاً تصویر رسید ارسال کنید."))],
            SUPPORT_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, support_msg)],
            ADMIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)],
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(MessageHandler(filters.Regex(r"^/approve_\d+$"), approve_order))
    app.add_handler(MessageHandler(filters.Regex(r"^/reject_\d+$"), reject_order))
    app.add_handler(MessageHandler(filters.Regex(r"^/addbalance_\d+_\d+$"), add_balance))
    app.add_handler(MessageHandler(filters.Regex(r"^/reply_\d+$"), reply_user))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("🤖 Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
