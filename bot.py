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
    ADMIN_MENU, ADMIN_CHARGE_USERID, ADMIN_CHARGE_AMOUNT
) = range(13)

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

# دکمه انصراف/بازگشت که همه جا استفاده می‌شه
def cancel_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 بازگشت به منوی اصلی", callback_data="go_main")]
    ])

# ─── Cancel Handler ───────────────────────────────────────────────────────────
async def go_main_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text("↩️ عملیات لغو شد.")
    await query.message.reply_text("🏠 منوی اصلی:", reply_markup=main_keyboard())
    return MAIN_MENU

async def pay_pending_from_wallet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """وقتی کاربر بعد از شارژ کیف پول، سفارش معلقش رو از کیف پول پرداخت می‌کنه"""
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
        await query.answer(
            f"❌ موجودی هنوز کافی نیست.\nکمبود: {need:,} تومان\nمنتظر تأیید ادمین باشید.",
            show_alert=True
        )
        return MAIN_MENU

    # پرداخت از کیف پول
    user["balance"] -= total
    order_id = len(db["orders"]) + 1
    order = {
        "id": order_id, "user_id": str(uid),
        "gb": gb, "days": days, "total": total,
        "status": "pending_activation",
        "payment": "wallet",
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
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"🛒 *سفارش جدید #{order_id}*\n"
                f"👤 {query.from_user.first_name} | ID: `{uid}`\n"
                f"📦 {gb} GB | {days} روز\n"
                f"💰 {total:,} تومان (از کیف پول)\n\n"
                f"تأیید: /approve_{order_id}",
                parse_mode="Markdown"
            )
        except:
            pass
    return MAIN_MENU

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
        parse_mode="Markdown",
        reply_markup=cancel_kb()
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
        parse_mode="Markdown",
        reply_markup=cancel_kb()
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

    # نشون دادن روش‌های پرداخت - کیف پول اگه کافیه نشون بده
    buttons = []
    if balance >= total:
        buttons.append([InlineKeyboardButton(
            f"💰 پرداخت از کیف پول ({balance:,} تومان موجودی)",
            callback_data="pay_wallet"
        )])
    elif balance > 0:
        buttons.append([InlineKeyboardButton(
            f"💰 کیف پول (موجودی {balance:,}T - کافی نیست)",
            callback_data="pay_wallet_insufficient"
        )])
    
    buttons.append([InlineKeyboardButton("💳 پرداخت کارت به کارت", callback_data="pay_card")])
    buttons.append([InlineKeyboardButton("🔋 شارژ کیف پول و پرداخت", callback_data="charge_then_pay")])
    buttons.append([InlineKeyboardButton("❌ انصراف", callback_data="go_main")])

    save_db(db)
    await query.edit_message_text(
        f"💳 *روش پرداخت را انتخاب کنید:*\n\n"
        f"📦 {gb} گیگابایت | {days} روز\n"
        f"💰 مبلغ: *{total:,} تومان*\n"
        f"👛 موجودی کیف پول: {balance:,} تومان",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return BUY_PAYMENT_METHOD

async def buy_payment_method_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "pay_wallet_insufficient":
        await query.answer("❌ موجودی کافی نیست. از دکمه شارژ کیف پول استفاده کنید.", show_alert=True)
        return BUY_PAYMENT_METHOD

    if query.data == "charge_then_pay":
        # ذخیره اطلاعات سفارش برای بعد از شارژ کیف پول
        context.user_data["pending_order"] = {
            "gb": context.user_data["gb"],
            "days": context.user_data["days"],
            "total": context.user_data["total"],
        }
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ انصراف", callback_data="go_main")]])
        await query.edit_message_text(
            f"🔋 *شارژ کیف پول*\n\n"
            f"💡 بعد از شارژ، دکمه پرداخت از کیف پول نشان داده می‌شود.\n\n"
            f"چه مبلغی می‌خواهید واریز کنید؟\n_(مثال: 50000، 100000)_ تومان",
            parse_mode="Markdown", reply_markup=kb
        )
        return WALLET_AMOUNT

    uid = query.from_user.id
    db = load_db()
    user = get_user(db, uid)
    total = context.user_data["total"]
    gb = context.user_data["gb"]
    days = context.user_data["days"]

    if query.data == "pay_wallet":
        # پرداخت از کیف پول
        user["balance"] -= total
        order_id = len(db["orders"]) + 1
        order = {
            "id": order_id, "user_id": str(uid),
            "gb": gb, "days": days, "total": total,
            "status": "pending_activation",
            "payment": "wallet",
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
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    admin_id,
                    f"🛒 *سفارش جدید #{order_id}*\n"
                    f"👤 {query.from_user.first_name} | ID: `{uid}`\n"
                    f"📦 {gb} GB | {days} روز\n"
                    f"💰 {total:,} تومان (از کیف پول)\n\n"
                    f"تأیید: /approve_{order_id}",
                    parse_mode="Markdown"
                )
            except:
                pass
        return MAIN_MENU

    elif query.data == "pay_card":
        # پرداخت کارت به کارت
        save_db(db)
        await query.edit_message_text(
            f"💳 *پرداخت کارت به کارت*\n\n"
            f"💰 مبلغ: *{total:,} تومان*\n"
            f"🏦 شماره کارت:\n`{CARD_NUMBER}`\n"
            f"👤 به نام: *{CARD_OWNER}*\n\n"
            f"پس از واریز، *تصویر رسید* را ارسال کنید:\n\n"
            f"_(یا /start برای انصراف)_",
            parse_mode="Markdown"
        )
        return BUY_RECEIPT

async def buy_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text(
            "📷 لطفاً تصویر رسید پرداخت را ارسال کنید:",
            reply_markup=cancel_kb()
        )
        return BUY_RECEIPT

    uid = update.effective_user.id
    db = load_db()
    order_id = len(db["orders"]) + 1
    order = {
        "id": order_id, "user_id": str(uid),
        "gb": context.user_data.get("gb", 0),
        "days": context.user_data.get("days", 0),
        "total": context.user_data.get("total", 0),
        "status": "pending_payment",
        "payment": "card",
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
                        f"✅ /approve_{order_id}   ❌ /reject_{order_id}",
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
        [InlineKeyboardButton("🏠 بازگشت به منو", callback_data="go_main")]
    ])
    await update.message.reply_text(
        f"💰 *کیف پول شما*\n\n💵 موجودی: *{user['balance']:,} تومان*",
        parse_mode="Markdown", reply_markup=kb
    )
    return WALLET_MENU

