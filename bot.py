import os
import json
import logging
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "123456789").split(",")))
CARD_NUMBER = os.getenv("CARD_NUMBER", "6037-XXXX-XXXX-XXXX")
CARD_OWNER = os.getenv("CARD_OWNER", "نام صاحب کارت")
PRICE_PER_GB = 4000  # تومان

DB_FILE = "db.json"

# ─── States ───────────────────────────────────────────────────────────────────
(
    MAIN_MENU, BUY_GB, BUY_DURATION, BUY_CONFIRM, BUY_PAYMENT_METHOD, BUY_RECEIPT,
    WALLET_MENU, WALLET_AMOUNT, WALLET_RECEIPT,
    SUPPORT_MSG,
    ADMIN_MENU, ADMIN_CHARGE_USERID, ADMIN_CHARGE_AMOUNT, ADMIN_REPLY_MSG
) = range(14)

# ─── Database ─────────────────────────────────────────────────────────────────
def load_db():
    if not os.path.exists(DB_FILE):
        return {"users": {}, "orders": [], "pending_wallets": [], "support_msgs": []}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)
        db.setdefault("support_msgs", [])
        return db

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
        ["💳 شارژ کیف پول کاربر", "📨 پیام‌های پشتیبانی"],
        ["📊 آمار", "🔙 خروج از پنل ادمین"]
    ], resize_keyboard=True)

def cancel_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ انصراف / منوی اصلی", callback_data="go_main")]
    ])

def admin_cancel_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ انصراف", callback_data="admin_go_main")]
    ])

# ─── Cancel Handlers ───────────────────────────────────────────────────────────
async def go_main_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("↩️ عملیات لغو شد.")
    await query.message.reply_text("🏠 منوی اصلی:", reply_markup=main_keyboard())
    return MAIN_MENU

async def admin_go_main_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("↩️ عملیات لغو شد.")
    await query.message.reply_text("🔑 پنل مدیریت:", reply_markup=admin_keyboard())
    return ADMIN_MENU

async def pay_pending_from_wallet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    uid = query.from_user.id
    db = load_db()
    user = get_user(db, uid)
    pending_order = context.user_data.get("pending_order")

    if not pending_order:
        await query.edit_message_text("❌ سفارش معلقی پیدا نشد.")
        return MAIN_MENU

    total = pending_order["total"]
    gb = pending_order["gb"]
    days = pending_order["days"]

    if user["balance"] < total:
        need = total - user["balance"]
        await query.answer(f"❌ موجودی کافی نیست.\nکمبود: {need:,} تومان", show_alert=True)
        return MAIN_MENU

    user["balance"] -= total
    order_id = len(db["orders"]) + 1
    order = {
        "id": order_id, "user_id": str(uid),
        "gb": gb, "days": days, "total": total,
        "status": "pending_activation", "payment": "wallet",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    db["orders"].append(order)
    user["orders"].append(order_id)
    save_db(db)
    context.user_data.pop("pending_order", None)

    await query.edit_message_text(
        f"✅ *پرداخت از کیف پول موفق!*\n\n"
        f"🆔 شماره سفارش: `#{order_id}`\n"
        f"📦 {gb} گیگابایت | {days} روز\n"
        f"💰 {total:,} تومان از کیف پول کسر شد\n"
        f"💵 موجودی باقی‌مانده: {user['balance']:,} تومان\n\n"
        f"⏳ ادمین به زودی سرویس را فعال می‌کند.",
        parse_mode="Markdown"
    )
    await notify_admins_new_order(context, order_id, query.from_user.first_name, uid, gb, days, total, "از کیف پول")
    return MAIN_MENU

# ─── Helper: Notify Admins ────────────────────────────────────────────────────
async def notify_admins_new_order(context, order_id, name, uid, gb, days, total, payment_label):
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"🛒 *سفارش جدید #{order_id}*\n"
                f"👤 {name} | ID: `{uid}`\n"
                f"📦 {gb} GB | {days} روز\n"
                f"💰 {total:,} تومان ({payment_label})\n\n"
                f"✅ تأیید: /approve_{order_id}\n"
                f"❌ رد: /reject_{order_id}",
                parse_mode="Markdown"
            )
        except:
            pass

