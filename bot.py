"""
🤖 VPN Shop Bot - نسخه ۲.۰
معماری تمیز، همه چیز با دکمه، محصولات قابل تنظیم از فایل JSON
"""
import os, json, logging, re
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════
#  تنظیمات
# ══════════════════════════════════════════════════════
BOT_TOKEN    = os.getenv("BOT_TOKEN", "YOUR_TOKEN")
ADMIN_IDS    = list(map(int, os.getenv("ADMIN_IDS", "123456789").split(",")))
CARD_NUMBER  = os.getenv("CARD_NUMBER", "6037-XXXX-XXXX-XXXX")
CARD_OWNER   = os.getenv("CARD_OWNER", "نام صاحب کارت")
SHOP_NAME    = os.getenv("SHOP_NAME", "فروشگاه VPN")

DB_FILE       = "db.json"
PRODUCTS_FILE = "products.json"

# ══════════════════════════════════════════════════════
#  States
# ══════════════════════════════════════════════════════
(
    ST_MAIN,
    ST_BROWSE_PRODUCTS, ST_SELECT_VARIANT,
    ST_PAY_METHOD, ST_WAIT_RECEIPT, ST_WALLET_TOPUP, ST_WALLET_RECEIPT,
    ST_SUPPORT_MSG,
    ST_ADMIN, ST_ADMIN_TOPUP_UID, ST_ADMIN_TOPUP_AMT,
    ST_ADMIN_REPLY, ST_ADMIN_PROD_MENU, ST_ADMIN_PROD_NEW_NAME,
    ST_ADMIN_PROD_NEW_DESC, ST_ADMIN_PROD_NEW_VARIANT,
) = range(16)

# ══════════════════════════════════════════════════════
#  Database
# ══════════════════════════════════════════════════════
def _empty_db():
    return {"users": {}, "orders": [], "support_msgs": [], "pending_wallets": []}

def load_db() -> dict:
    if not os.path.exists(DB_FILE):
        return _empty_db()
    with open(DB_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)
    for key in _empty_db():
        db.setdefault(key, _empty_db()[key])
    return db

def save_db(db: dict):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def get_user(db: dict, uid) -> dict:
    uid = str(uid)
    if uid not in db["users"]:
        db["users"][uid] = {"balance": 0, "orders": [], "username": "", "joined": now()}
    return db["users"][uid]

def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")

# ══════════════════════════════════════════════════════
#  Products
# ══════════════════════════════════════════════════════
def load_products() -> list:
    if not os.path.exists(PRODUCTS_FILE):
        return []
    with open(PRODUCTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("products", [])

def save_products(products: list):
    with open(PRODUCTS_FILE, "w", encoding="utf-8") as f:
        json.dump({"products": products}, f, ensure_ascii=False, indent=2)

def active_products() -> list:
    return [p for p in load_products() if p.get("active", True)]

# ══════════════════════════════════════════════════════
#  Keyboards
# ══════════════════════════════════════════════════════
MAIN_KB = ReplyKeyboardMarkup([
    ["🛒 خرید سرویس", "📋 سفارش‌های من"],
    ["💰 کیف پول",    "👤 حساب کاربری"],
    ["📞 پشتیبانی"]
], resize_keyboard=True)

ADMIN_KB = ReplyKeyboardMarkup([
    ["👥 کاربران",          "📦 سفارشات"],
    ["💳 شارژ کیف پول",    "📨 پیام‌های پشتیبانی"],
    ["📦 مدیریت محصولات",  "📊 آمار"],
    ["🔙 خروج از پنل"]
], resize_keyboard=True)

def back_kb(label="❌ انصراف"):
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data="go_back")]])

def main_back_ib():
    return InlineKeyboardButton("🏠 منوی اصلی", callback_data="go_main")

# ══════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════
async def notify_admins(context, text: str, kb=None):
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_message(aid, text, parse_mode="Markdown", reply_markup=kb)
        except Exception as e:
            logger.warning(f"notify_admins failed for {aid}: {e}")

async def go_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """بازگشت به منوی اصلی از هر جایی"""
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("↩️ به منوی اصلی بازگشتید.")
        await update.callback_query.message.reply_text("🏠 منوی اصلی:", reply_markup=MAIN_KB)
    else:
        await update.message.reply_text("🏠 منوی اصلی:", reply_markup=MAIN_KB)
    return ST_MAIN

async def go_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("↩️ به پنل ادمین بازگشتید.")
        await update.callback_query.message.reply_text("🔑 پنل مدیریت:", reply_markup=ADMIN_KB)
    else:
        await update.message.reply_text("🔑 پنل مدیریت:", reply_markup=ADMIN_KB)
    return ST_ADMIN

# ══════════════════════════════════════════════════════
#  /start
# ══════════════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db = load_db()
    user = get_user(db, uid)
    user["username"] = update.effective_user.username or ""
    save_db(db)
    name = update.effective_user.first_name or "کاربر"
    await update.message.reply_text(
        f"👋 سلام *{name}* عزیز!\n\n"
        f"به *{SHOP_NAME}* خوش آمدید 🔒\n"
        f"از منوی زیر گزینه مورد نظر را انتخاب کنید:",
        parse_mode="Markdown", reply_markup=MAIN_KB
    )
    return ST_MAIN