async def wallet_charge_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ انصراف", callback_data="go_main")]
    ])
    await query.edit_message_text(
        f"💳 *شارژ کیف پول*\n\nچه مبلغی می‌خواهید واریز کنید؟\n_(مثال: 50000، 100000)_ تومان",
        parse_mode="Markdown", reply_markup=kb
    )
    return WALLET_AMOUNT

async def wallet_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", "")
    if not text.isdigit() or int(text) < 10000:
        await update.message.reply_text("❌ حداقل مبلغ ۱۰,۰۰۰ تومان است:", reply_markup=cancel_kb())
        return WALLET_AMOUNT

    amount = int(text)
    context.user_data["wallet_amount"] = amount
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ انصراف", callback_data="go_main")]
    ])
    await update.message.reply_text(
        f"💳 *اطلاعات پرداخت*\n\n"
        f"💰 مبلغ: *{amount:,} تومان*\n"
        f"🏦 شماره کارت:\n`{CARD_NUMBER}`\n"
        f"👤 به نام: *{CARD_OWNER}*\n\n"
        f"پس از واریز، *تصویر رسید* را ارسال کنید:",
        parse_mode="Markdown", reply_markup=kb
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

    # اگه سفارش معلقی داشت، دکمه پرداخت از کیف پول نشون بده
    pending_order = context.user_data.get("pending_order")
    if pending_order:
        total = pending_order["total"]
        gb = pending_order["gb"]
        days = pending_order["days"]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"💰 پرداخت سفارش از کیف پول ({total:,} تومان)",
                callback_data="pay_pending_from_wallet"
            )],
            [InlineKeyboardButton("🏠 منوی اصلی", callback_data="go_main")]
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
        parse_mode="Markdown",
        reply_markup=cancel_kb()
    )
    return SUPPORT_MSG