# ─── /start ───────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db = load_db()
    user = get_user(db, uid)
    user["username"] = update.effective_user.username or ""
    save_db(db)
    name = update.effective_user.first_name or "کاربر"
    await update.message.reply_text(
        f"🔒 به فروشگاه VPN خوش آمدید، {name} عزیز!\n\nاز منوی زیر گزینه مورد نظر را انتخاب کنید:",
        reply_markup=main_keyboard()
    )
    return MAIN_MENU

# ─── Buy Flow ─────────────────────────────────────────────────────────────────
async def buy_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📡 *خرید سرویس VPN*\n\n"
        f"💵 قیمت: *{PRICE_PER_GB:,} تومان* به ازای هر گیگابایت\n\n"
        f"چند گیگابایت می‌خواهید؟\n_(مثال: 10، 20، 50)_",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )
    return BUY_GB

async def buy_gb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("❌ لطفاً یک عدد صحیح مثبت وارد کنید:", reply_markup=cancel_kb())
        return BUY_GB
    context.user_data["gb"] = int(text)
    await update.message.reply_text(
        f"⏳ مدت زمان سرویس را وارد کنید:\n_(بین ۳۰ تا ۹۰ روز - مثال: 30، 60، 90)_",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )
    return BUY_DURATION

async def buy_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit() or not (30 <= int(text) <= 90):
        await update.message.reply_text("❌ لطفاً عددی بین ۳۰ تا ۹۰ وارد کنید:", reply_markup=cancel_kb())
        return BUY_DURATION

    gb = context.user_data["gb"]
    days = int(text)
    total = gb * PRICE_PER_GB
    context.user_data["days"] = days
    context.user_data["total"] = total

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأیید سفارش", callback_data="buy_confirm")],
        [InlineKeyboardButton("❌ انصراف", callback_data="go_main")]
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

    uid = query.from_user.id
    db = load_db()
    user = get_user(db, uid)
    total = context.user_data["total"]
    gb = context.user_data["gb"]
    days = context.user_data["days"]
    balance = user["balance"]

    buttons = []
    if balance >= total:
        buttons.append([InlineKeyboardButton(f"💰 پرداخت از کیف پول ({balance:,} تومان موجودی)", callback_data="pay_wallet")])
    elif balance > 0:
        buttons.append([InlineKeyboardButton(f"💰 کیف پول (موجودی {balance:,}T - کافی نیست)", callback_data="pay_wallet_insufficient")])

    buttons.append([InlineKeyboardButton("💳 پرداخت کارت به کارت", callback_data="pay_card")])
    buttons.append([InlineKeyboardButton("🔋 شارژ کیف پول و پرداخت", callback_data="charge_then_pay")])
    buttons.append([InlineKeyboardButton("❌ انصراف", callback_data="go_main")])

    save_db(db)
    await query.edit_message_text(
        f"💳 *روش پرداخت را انتخاب کنید:*\n\n"
        f"📦 {gb} گیگابایت | {days} روز\n"
        f"💰 مبلغ: *{total:,} تومان*\n"
        f"👛 موجودی کیف پول: {balance:,} تومان",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons)
    )
    return BUY_PAYMENT_METHOD