# ══════════════════════════════════════════════════════
#  خرید سرویس - انتخاب محصول
# ══════════════════════════════════════════════════════
async def browse_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prods = active_products()
    if not prods:
        await update.message.reply_text("⚠️ در حال حاضر محصولی موجود نیست.")
        return ST_MAIN

    buttons = [[InlineKeyboardButton(p["name"], callback_data=f"prod_{i}")] for i, p in enumerate(prods)]
    buttons.append([main_back_ib()])
    await update.message.reply_text(
        "🛒 *کدام سرویس را می‌خواهید؟*\n\nیک محصول انتخاب کنید:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ST_BROWSE_PRODUCTS

async def select_product_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split("_")[1])
    prods = active_products()
    if idx >= len(prods):
        await query.answer("❌ محصول پیدا نشد.", show_alert=True)
        return ST_BROWSE_PRODUCTS

    prod = prods[idx]
    context.user_data["product"] = prod
    context.user_data["prod_idx"] = idx

    buttons = []
    for vi, v in enumerate(prod["variants"]):
        label = f"{v['label']}  ←  {v['price']:,} تومان"
        buttons.append([InlineKeyboardButton(label, callback_data=f"var_{vi}")])
    buttons.append([InlineKeyboardButton("🔙 برگشت", callback_data="back_products"), main_back_ib()])

    await query.edit_message_text(
        f"📦 *{prod['name']}*\n\n"
        f"_{prod.get('description', '')}_\n\n"
        f"یک پلن انتخاب کنید:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ST_SELECT_VARIANT

async def select_variant_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    vi = int(query.data.split("_")[1])
    prod = context.user_data.get("product")
    variant = prod["variants"][vi]
    context.user_data["variant"] = variant

    uid = query.from_user.id
    db = load_db()
    user = get_user(db, uid)
    save_db(db)
    balance = user["balance"]
    total = variant["price"]

    buttons = []
    if balance >= total:
        buttons.append([InlineKeyboardButton(
            f"💰 پرداخت از کیف پول ({balance:,} تومان)",
            callback_data="pay_wallet"
        )])
    elif balance > 0:
        buttons.append([InlineKeyboardButton(
            f"💰 کیف پول ({balance:,}T - ناکافی)",
            callback_data="pay_wallet_low"
        )])
    buttons.append([InlineKeyboardButton("💳 کارت به کارت", callback_data="pay_card")])
    buttons.append([InlineKeyboardButton("🔋 شارژ کیف پول و پرداخت", callback_data="pay_topup_then_pay")])
    buttons.append([InlineKeyboardButton("🔙 برگشت", callback_data="back_variants"), main_back_ib()])

    await query.edit_message_text(
        f"📋 *خلاصه سفارش:*\n\n"
        f"📦 {prod['name']}\n"
        f"🔖 پلن: {variant['label']}\n"
        f"💰 مبلغ: *{total:,} تومان*\n"
        f"👛 موجودی شما: {balance:,} تومان\n\n"
        f"روش پرداخت را انتخاب کنید:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ST_PAY_METHOD

# ══════════════════════════════════════════════════════
#  پرداخت
# ══════════════════════════════════════════════════════
async def pay_method_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = query.from_user.id
    db = load_db()
    user = get_user(db, uid)
    prod = context.user_data["product"]
    variant = context.user_data["variant"]
    total = variant["price"]

    if data == "pay_wallet_low":
        await query.answer("موجودی کافی نیست. کیف پول را شارژ کنید.", show_alert=True)
        return ST_PAY_METHOD

    if data == "pay_topup_then_pay":
        # ذخیره سفارش معلق برای بعد از شارژ
        context.user_data["pending_order"] = {"product": prod, "variant": variant}
        await query.edit_message_text(
            f"🔋 *شارژ کیف پول*\n\n"
            f"بعد از شارژ می‌توانید سفارش را از کیف پول پرداخت کنید.\n\n"
            f"چه مبلغی واریز می‌کنید؟ (تومان)",
            parse_mode="Markdown", reply_markup=back_kb()
        )
        return ST_WALLET_TOPUP

    if data == "pay_wallet":
        # پرداخت فوری از کیف پول
        return await _finalize_wallet_pay(query, context, db, user, uid, prod, variant, total)

    if data == "pay_card":
        save_db(db)
        await query.edit_message_text(
            f"💳 *پرداخت کارت به کارت*\n\n"
            f"💰 مبلغ: *{total:,} تومان*\n"
            f"🏦 شماره کارت:\n`{CARD_NUMBER}`\n"
            f"👤 به نام: *{CARD_OWNER}*\n\n"
            f"پس از واریز، *تصویر رسید* را ارسال کنید:",
            parse_mode="Markdown", reply_markup=back_kb("❌ انصراف")
        )
        return ST_WAIT_RECEIPT

async def _finalize_wallet_pay(query_or_update, context, db, user, uid, prod, variant, total):
    """ثبت سفارش و کسر از کیف پول"""
    user["balance"] -= total
    order = _make_order(db, uid, prod, variant, "wallet", "active")
    db["orders"].append(order)
    user["orders"].append(order["id"])
    save_db(db)

    msg = (
        f"✅ *پرداخت موفق از کیف پول!*\n\n"
        f"🆔 سفارش: `#{order['id']}`\n"
        f"📦 {prod['name']} | {variant['label']}\n"
        f"💰 {total:,} تومان کسر شد\n"
        f"💵 موجودی: {user['balance']:,} تومان\n\n"
        f"⏳ ادمین به زودی سرویس را فعال می‌کند."
    )
    if hasattr(query_or_update, 'edit_message_text'):
        await query_or_update.edit_message_text(msg, parse_mode="Markdown")
    else:
        await query_or_update.message.reply_text(msg, parse_mode="Markdown")

    await notify_admins(
        context,
        f"🛒 *سفارش جدید #{order['id']}*\n"
        f"👤 ID: `{uid}`\n"
        f"📦 {prod['name']} | {variant['label']}\n"
        f"💰 {total:,} تومان (کیف پول)\n\n"
        f"✅ تأیید: /approve_{order['id']}\n"
        f"🔗 ارسال لینک: /setlink_{order['id']}"
    )
    return ST_MAIN

async def receipt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("📷 لطفاً *تصویر* رسید را ارسال کنید:", parse_mode="Markdown", reply_markup=back_kb())
        return ST_WAIT_RECEIPT

    uid = update.effective_user.id
    db = load_db()
    prod = context.user_data["product"]
    variant = context.user_data["variant"]
    order = _make_order(db, uid, prod, variant, "card", "pending_payment")
    db["orders"].append(order)
    user = get_user(db, uid)
    user["orders"].append(order["id"])
    save_db(db)

    await update.message.reply_text(
        f"✅ رسید دریافت شد!\n🆔 سفارش: `#{order['id']}`\n⏳ در انتظار تأیید ادمین...",
        parse_mode="Markdown", reply_markup=MAIN_KB
    )
    photo_id = update.message.photo[-1].file_id
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_photo(
                aid, photo_id,
                caption=(
                    f"💳 *رسید سفارش #{order['id']}*\n"
                    f"👤 {update.effective_user.first_name} | ID: `{uid}`\n"
                    f"📦 {prod['name']} | {variant['label']}\n"
                    f"💰 {variant['price']:,} تومان\n\n"
                    f"✅ /approve_{order['id']}   ❌ /reject_{order['id']}"
                ), parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"send_photo to admin failed: {e}")
    context.user_data.clear()
    return ST_MAIN

def _make_order(db, uid, prod, variant, payment, status) -> dict:
    oid = (max((o["id"] for o in db["orders"]), default=0)) + 1
    return {
        "id": oid, "user_id": str(uid),
        "product_name": prod["name"],
        "variant_label": variant["label"],
        "price": variant["price"],
        "payment": payment, "status": status,
        "config_link": None,
        "date": now()
    }

# ══════════════════════════════════════════════════════
#  شارژ کیف پول
# ══════════════════════════════════════════════════════
async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db = load_db()
    user = get_user(db, uid)
    save_db(db)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ شارژ کیف پول", callback_data="wallet_topup")],
        [main_back_ib()]
    ])
    await update.message.reply_text(
        f"💰 *کیف پول*\n\n💵 موجودی: *{user['balance']:,} تومان*",
        parse_mode="Markdown", reply_markup=kb
    )
    return ST_MAIN