async def support_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msg = update.message.text
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin_id,
                f"📞 *پیام پشتیبانی*\n👤 {update.effective_user.first_name} | ID: `{uid}`\n\n💬 {msg}\n\nپاسخ: /reply_{uid}",
                parse_mode="Markdown"
            )
        except:
            pass
    await update.message.reply_text("✅ پیام ارسال شد.", reply_markup=main_keyboard())
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
    await update.message.reply_text(
        f"📊 *آمار سیستم*\n\n👥 کاربران: {total_users}\n📦 سفارشات: {total_orders}\n⏳ در انتظار: {pending}\n✅ فعال: {active}",
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

async def admin_charge_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💳 *شارژ کیف پول کاربر*\n\nآیدی عددی کاربر را وارد کنید:\n_(مثال: 123456789)_\n\nبرای انصراف /admin بزنید",
        parse_mode="Markdown"
    )
    return ADMIN_CHARGE_USERID

async def admin_charge_userid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ آیدی باید عدد باشد:")
        return ADMIN_CHARGE_USERID

    db = load_db()
    if text not in db["users"]:
        await update.message.reply_text(f"❌ کاربر `{text}` در سیستم نیست.", parse_mode="Markdown")
        return ADMIN_CHARGE_USERID

    context.user_data["charge_uid"] = text
    user = db["users"][text]
    await update.message.reply_text(
        f"✅ کاربر پیدا شد!\n💵 موجودی فعلی: {user['balance']:,} تومان\n\nمبلغ شارژ را وارد کنید (تومان):"
    )
    return ADMIN_CHARGE_AMOUNT

async def admin_charge_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", "")
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("❌ مبلغ نامعتبر است:")
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

# ─── Admin Commands ───────────────────────────────────────────────────────────
async def approve_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
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
                    f"🎉 *سرویس شما فعال شد!*\n\n🆔 سفارش #{order_id}\n📦 {o['gb']}GB | {o['days']}روز\n\nبه زودی اطلاعات ارسال می‌شود.",
                    parse_mode="Markdown"
                )
            except:
                pass
            return
    await update.message.reply_text(f"❌ سفارش #{order_id} پیدا نشد.")

async def reject_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
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
                await context.bot.send_message(int(o["user_id"]), f"❌ سفارش #{order_id} تأیید نشد.\nبرای پیگیری پشتیبانی تماس بگیرید.")
            except:
                pass
            return
    await update.message.reply_text(f"❌ سفارش #{order_id} پیدا نشد.")

async def add_balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
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
    await update.message.reply_text(f"✅ {amount:,} تومان به `{target_uid}` اضافه شد.\nموجودی: {user['balance']:,} تومان", parse_mode="Markdown")
    try:
        await context.bot.send_message(int(target_uid), f"💰 *کیف پول شارژ شد!*\n\n➕ {amount:,} تومان\n💵 موجودی: {user['balance']:,} تومان", parse_mode="Markdown")
    except:
        pass

async def reply_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    try:
        target_uid = int(update.message.text.split("_")[1])
        context.user_data["reply_to"] = target_uid
        await update.message.reply_text(f"✏️ پیام خود را برای کاربر `{target_uid}` بنویسید:", parse_mode="Markdown")
    except:
        await update.message.reply_text("فرمت اشتباه. مثال: /reply_123456789")

# ─── Main Text Handler ────────────────────────────────────────────────────────
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
            await update.message.reply_text("❌ ارسال ناموفق.")
        return ADMIN_MENU if uid in ADMIN_IDS else MAIN_MENU

    # منوی کاربر
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

    # منوی ادمین
    if uid in ADMIN_IDS:
        if text == "👥 کاربران":
            return await admin_list_users(update, context)
        elif text == "📦 سفارشات":
            return await admin_list_orders(update, context)
        elif text == "💳 شارژ کیف پول کاربر":
            return await admin_charge_start(update, context)
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
            ],
            ADMIN_CHARGE_USERID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_charge_userid),
            ],
            ADMIN_CHARGE_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_charge_amount),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("admin", admin_panel),
        ],
        allow_reentry=True
    )

    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.Regex(r"^/approve_\d+$"), approve_order))
    app.add_handler(MessageHandler(filters.Regex(r"^/reject_\d+$"), reject_order))
    app.add_handler(MessageHandler(filters.Regex(r"^/addbalance_\d+_\d+$"), add_balance_cmd))
    app.add_handler(MessageHandler(filters.Regex(r"^/reply_\d+$"), reply_user))

    print("🤖 Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