async def buy_payment_method_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "pay_wallet_insufficient":
        await query.answer("❌ موجودی کافی نیست. از دکمه شارژ کیف پول استفاده کنید.", show_alert=True)
        return BUY_PAYMENT_METHOD

    if query.data == "charge_then_pay":
        context.user_data["pending_order"] = {
            "gb": context.user_data["gb"],
            "days": context.user_data["days"],
            "total": context.user_data["total"],
        }
        await query.edit_message_text(
            f"🔋 *شارژ کیف پول*\n\n"
            f"💡 بعد از شارژ، دکمه پرداخت از کیف پول نشان داده می‌شود.\n\n"
            f"چه مبلغی می‌خواهید واریز کنید؟\n_(مثال: 50000، 100000)_ تومان",
            parse_mode="Markdown", reply_markup=cancel_kb()
        )
        return WALLET_AMOUNT

    uid = query.from_user.id
    db = load_db()
    user = get_user(db, uid)
    total = context.user_data["total"]
    gb = context.user_data["gb"]
    days = context.user_data["days"]

    if query.data == "pay_wallet":
        user["balance"] -= total
        order_id = len(db["orders"]) + 1
        order = {
            "id": order_id, "user_id": str(uid),
            "gb": gb, "days": days, "total": total,
            "status": "pending_activation", "payment": "wallet",
            "date": datetime.now().strftime("%Y-%m-%d %H:%M")
        }
        db["orders"].append(order)
        user["orders"].append(order_id)
        save_db(db)

        await query.edit_message_text(
            f"✅ *پرداخت از کیف پول موفق!*\n\n"
            f"🆔 شماره سفارش: `#{order_id}`\n"
            f"📦 {gb} گیگابایت | {days} روز\n"
            f"💰 {total:,} تومان از کیف پول کسر شد\n"
            f"💵 موجودی باقی‌مانده: {user['balance']:,} تومان\n\n"
            f"⏳ ادمین به زودی سرویس را فعال می‌کند.",
            parse_mode="Markdown"
        )
        await notify_admins_new_order(context, order_id, query.from_user.first_name, uid, gb, days, total, "از کیف پول")
        return MAIN_MENU

    elif query.data == "pay_card":
        save_db(db)
        await query.edit_message_text(
            f"💳 *پرداخت کارت به کارت*\n\n"
            f"💰 مبلغ: *{total:,} تومان*\n"
            f"🏦 شماره کارت:\n`{CARD_NUMBER}`\n"
            f"👤 به نام: *{CARD_OWNER}*\n\n"
            f"پس از واریز، *تصویر رسید* را ارسال کنید:",
            parse_mode="Markdown", reply_markup=cancel_kb()
        )
        return BUY_RECEIPT

async def buy_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("📷 لطفاً تصویر رسید پرداخت را ارسال کنید:", reply_markup=cancel_kb())
        return BUY_RECEIPT

    uid = update.effective_user.id
    db = load_db()
    order_id = len(db["orders"]) + 1
    order = {
        "id": order_id, "user_id": str(uid),
        "gb": context.user_data.get("gb", 0),
        "days": context.user_data.get("days", 0),
        "total": context.user_data.get("total", 0),
        "status": "pending_payment", "payment": "card",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    db["orders"].append(order)
    user = get_user(db, uid)
    user["orders"].append(order_id)
    save_db(db)

    await update.message.reply_text(
        f"✅ رسید دریافت شد!\n\n🆔 شماره سفارش: `#{order_id}`\n⏳ در حال بررسی توسط ادمین...",
        parse_mode="Markdown", reply_markup=main_keyboard()
    )
    photo_id = update.message.photo[-1].file_id
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_photo(
                admin_id, photo_id,
                caption=f"💳 *رسید سفارش #{order_id}*\n"
                        f"👤 {update.effective_user.first_name} | ID: `{uid}`\n"
                        f"📦 {order['gb']} GB | {order['days']} روز\n"
                        f"💰 {order['total']:,} تومان\n\n"
                        f"✅ تأیید: /approve_{order_id}\n"
                        f"❌ رد: /reject_{order_id}",
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
        [InlineKeyboardButton("➕ شارژ کیف پول", callback_data="wallet_charge")],
        [InlineKeyboardButton("❌ انصراف / منوی اصلی", callback_data="go_main")]
    ])
    await update.message.reply_text(
        f"💰 *کیف پول شما*\n\n💵 موجودی: *{user['balance']:,} تومان*",
        parse_mode="Markdown", reply_markup=kb
    )
    return WALLET_MENU

async def wallet_charge_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        f"💳 *شارژ کیف پول*\n\nچه مبلغی می‌خواهید واریز کنید؟\n_(مثال: 50000، 100000)_ تومان",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )
    return WALLET_AMOUNT