async def wallet_topup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🔋 *شارژ کیف پول*\n\nچه مبلغی واریز می‌کنید؟ (تومان)\n_مثال: 100000_",
        parse_mode="Markdown", reply_markup=back_kb()
    )
    return ST_WALLET_TOPUP

async def wallet_topup_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace(",", "").strip()
    if not text.isdigit() or int(text) < 10000:
        await update.message.reply_text("❌ حداقل مبلغ ۱۰,۰۰۰ تومان است:", reply_markup=back_kb())
        return ST_WALLET_TOPUP
    amount = int(text)
    context.user_data["topup_amount"] = amount
    await update.message.reply_text(
        f"💳 *اطلاعات پرداخت*\n\n"
        f"💰 مبلغ: *{amount:,} تومان*\n"
        f"🏦 کارت:\n`{CARD_NUMBER}`\n"
        f"👤 به نام: *{CARD_OWNER}*\n\n"
        f"تصویر رسید را ارسال کنید:",
        parse_mode="Markdown", reply_markup=back_kb("❌ انصراف")
    )
    return ST_WALLET_RECEIPT

async def wallet_receipt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.photo:
        await update.message.reply_text("📷 لطفاً تصویر رسید را ارسال کنید:", reply_markup=back_kb())
        return ST_WALLET_RECEIPT

    uid = update.effective_user.id
    amount = context.user_data.get("topup_amount", 0)
    pending = context.user_data.get("pending_order")

    db = load_db()
    db["pending_wallets"].append({"user_id": str(uid), "amount": amount, "date": now()})
    save_db(db)

    # دکمه پرداخت معلق
    if pending:
        variant = pending["variant"]
        total = variant["price"]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💰 پرداخت سفارش ({total:,} تومان)", callback_data="pay_pending")],
            [main_back_ib()]
        ])
        await update.message.reply_text(
            f"✅ رسید شارژ دریافت شد!\n"
            f"💰 {amount:,} تومان\n"
            f"⏳ پس از تأیید ادمین موجودی اضافه می‌شود.\n\n"
            f"بعد از شارژ شدن کیف پولت دکمه پایین رو بزن:",
            reply_markup=kb
        )
    else:
        await update.message.reply_text(
            f"✅ رسید شارژ دریافت شد!\n💰 {amount:,} تومان\n⏳ ادمین به زودی تأیید می‌کند.",
            reply_markup=MAIN_KB
        )

    photo_id = update.message.photo[-1].file_id
    for aid in ADMIN_IDS:
        try:
            await context.bot.send_photo(
                aid, photo_id,
                caption=(
                    f"💰 *درخواست شارژ کیف پول*\n"
                    f"👤 {update.effective_user.first_name} | ID: `{uid}`\n"
                    f"💵 {amount:,} تومان\n\n"
                    f"✅ تأیید: /addbalance_{uid}_{amount}"
                ), parse_mode="Markdown"
            )
        except Exception as e:
            logger.warning(f"Failed to send wallet receipt to admin: {e}")
    return ST_MAIN