async def wallet_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", "")
    if not text.isdigit() or int(text) < 10000:
        await update.message.reply_text("❌ حداقل مبلغ ۱۰,۰۰۰ تومان است:", reply_markup=cancel_kb())
        return WALLET_AMOUNT

    amount = int(text)
    context.user_data["wallet_amount"] = amount
    await update.message.reply_text(
        f"💳 *اطلاعات پرداخت*\n\n"
        f"💰 مبلغ: *{amount:,} تومان*\n"
        f"🏦 شماره کارت:\n`{CARD_NUMBER}`\n"
        f"👤 به نام: *{CARD_OWNER}*\n\n"
        f"پس از واریز، *تصویر رسید* را ارسال کنید:",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )
    return WALLET_RECEIPT

async def wallet_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("📷 لطفاً تصویر رسید را ارسال کنید:", reply_markup=cancel_kb())
        return WALLET_RECEIPT

    uid = update.effective_user.id
    amount = context.user_data.get("wallet_amount", 0)
    db = load_db()
    pw_id = len(db["pending_wallets"]) + 1
    db["pending_wallets"].append({
        "id": pw_id, "user_id": str(uid), "amount": amount,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M")
    })
    save_db(db)

    pending_order = context.user_data.get("pending_order")
    if pending_order:
        total = pending_order["total"]; gb = pending_order["gb"]; days = pending_order["days"]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💰 پرداخت سفارش از کیف پول ({total:,} تومان)", callback_data="pay_pending_from_wallet")],
            [InlineKeyboardButton("❌ انصراف / منوی اصلی", callback_data="go_main")]
        ])
        await update.message.reply_text(
            f"✅ رسید شارژ دریافت شد!\n"
            f"💰 {amount:,} تومان\n"
            f"⏳ پس از تأیید ادمین، موجودی افزایش می‌یابد.\n\n"
            f"📦 سفارش معلق: {gb}GB | {days}روز | {total:,} تومان\n"
            f"وقتی کیف پولت شارژ شد دکمه پایین رو بزن:",
            reply_markup=kb
        )
    else:
        await update.message.reply_text(
            f"✅ رسید شارژ دریافت شد!\n💰 {amount:,} تومان\n⏳ پس از تأیید ادمین موجودی افزایش می‌یابد.",
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
                        f"✅ تأیید: /addbalance_{uid}_{amount}",
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
    status_map = {
        "pending_payment": "⏳ در انتظار تأیید پرداخت",
        "pending_activation": "⚙️ در حال فعال‌سازی",
        "active": "✅ فعال",
        "rejected": "❌ رد شده"
    }
    text = "📋 *سرویس‌های شما:*\n\n"
    for o in orders[-5:]:
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
        f"👤 *حساب کاربری*\n\n🆔 آیدی: `{uid}`\n💰 موجودی: {user['balance']:,} تومان\n📦 تعداد سفارشات: {len(user['orders'])}",
        parse_mode="Markdown"
    )
    return MAIN_MENU

# ─── Support ──────────────────────────────────────────────────────────────────
async def support_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📞 *پشتیبانی*\n\nپیام خود را بنویسید:",
        parse_mode="Markdown", reply_markup=cancel_kb()
    )
    return SUPPORT_MSG

async def support_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msg = update.message.text
    db = load_db()
    msg_id = len(db["support_msgs"]) + 1
    db["support_msgs"].append({
        "id": msg_id, "user_id": str(uid),
        "name": update.effective_user.first_name or "کاربر",
        "message": msg, "answered": False,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M")
    })
    save_db(db)

    for admin_id in ADMIN_IDS:
        try:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✏️ پاسخ به این پیام", callback_data=f"reply_msg_{msg_id}")]
            ])
            await context.bot.send_message(
                admin_id,
                f"📞 *پیام پشتیبانی جدید #{msg_id}*\n"
                f"👤 {update.effective_user.first_name} | ID: `{uid}`\n\n"
                f"💬 {msg}",
                parse_mode="Markdown", reply_markup=kb
            )
        except:
            pass
    await update.message.reply_text("✅ پیام شما ارسال شد. به زودی پاسخ داده می‌شود.", reply_markup=main_keyboard())
    return MAIN_MENU

# ─── Admin Panel ──────────────────────────────────────────────────────────────
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        return
    await update.message.reply_text("🔑 *پنل مدیریت*", parse_mode="Markdown", reply_markup=admin_keyboard())
    return ADMIN_MENU

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    total_users = len(db["users"])
    total_orders = len(db["orders"])
    pending = sum(1 for o in db["orders"] if o["status"] == "pending_payment")
    active = sum(1 for o in db["orders"] if o["status"] == "active")
    unanswered = sum(1 for m in db["support_msgs"] if not m.get("answered"))
    await update.message.reply_text(
        f"📊 *آمار سیستم*\n\n👥 کاربران: {total_users}\n📦 سفارشات: {total_orders}\n"
        f"⏳ در انتظار: {pending}\n✅ فعال: {active}\n📨 پیام بی‌پاسخ: {unanswered}",
        parse_mode="Markdown"
    )
    return ADMIN_MENU

async def admin_list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    if not db["users"]:
        await update.message.reply_text("هنوز کاربری ثبت نشده.")
        return ADMIN_MENU
    text = "👥 *لیست کاربران:*\n\n"
    for uid_str, u in list(db["users"].items())[-10:]:
        text += f"🆔 `{uid_str}` | 💰 {u['balance']:,}T | 📦 {len(u['orders'])} سفارش\n"
    await update.message.reply_text(text, parse_mode="Markdown")
    return ADMIN_MENU

async def admin_list_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    if not db["orders"]:
        await update.message.reply_text("📭 هنوز سفارشی ثبت نشده.")
        return ADMIN_MENU

    status_map = {
        "pending_payment": "⏳ انتظار پرداخت",
        "pending_activation": "⚙️ انتظار فعال‌سازی",
        "active": "✅ فعال",
        "rejected": "❌ رد شده"
    }
    text = "📦 *آخرین ۱۰ سفارش:*\n\n"
    for o in db["orders"][-10:]:
        status = status_map.get(o["status"], o["status"])
        text += (
            f"🆔 #{o['id']} | 👤 `{o['user_id']}`\n"
            f"📦 {o['gb']}GB | {o['days']}روز | 💰{o['total']:,}T\n"
            f"{status} | 📅 {o['date']}\n"
        )
        if o["status"] == "pending_payment":
            text += f"✅ /approve_{o['id']}  ❌ /reject_{o['id']}\n"
        text += "\n"

    await update.message.reply_text(text, parse_mode="Markdown")
    return ADMIN_MENU

# ─── Support Messages List (admin) ────────────────────────────────────────────
async def admin_support_msgs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    msgs = [m for m in db["support_msgs"] if not m.get("answered")]
    if not msgs:
        await update.message.reply_text("📭 پیام بی‌پاسخی وجود ندارد.")
        return ADMIN_MENU

    for m in msgs[-10:]:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✏️ پاسخ به این پیام", callback_data=f"reply_msg_{m['id']}")]
        ])
        await update.message.reply_text(
            f"📨 *پیام #{m['id']}*\n👤 {m['name']} | ID: `{m['user_id']}`\n📅 {m['date']}\n\n💬 {m['message']}",
            parse_mode="Markdown", reply_markup=kb
        )
    return ADMIN_MENU

async def admin_reply_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    msg_id = int(query.data.split("_")[-1])
    db = load_db()
    target_msg = next((m for m in db["support_msgs"] if m["id"] == msg_id), None)
    if not target_msg:
        await query.answer("❌ پیام پیدا نشد.", show_alert=True)
        return ADMIN_MENU

    context.user_data["reply_to_msg_id"] = msg_id
    context.user_data["reply_to_uid"] = target_msg["user_id"]
    await query.message.reply_text(
        f"✏️ پاسخ خود را برای کاربر `{target_msg['user_id']}` بنویسید:",
        parse_mode="Markdown", reply_markup=admin_cancel_kb()
    )
    return ADMIN_REPLY_MSG