async def pay_pending_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    pending = context.user_data.get("pending_order")
    if not pending:
        await query.answer("❌ سفارشی پیدا نشد.", show_alert=True)
        return ST_MAIN

    db = load_db()
    user = get_user(db, uid)
    prod = pending["product"]
    variant = pending["variant"]
    total = variant["price"]

    if user["balance"] < total:
        await query.answer(f"❌ موجودی کافی نیست. کمبود: {total - user['balance']:,} تومان", show_alert=True)
        return ST_MAIN

    return await _finalize_wallet_pay(query, context, db, user, uid, prod, variant, total)

# ══════════════════════════════════════════════════════
#  سفارش‌های من
# ══════════════════════════════════════════════════════
STATUS_FA = {
    "pending_payment":    "⏳ انتظار تأیید پرداخت",
    "pending_activation": "⚙️ در حال فعال‌سازی",
    "active":             "✅ فعال",
    "rejected":           "❌ رد شده",
}

async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db = load_db()
    user = get_user(db, uid)
    save_db(db)

    if not user["orders"]:
        await update.message.reply_text("📭 هنوز سفارشی نداری.")
        return ST_MAIN

    orders = [o for o in db["orders"] if o["id"] in user["orders"]][-5:]
    buttons = []
    text = "📋 *سفارش‌های شما:*\n\n"
    for o in orders:
        status = STATUS_FA.get(o["status"], o["status"])
        text += f"🆔 #{o['id']} | {o['product_name']}\n{o['variant_label']}\n{status} | {o['date']}\n\n"
        if o.get("config_link"):
            buttons.append([InlineKeyboardButton(f"🔗 لینک سفارش #{o['id']}", callback_data=f"vlink_{o['id']}")])

    buttons.append([main_back_ib()])
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons))
    return ST_MAIN

async def view_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    oid = int(query.data.split("_")[1])
    uid = query.from_user.id
    db = load_db()
    order = next((o for o in db["orders"] if o["id"] == oid and o["user_id"] == str(uid)), None)
    if not order or not order.get("config_link"):
        await query.answer("❌ لینکی یافت نشد.", show_alert=True)
        return ST_MAIN
    await query.message.reply_text(
        f"🔗 *اطلاعات اتصال سفارش #{oid}*\n\n{order['config_link']}",
        parse_mode="Markdown"
    )
    return ST_MAIN

# ══════════════════════════════════════════════════════
#  حساب کاربری
# ══════════════════════════════════════════════════════
async def account_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db = load_db()
    user = get_user(db, uid)
    save_db(db)
    await update.message.reply_text(
        f"👤 *حساب کاربری*\n\n"
        f"🆔 آیدی: `{uid}`\n"
        f"💰 موجودی: {user['balance']:,} تومان\n"
        f"📦 تعداد سفارشات: {len(user['orders'])}\n"
        f"📅 عضویت: {user.get('joined', '-')}",
        parse_mode="Markdown"
    )
    return ST_MAIN

# ══════════════════════════════════════════════════════
#  پشتیبانی
# ══════════════════════════════════════════════════════
async def support_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📞 *پشتیبانی*\n\nپیام خود را بنویسید:",
        parse_mode="Markdown", reply_markup=back_kb("❌ انصراف")
    )
    return ST_SUPPORT_MSG

async def support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    msg = update.message.text
    db = load_db()
    mid = (max((m["id"] for m in db["support_msgs"]), default=0)) + 1
    db["support_msgs"].append({
        "id": mid, "user_id": str(uid),
        "name": update.effective_user.first_name or "کاربر",
        "message": msg, "answered": False, "date": now()
    })
    save_db(db)

    for aid in ADMIN_IDS:
        try:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("✏️ پاسخ", callback_data=f"areply_{mid}")]])
            await context.bot.send_message(
                aid,
                f"📞 *پیام پشتیبانی #{mid}*\n"
                f"👤 {update.effective_user.first_name} | `{uid}`\n\n"
                f"💬 {msg}",
                parse_mode="Markdown", reply_markup=kb
            )
        except Exception as e:
            logger.warning(f"Support notify failed: {e}")

    await update.message.reply_text("✅ پیامت ارسال شد. به زودی پاسخ می‌گیری.", reply_markup=MAIN_KB)
    return ST_MAIN

# ══════════════════════════════════════════════════════
#  پنل ادمین
# ══════════════════════════════════════════════════════
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return ST_MAIN
    await update.message.reply_text("🔑 *پنل مدیریت*", parse_mode="Markdown", reply_markup=ADMIN_KB)
    return ST_ADMIN

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    total_u = len(db["users"])
    total_o = len(db["orders"])
    pending = sum(1 for o in db["orders"] if o["status"] == "pending_payment")
    active = sum(1 for o in db["orders"] if o["status"] == "active")
    unanswered = sum(1 for m in db["support_msgs"] if not m.get("answered"))
    await update.message.reply_text(
        f"📊 *آمار*\n\n"
        f"👥 کاربران: {total_u}\n"
        f"📦 سفارشات: {total_o}\n"
        f"⏳ در انتظار: {pending}\n"
        f"✅ فعال: {active}\n"
        f"📨 پیام بی‌پاسخ: {unanswered}",
        parse_mode="Markdown"
    )
    return ST_ADMIN