async def admin_reply_msg_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_uid = context.user_data.get("reply_to_uid")
    msg_id = context.user_data.get("reply_to_msg_id")
    text = update.message.text

    if not target_uid:
        await update.message.reply_text("❌ خطا، دوباره تلاش کنید.", reply_markup=admin_keyboard())
        return ADMIN_MENU

    try:
        await context.bot.send_message(int(target_uid), f"📨 *پاسخ پشتیبانی:*\n\n{text}", parse_mode="Markdown")
        db = load_db()
        for m in db["support_msgs"]:
            if m["id"] == msg_id:
                m["answered"] = True
        save_db(db)
        await update.message.reply_text("✅ پاسخ ارسال شد.", reply_markup=admin_keyboard())
    except:
        await update.message.reply_text("❌ ارسال ناموفق. کاربر ربات را بلاک کرده.", reply_markup=admin_keyboard())

    context.user_data.pop("reply_to_uid", None)
    context.user_data.pop("reply_to_msg_id", None)
    return ADMIN_MENU

# ─── Admin Charge Wallet Flow ─────────────────────────────────────────────────
async def admin_charge_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💳 *شارژ کیف پول کاربر*\n\nآیدی عددی کاربر را وارد کنید:\n_(مثال: 123456789)_",
        parse_mode="Markdown", reply_markup=admin_cancel_kb()
    )
    return ADMIN_CHARGE_USERID

async def admin_charge_userid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ آیدی باید عدد باشد:", reply_markup=admin_cancel_kb())
        return ADMIN_CHARGE_USERID

    db = load_db()
    if text not in db["users"]:
        await update.message.reply_text(f"❌ کاربر `{text}` در سیستم نیست.", parse_mode="Markdown", reply_markup=admin_cancel_kb())
        return ADMIN_CHARGE_USERID

    context.user_data["charge_uid"] = text
    user = db["users"][text]
    await update.message.reply_text(
        f"✅ کاربر پیدا شد!\n💵 موجودی فعلی: {user['balance']:,} تومان\n\nمبلغ شارژ را وارد کنید (تومان):",
        reply_markup=admin_cancel_kb()
    )
    return ADMIN_CHARGE_AMOUNT

async def admin_charge_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", "")
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("❌ مبلغ نامعتبر است:", reply_markup=admin_cancel_kb())
        return ADMIN_CHARGE_AMOUNT

    amount = int(text)
    target_uid = context.user_data["charge_uid"]
    db = load_db()
    user = get_user(db, target_uid)
    user["balance"] += amount
    save_db(db)

    await update.message.reply_text(
        f"✅ *شارژ موفق!*\n\n👤 کاربر: `{target_uid}`\n➕ {amount:,} تومان\n💵 موجودی جدید: {user['balance']:,} تومان",
        parse_mode="Markdown", reply_markup=admin_keyboard()
    )
    try:
        await context.bot.send_message(
            int(target_uid),
            f"💰 *کیف پول شارژ شد!*\n\n➕ {amount:,} تومان\n💵 موجودی: {user['balance']:,} تومان",
            parse_mode="Markdown"
        )
    except:
        pass
    return ADMIN_MENU

async def admin_exit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ از پنل ادمین خارج شدید.", reply_markup=main_keyboard())
    return MAIN_MENU

# ─── Admin Commands (approve/reject/addbalance) ───────────────────────────────
async def approve_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    import re
    m = re.match(r"^/approve_?(\d+)$", update.message.text.strip())
    if not m:
        await update.message.reply_text("فرمت اشتباه. مثال: /approve_5")
        return ADMIN_MENU
    order_id = int(m.group(1))
    db = load_db()
    for o in db["orders"]:
        if o["id"] == order_id:
            o["status"] = "active"
            save_db(db)
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 ارسال لینک سرویس به خریدار", callback_data=f"send_link_{order_id}")]
            ])
            await update.message.reply_text(
                f"✅ سفارش #{order_id} تأیید شد و به کاربر اطلاع داده شد.\n\n"
                f"می‌خواهید اطلاعات اتصال (لینک/کانفیگ) را برای خریدار ارسال کنید؟",
                reply_markup=kb
            )
            try:
                await context.bot.send_message(
                    int(o["user_id"]),
                    f"🎉 *سرویس شما فعال شد!*\n\n🆔 سفارش #{order_id}\n📦 {o['gb']}GB | {o['days']}روز\n\nبه زودی اطلاعات اتصال ارسال می‌شود.",
                    parse_mode="Markdown"
                )
            except:
                pass
            return ADMIN_MENU
    await update.message.reply_text(f"❌ سفارش #{order_id} پیدا نشد.")
    return ADMIN_MENU

async def reject_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    import re
    m = re.match(r"^/reject_?(\d+)$", update.message.text.strip())
    if not m:
        await update.message.reply_text("فرمت اشتباه. مثال: /reject_5")
        return ADMIN_MENU
    order_id = int(m.group(1))
    db = load_db()
    for o in db["orders"]:
        if o["id"] == order_id:
            o["status"] = "rejected"
            save_db(db)
            await update.message.reply_text(f"❌ سفارش #{order_id} رد شد.")
            try:
                await context.bot.send_message(int(o["user_id"]), f"❌ سفارش #{order_id} تأیید نشد.\nبرای پیگیری پشتیبانی تماس بگیرید.")
            except:
                pass
            return ADMIN_MENU
    await update.message.reply_text(f"❌ سفارش #{order_id} پیدا نشد.")
    return ADMIN_MENU

async def add_balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    import re
    m = re.match(r"^/addbalance_?(\d+)_(\d+)$", update.message.text.strip())
    if not m:
        await update.message.reply_text("فرمت اشتباه. مثال: /addbalance_123456_50000")
        return ADMIN_MENU
    target_uid = m.group(1)
    amount = int(m.group(2))
    db = load_db()
    user = get_user(db, target_uid)
    user["balance"] += amount
    save_db(db)
    await update.message.reply_text(f"✅ {amount:,} تومان به `{target_uid}` اضافه شد.\nموجودی: {user['balance']:,} تومان", parse_mode="Markdown")
    try:
        await context.bot.send_message(int(target_uid), f"💰 *کیف پول شارژ شد!*\n\n➕ {amount:,} تومان\n💵 موجودی: {user['balance']:,} تومان", parse_mode="Markdown")
    except:
        pass
    return ADMIN_MENU

# ─── Send Link to Buyer Flow ──────────────────────────────────────────────────
async def send_link_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split("_")[-1])
    db = load_db()
    order = next((o for o in db["orders"] if o["id"] == order_id), None)
    if not order:
        await query.answer("❌ سفارش پیدا نشد.", show_alert=True)
        return ADMIN_MENU

    context.user_data["send_link_order_id"] = order_id
    context.user_data["send_link_uid"] = order["user_id"]
    await query.message.reply_text(
        f"🔗 لینک یا اطلاعات اتصال سفارش #{order_id} را بفرستید:\n"
        f"_(می‌توانید متن، لینک، یا فایل کانفیگ بفرستید)_",
        parse_mode="Markdown", reply_markup=admin_cancel_kb()
    )
    return ADMIN_REPLY_MSG  # از همون state پاسخ پشتیبانی استفاده می‌کنیم با چک جدا

async def send_link_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_uid = context.user_data.get("send_link_uid")
    order_id = context.user_data.get("send_link_order_id")
    text = update.message.text

    try:
        await context.bot.send_message(
            int(target_uid),
            f"🔗 *اطلاعات اتصال سفارش #{order_id}*\n\n{text}",
            parse_mode="Markdown"
        )
        await update.message.reply_text("✅ لینک ارسال شد.", reply_markup=admin_keyboard())
    except:
        await update.message.reply_text("❌ ارسال ناموفق. کاربر ربات را بلاک کرده.", reply_markup=admin_keyboard())

    context.user_data.pop("send_link_uid", None)
    context.user_data.pop("send_link_order_id", None)
    return ADMIN_MENU

# ─── Unified ADMIN_REPLY_MSG router (پاسخ پشتیبانی یا ارسال لینک) ─────────────
async def admin_reply_msg_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "send_link_uid" in context.user_data:
        return await send_link_text(update, context)
    else:
        return await admin_reply_msg_text(update, context)