async def admin_list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    if not db["users"]:
        await update.message.reply_text("هنوز کاربری نیست.")
        return ST_ADMIN
    text = "👥 *کاربران (۱۰ آخر):*\n\n"
    for uid, u in list(db["users"].items())[-10:]:
        text += f"🆔 `{uid}` | 💰 {u['balance']:,}T | 📦 {len(u['orders'])}سفارش\n"
    await update.message.reply_text(text, parse_mode="Markdown")
    return ST_ADMIN

async def admin_list_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    if not db["orders"]:
        await update.message.reply_text("📭 هنوز سفارشی نیست.")
        return ST_ADMIN
    text = "📦 *سفارشات (۱۰ آخر):*\n\n"
    for o in db["orders"][-10:]:
        status = STATUS_FA.get(o["status"], o["status"])
        text += (
            f"🆔 #{o['id']} | 👤 `{o['user_id']}`\n"
            f"📦 {o['product_name']} | {o['variant_label']}\n"
            f"💰 {o['price']:,}T | {status}\n"
        )
        if o["status"] == "pending_payment":
            text += f"👉 /approve_{o['id']}  /reject_{o['id']}\n"
        if o.get("config_link"):
            text += f"🔗 لینک ثبت شده ✅\n"
        else:
            text += f"🔗 /setlink_{o['id']}\n"
        text += "\n"
    await update.message.reply_text(text, parse_mode="Markdown")
    return ST_ADMIN

async def admin_support_msgs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = load_db()
    msgs = [m for m in db["support_msgs"] if not m.get("answered")]
    if not msgs:
        await update.message.reply_text("📭 هیچ پیام بی‌پاسخی ندارید.")
        return ST_ADMIN
    for m in msgs[-8:]:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✏️ پاسخ", callback_data=f"areply_{m['id']}")]])
        await update.message.reply_text(
            f"📨 *پیام #{m['id']}*\n"
            f"👤 {m['name']} | `{m['user_id']}`\n"
            f"📅 {m['date']}\n\n"
            f"💬 {m['message']}",
            parse_mode="Markdown", reply_markup=kb
        )
    return ST_ADMIN

async def admin_reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    mid = int(query.data.split("_")[1])
    db = load_db()
    msg_obj = next((m for m in db["support_msgs"] if m["id"] == mid), None)
    if not msg_obj:
        await query.answer("❌ پیام پیدا نشد.", show_alert=True)
        return ST_ADMIN
    context.user_data["reply_mid"] = mid
    context.user_data["reply_uid"] = msg_obj["user_id"]
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ انصراف", callback_data="admin_back")]])
    await query.message.reply_text(
        f"✏️ پاسخ به پیام #{mid} را بنویسید:", reply_markup=kb
    )
    return ST_ADMIN_REPLY

async def admin_reply_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target_uid = context.user_data.get("reply_uid")
    mid = context.user_data.get("reply_mid")
    try:
        await context.bot.send_message(int(target_uid),
            f"📨 *پاسخ پشتیبانی:*\n\n{update.message.text}", parse_mode="Markdown")
        db = load_db()
        for m in db["support_msgs"]:
            if m["id"] == mid:
                m["answered"] = True
        save_db(db)
        await update.message.reply_text("✅ پاسخ ارسال شد.", reply_markup=ADMIN_KB)
    except:
        await update.message.reply_text("❌ ارسال ناموفق (کاربر بلاک کرده).", reply_markup=ADMIN_KB)
    context.user_data.clear()
    return ST_ADMIN

# ══════════════════════════════════════════════════════
#  مدیریت محصولات (ادمین)
# ══════════════════════════════════════════════════════
async def admin_products_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prods = load_products()
    buttons = []
    for i, p in enumerate(prods):
        status = "✅" if p.get("active") else "❌"
        buttons.append([InlineKeyboardButton(f"{status} {p['name']}", callback_data=f"aprod_{i}")])
    buttons.append([InlineKeyboardButton("➕ محصول جدید", callback_data="aprod_new")])
    buttons.append([InlineKeyboardButton("🔙 برگشت", callback_data="admin_back")])
    await update.message.reply_text(
        "📦 *مدیریت محصولات:*\n\nروی محصول بزن تا ویرایش/حذف کنی:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ST_ADMIN_PROD_MENU

async def admin_product_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "aprod_new":
        await query.edit_message_text(
            "📦 *محصول جدید*\n\nنام محصول را بنویسید:",
            parse_mode="Markdown", reply_markup=back_kb("❌ انصراف")
        )
        return ST_ADMIN_PROD_NEW_NAME

    idx = int(query.data.split("_")[1])
    prods = load_products()
    if idx >= len(prods):
        await query.answer("❌ محصول پیدا نشد.", show_alert=True)
        return ST_ADMIN_PROD_MENU

    prod = prods[idx]
    context.user_data["edit_prod_idx"] = idx
    toggle_label = "❌ غیرفعال کن" if prod.get("active") else "✅ فعال کن"
    variants_text = "\n".join(f"  • {v['label']} → {v['price']:,}T" for v in prod.get("variants", []))

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data=f"atoggle_{idx}")],
        [InlineKeyboardButton("🗑 حذف محصول", callback_data=f"adelete_{idx}")],
        [InlineKeyboardButton("🔙 برگشت", callback_data="admin_back")]
    ])
    await query.edit_message_text(
        f"📦 *{prod['name']}*\n"
        f"_{prod.get('description', '')}_\n\n"
        f"وضعیت: {'✅ فعال' if prod.get('active') else '❌ غیرفعال'}\n\n"
        f"پلن‌ها:\n{variants_text}",
        parse_mode="Markdown", reply_markup=kb
    )
    return ST_ADMIN_PROD_MENU

async def admin_toggle_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split("_")[1])
    prods = load_products()
    prods[idx]["active"] = not prods[idx].get("active", True)
    save_products(prods)
    status = "✅ فعال" if prods[idx]["active"] else "❌ غیرفعال"
    await query.answer(f"محصول {status} شد.", show_alert=True)
    await query.edit_message_text(f"وضعیت محصول «{prods[idx]['name']}» به {status} تغییر کرد.")
    return ST_ADMIN_PROD_MENU

async def admin_delete_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = int(query.data.split("_")[1])
    prods = load_products()
    removed = prods.pop(idx)
    save_products(prods)
    await query.edit_message_text(f"🗑 محصول «{removed['name']}» حذف شد.")
    return ST_ADMIN_PROD_MENU

async def admin_new_prod_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_prod"] = {"name": update.message.text.strip(), "active": True, "variants": []}
    await update.message.reply_text(
        "📝 توضیح کوتاه محصول را بنویسید:\n_(مثال: فیلترشکن پرسرعت VLESS)_",
        parse_mode="Markdown", reply_markup=back_kb()
    )
    return ST_ADMIN_PROD_NEW_DESC

async def admin_new_prod_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_prod"]["description"] = update.message.text.strip()
    await update.message.reply_text(
        "📦 پلن‌های این محصول را اضافه کنید.\n\n"
        "فرمت: `نام | قیمت` (هر پلن یک خط)\n"
        "مثال:\n`۱ ماه - ۱۰ گیگ | 50000`\n`۳ ماه - ۳۰ گیگ | 120000`",
        parse_mode="Markdown", reply_markup=back_kb()
    )
    return ST_ADMIN_PROD_NEW_VARIANT

async def admin_new_prod_variants(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = update.message.text.strip().split("\n")
    variants = []
    for line in lines:
        parts = line.split("|")
        if len(parts) == 2:
            label = parts[0].strip()
            price_str = parts[1].strip().replace(",", "")
            if price_str.isdigit():
                variants.append({"label": label, "price": int(price_str)})

    if not variants:
        await update.message.reply_text("❌ فرمت اشتباه. دوباره امتحان کن:", reply_markup=back_kb())
        return ST_ADMIN_PROD_NEW_VARIANT

    new_prod = context.user_data["new_prod"]
    new_prod["variants"] = variants
    new_prod["id"] = f"prod_{now().replace(' ', '_').replace(':', '-')}"

    prods = load_products()
    prods.append(new_prod)
    save_products(prods)

    context.user_data.clear()
    await update.message.reply_text(
        f"✅ محصول *{new_prod['name']}* با {len(variants)} پلن اضافه شد!",
        parse_mode="Markdown", reply_markup=ADMIN_KB
    )
    return ST_ADMIN

# ══════════════════════════════════════════════════════
#  شارژ کیف پول ادمین
# ══════════════════════════════════════════════════════
async def admin_topup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💳 *شارژ کیف پول*\n\nآیدی عددی کاربر را وارد کنید:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ انصراف", callback_data="admin_back")]])
    )
    return ST_ADMIN_TOPUP_UID

async def admin_topup_uid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("❌ آیدی باید عدد باشد:")
        return ST_ADMIN_TOPUP_UID
    db = load_db()
    if text not in db["users"]:
        await update.message.reply_text(f"❌ کاربر `{text}` پیدا نشد.", parse_mode="Markdown")
        return ST_ADMIN_TOPUP_UID
    context.user_data["topup_uid"] = text
    user = db["users"][text]
    await update.message.reply_text(
        f"✅ کاربر پیدا شد.\n💵 موجودی: {user['balance']:,} تومان\n\nمبلغ شارژ (تومان):"
    )
    return ST_ADMIN_TOPUP_AMT

async def admin_topup_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(",", "")
    if not text.isdigit() or int(text) <= 0:
        await update.message.reply_text("❌ مبلغ نامعتبر:")
        return ST_ADMIN_TOPUP_AMT
    amount = int(text)
    uid = context.user_data["topup_uid"]
    db = load_db()
    user = get_user(db, uid)
    user["balance"] += amount
    save_db(db)
    await update.message.reply_text(
        f"✅ {amount:,} تومان به `{uid}` اضافه شد.\n💵 موجودی: {user['balance']:,} تومان",
        parse_mode="Markdown", reply_markup=ADMIN_KB
    )
    try:
        await context.bot.send_message(int(uid),
            f"💰 *کیف پول شارژ شد!*\n\n➕ {amount:,} تومان\n💵 موجودی: {user['balance']:,} تومان",
            parse_mode="Markdown")
    except:
        pass
    context.user_data.clear()
    return ST_ADMIN

# ══════════════════════════════════════════════════════
#  کامندهای ادمین (group=-1، همیشه کار می‌کنن)
# ══════════════════════════════════════════════════════
async def cmd_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    m = re.match(r"^/approve_?(\d+)$", update.message.text.strip())
    if not m:
        await update.message.reply_text("فرمت: /approve_5")
        return
    oid = int(m.group(1))
    db = load_db()
    order = next((o for o in db["orders"] if o["id"] == oid), None)
    if not order:
        await update.message.reply_text(f"❌ سفارش #{oid} پیدا نشد.")
        return
    order["status"] = "active"
    save_db(db)

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 ارسال لینک به خریدار", callback_data=f"asendlink_{oid}")]])
    await update.message.reply_text(
        f"✅ سفارش #{oid} تأیید شد.\nآیا می‌خواهید لینک سرویس را ارسال کنید؟",
        reply_markup=kb
    )
    try:
        await context.bot.send_message(int(order["user_id"]),
            f"🎉 *سرویس شما فعال شد!*\n\n🆔 سفارش #{oid}\n📦 {order['product_name']} | {order['variant_label']}\n\nبه زودی لینک اتصال ارسال می‌شود.",
            parse_mode="Markdown")
    except:
        pass