# ─── Main Text Handler ────────────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

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

    if uid in ADMIN_IDS:
        if text == "👥 کاربران":
            return await admin_list_users(update, context)
        elif text == "📦 سفارشات":
            return await admin_list_orders(update, context)
        elif text == "💳 شارژ کیف پول کاربر":
            return await admin_charge_start(update, context)
        elif text == "📨 پیام‌های پشتیبانی":
            return await admin_support_msgs(update, context)
        elif text == "📊 آمار":
            return await admin_stats(update, context)
        elif text == "🔙 خروج از پنل ادمین":
            return await admin_exit(update, context)

    await update.message.reply_text("لطفاً از منو استفاده کنید.", reply_markup=main_keyboard())
    return MAIN_MENU

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CommandHandler("admin", admin_panel),
        ],
        states={
            MAIN_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
                CallbackQueryHandler(wallet_charge_callback, pattern="^wallet_charge$"),
                CallbackQueryHandler(go_main_callback, pattern="^go_main$"),
                CallbackQueryHandler(pay_pending_from_wallet_callback, pattern="^pay_pending_from_wallet$"),
            ],
            BUY_GB: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, buy_gb),
                CallbackQueryHandler(go_main_callback, pattern="^go_main$"),
            ],
            BUY_DURATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, buy_duration),
                CallbackQueryHandler(go_main_callback, pattern="^go_main$"),
            ],
            BUY_CONFIRM: [
                CallbackQueryHandler(buy_confirm_callback, pattern="^buy_confirm$"),
                CallbackQueryHandler(go_main_callback, pattern="^go_main$"),
            ],
            BUY_PAYMENT_METHOD: [
                CallbackQueryHandler(buy_payment_method_callback, pattern="^pay_"),
                CallbackQueryHandler(buy_payment_method_callback, pattern="^charge_then_pay$"),
                CallbackQueryHandler(go_main_callback, pattern="^go_main$"),
            ],
            BUY_RECEIPT: [
                MessageHandler(filters.PHOTO, buy_receipt),
                MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: u.message.reply_text("📷 لطفاً تصویر رسید ارسال کنید:")),
                CallbackQueryHandler(go_main_callback, pattern="^go_main$"),
            ],
            WALLET_MENU: [
                CallbackQueryHandler(wallet_charge_callback, pattern="^wallet_charge$"),
                CallbackQueryHandler(go_main_callback, pattern="^go_main$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
            ],
            WALLET_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_amount),
                CallbackQueryHandler(go_main_callback, pattern="^go_main$"),
            ],
            WALLET_RECEIPT: [
                MessageHandler(filters.PHOTO, wallet_receipt),
                MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: u.message.reply_text("📷 لطفاً تصویر رسید ارسال کنید:")),
                CallbackQueryHandler(go_main_callback, pattern="^go_main$"),
                CallbackQueryHandler(pay_pending_from_wallet_callback, pattern="^pay_pending_from_wallet$"),
            ],
            SUPPORT_MSG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, support_msg),
                CallbackQueryHandler(go_main_callback, pattern="^go_main$"),
            ],
            ADMIN_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
                CallbackQueryHandler(admin_reply_button_callback, pattern="^reply_msg_"),
                CallbackQueryHandler(send_link_button_callback, pattern="^send_link_"),
            ],
            ADMIN_CHARGE_USERID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_charge_userid),
                CallbackQueryHandler(admin_go_main_callback, pattern="^admin_go_main$"),
            ],
            ADMIN_CHARGE_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_charge_amount),
                CallbackQueryHandler(admin_go_main_callback, pattern="^admin_go_main$"),
            ],
            ADMIN_REPLY_MSG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_reply_msg_router),
                CallbackQueryHandler(admin_go_main_callback, pattern="^admin_go_main$"),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("admin", admin_panel),
        ],
        allow_reentry=True
    )

    # گروه -1 یعنی این هندلرها قبل از ConversationHandler چک می‌شن
    app.add_handler(MessageHandler(filters.Regex(r"^/approve_?\d+$"), approve_order), group=-1)
    app.add_handler(MessageHandler(filters.Regex(r"^/reject_?\d+$"), reject_order), group=-1)
    app.add_handler(MessageHandler(filters.Regex(r"^/addbalance_?\d+_\d+$"), add_balance_cmd), group=-1)

    app.add_handler(conv)

    print("🤖 Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