async def cmd_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    m = re.match(r"^/reject_?(\d+)$", update.message.text.strip())
    if not m:
        await update.message.reply_text("فرمت: /reject_5")
        return
    oid = int(m.group(1))
    db = load_db()
    order = next((o for o in db["orders"] if o["id"] == oid), None)
    if not order:
        await update.message.reply_text(f"❌ سفارش #{oid} پیدا نشد.")
        return
    order["status"] = "rejected"
    save_db(db)
    await update.message.reply_text(f"❌ سفارش #{oid} رد شد.")
    try:
        await context.bot.send_message(int(order["user_id"]),
            f"❌ سفارش #{oid} تأیید نشد.\nبرای پیگیری پشتیبانی تماس بگیرید.")
    except:
        pass

async def cmd_addbalance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    m = re.match(r"^/addbalance_?(\d+)_(\d+)$", update.message.text.strip())
    if not m:
        await update.message.reply_text("فرمت: /addbalance_123456_50000")
        return
    uid, amount = m.group(1), int(m.group(2))
    db = load_db()
    user = get_user(db, uid)
    user["balance"] += amount
    save_db(db)
    await update.message.reply_text(f"✅ {amount:,}T به `{uid}` اضافه شد.\nموجودی: {user['balance']:,}T", parse_mode="Markdown")
    try:
        await context.bot.send_message(int(uid),
            f"💰 *کیف پول شارژ شد!*\n➕ {amount:,} تومان\n💵 موجودی: {user['balance']:,} تومان",
            parse_mode="Markdown")
    except:
        pass

async def cmd_setlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    m = re.match(r"^/setlink_?(\d+)(?:\s+([\s\S]+))?$", update.message.text.strip())
    if not m:
        await update.message.reply_text("فرمت: /setlink_5 vless://...")
        return
    oid = int(m.group(1))
    link = m.group(2)
    db = load_db()
    order = next((o for o in db["orders"] if o["id"] == oid), None)
    if not order:
        await update.message.reply_text(f"❌ سفارش #{oid} پیدا نشد.")
        return
    if not link:
        context.user_data["setlink_oid"] = oid
        context.user_data["setlink_uid"] = order["user_id"]
        await update.message.reply_text(
            f"🔗 لینک سفارش #{oid} را بفرستید:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ انصراف", callback_data="admin_back")]])
        )
        return
    order["config_link"] = link
    save_db(db)
    await update.message.reply_text(f"✅ لینک سفارش #{oid} ذخیره شد.")
    try:
        await context.bot.send_message(int(order["user_id"]),
            f"🔗 *اطلاعات اتصال سفارش #{oid}*\n\n{link}", parse_mode="Markdown")
    except:
        pass

# ══════════════════════════════════════════════════════
#  Callback Router
# ══════════════════════════════════════════════════════
async def global_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    if data == "go_main" or data == "go_back":
        return await go_main(update, context)
    if data == "admin_back":
        return await go_admin(update, context)
    if data == "wallet_topup":
        return await wallet_topup_callback(update, context)
    if data == "pay_pending":
        return await pay_pending_callback(update, context)
    if data.startswith("prod_"):
        return await select_product_callback(update, context)
    if data.startswith("var_"):
        return await select_variant_callback(update, context)
    if data.startswith("pay_"):
        return await pay_method_callback(update, context)
    if data.startswith("vlink_"):
        return await view_link_callback(update, context)
    if data == "back_products":
        return await browse_products_cb(update, context)
    if data == "back_variants":
        return await back_to_variants(update, context)
    if data.startswith("areply_"):
        return await admin_reply_callback(update, context)
    if data.startswith("aprod_"):
        return await admin_product_callback(update, context)
    if data.startswith("atoggle_"):
        return await admin_toggle_product(update, context)
    if data.startswith("adelete_"):
        return await admin_delete_product(update, context)
    if data.startswith("asendlink_"):
        oid = int(data.split("_")[1])
        db = load_db()
        order = next((o for o in db["orders"] if o["id"] == oid), None)
        if order:
            context.user_data["setlink_oid"] = oid
            context.user_data["setlink_uid"] = order["user_id"]
            await query.answer()
            await query.message.reply_text(
                f"🔗 لینک/کانفیگ سفارش #{oid} را بفرستید:",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ انصراف", callback_data="admin_back")]])
            )
            return ST_ADMIN_REPLY
        await query.answer("❌ سفارش پیدا نشد.", show_alert=True)
    await query.answer()

async def browse_products_cb(update, context):
    query = update.callback_query
    prods = active_products()
    buttons = [[InlineKeyboardButton(p["name"], callback_data=f"prod_{i}")] for i, p in enumerate(prods)]
    buttons.append([main_back_ib()])
    await query.edit_message_text(
        "🛒 *کدام سرویس را می‌خواهید؟*",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ST_BROWSE_PRODUCTS

async def back_to_variants(update, context):
    query = update.callback_query
    prod = context.user_data.get("product")
    if not prod:
        return await go_main(update, context)
    buttons = [[InlineKeyboardButton(f"{v['label']}  ←  {v['price']:,}T", callback_data=f"var_{vi}")] for vi, v in enumerate(prod["variants"])]
    buttons.append([InlineKeyboardButton("🔙 برگشت", callback_data="back_products"), main_back_ib()])
    await query.edit_message_text(
        f"📦 *{prod['name']}*\n\nیک پلن انتخاب کنید:",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ST_SELECT_VARIANT

# ══════════════════════════════════════════════════════
#  Text Router (منوی اصلی و ادمین)
# ══════════════════════════════════════════════════════
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    # setlink پس از درخواست
    if "setlink_oid" in context.user_data and uid in ADMIN_IDS:
        oid = context.user_data.pop("setlink_oid")
        target_uid = context.user_data.pop("setlink_uid", None)
        db = load_db()
        order = next((o for o in db["orders"] if o["id"] == oid), None)
        if order:
            order["config_link"] = text
            save_db(db)
            await update.message.reply_text(f"✅ لینک سفارش #{oid} ذخیره شد.", reply_markup=ADMIN_KB)
            if target_uid:
                try:
                    await context.bot.send_message(int(target_uid),
                        f"🔗 *اطلاعات اتصال سفارش #{oid}*\n\n{text}", parse_mode="Markdown")
                except:
                    pass
        return ST_ADMIN

    route = {
        "🛒 خرید سرویس":      browse_products,
        "📋 سفارش‌های من":     my_orders,
        "💰 کیف پول":         wallet_menu,
        "👤 حساب کاربری":     account_info,
        "📞 پشتیبانی":        support_start,
    }
    if text in route:
        return await route[text](update, context)

    if uid in ADMIN_IDS:
        admin_route = {
            "👥 کاربران":          admin_list_users,
            "📦 سفارشات":          admin_list_orders,
            "💳 شارژ کیف پول":     admin_topup_start,
            "📨 پیام‌های پشتیبانی": admin_support_msgs,
            "📦 مدیریت محصولات":   admin_products_menu,
            "📊 آمار":             admin_stats,
            "🔙 خروج از پنل":      lambda u, c: go_main(u, c),
        }
        if text in admin_route:
            return await admin_route[text](update, context)

    await update.message.reply_text("لطفاً از منو استفاده کنید.", reply_markup=MAIN_KB)
    return ST_MAIN

# ══════════════════════════════════════════════════════
#  اجرا
# ══════════════════════════════════════════════════════
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            CommandHandler("admin", admin_panel),
        ],
        states={
            ST_MAIN:              [MessageHandler(filters.TEXT & ~filters.COMMAND, text_router),
                                   CallbackQueryHandler(global_callback)],
            ST_BROWSE_PRODUCTS:   [CallbackQueryHandler(global_callback)],
            ST_SELECT_VARIANT:    [CallbackQueryHandler(global_callback)],
            ST_PAY_METHOD:        [CallbackQueryHandler(global_callback)],
            ST_WAIT_RECEIPT:      [MessageHandler(filters.PHOTO, receipt_handler),
                                   MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: u.message.reply_text("📷 تصویر رسید ارسال کنید:")),
                                   CallbackQueryHandler(global_callback)],
            ST_WALLET_TOPUP:      [MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_topup_amount),
                                   CallbackQueryHandler(global_callback)],
            ST_WALLET_RECEIPT:    [MessageHandler(filters.PHOTO, wallet_receipt_handler),
                                   MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: u.message.reply_text("📷 تصویر رسید ارسال کنید:")),
                                   CallbackQueryHandler(global_callback)],
            ST_SUPPORT_MSG:       [MessageHandler(filters.TEXT & ~filters.COMMAND, support_message),
                                   CallbackQueryHandler(global_callback)],
            ST_ADMIN:             [MessageHandler(filters.TEXT & ~filters.COMMAND, text_router),
                                   CallbackQueryHandler(global_callback)],
            ST_ADMIN_TOPUP_UID:   [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_topup_uid),
                                   CallbackQueryHandler(global_callback)],
            ST_ADMIN_TOPUP_AMT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_topup_amount),
                                   CallbackQueryHandler(global_callback)],
            ST_ADMIN_REPLY:       [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_reply_text),
                                   CallbackQueryHandler(global_callback)],
            ST_ADMIN_PROD_MENU:   [CallbackQueryHandler(global_callback),
                                   MessageHandler(filters.TEXT & ~filters.COMMAND, text_router)],
            ST_ADMIN_PROD_NEW_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_new_prod_name),
                                        CallbackQueryHandler(global_callback)],
            ST_ADMIN_PROD_NEW_DESC:    [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_new_prod_desc),
                                        CallbackQueryHandler(global_callback)],
            ST_ADMIN_PROD_NEW_VARIANT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_new_prod_variants),
                                        CallbackQueryHandler(global_callback)],
        },
        fallbacks=[
            CommandHandler("start", cmd_start),
            CommandHandler("admin", admin_panel),
        ],
        allow_reentry=True
    )

    # کامندهای ادمین - قبل از همه چیز اجرا میشن (group=-1)
    app.add_handler(MessageHandler(filters.Regex(r"^/approve_?\d+$"),      cmd_approve),    group=-1)
    app.add_handler(MessageHandler(filters.Regex(r"^/reject_?\d+$"),       cmd_reject),     group=-1)
    app.add_handler(MessageHandler(filters.Regex(r"^/addbalance_?\d+_\d+$"), cmd_addbalance), group=-1)
    app.add_handler(MessageHandler(filters.Regex(r"^/setlink_?\d+"),       cmd_setlink),    group=-1)

    app.add_handler(conv)

    logger.info("🤖 Bot v2.0 started!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
