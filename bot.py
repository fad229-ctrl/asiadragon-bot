import os, io, base64, logging, asyncio, anthropic
from supabase import create_client
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from datetime import datetime, timedelta
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# ─── Конфигурация ────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_KEY  = os.environ["ANTHROPIC_API_KEY"]
SUPABASE_URL   = os.environ["SUPABASE_URL"]
SUPABASE_KEY   = os.environ["SUPABASE_SERVICE_KEY"]
MANAGER_IDS    = list(map(int, os.environ.get("ALLOWED_USER_IDS","").split(","))) if os.environ.get("ALLOWED_USER_IDS") else []

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
ai       = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
logging.basicConfig(level=logging.INFO)

# ─── Права доступа ───────────────────────────────────────────────
def is_manager(uid):
    # Если список менеджеров не задан — все считаются менеджерами КРОМЕ зарегистрированных сотрудников
    if not MANAGER_IDS:
        worker = supabase.table("staff").select("id").eq("telegram_id", uid).eq("is_active", True).execute().data
        return not bool(worker)
    return uid in MANAGER_IDS

def is_worker(uid):
    r = supabase.table("staff").select("id").eq("telegram_id", uid).eq("is_active", True).execute().data
    return bool(r)

def get_staff(uid):
    r = supabase.table("staff").select("*").eq("telegram_id", uid).eq("is_active", True).execute().data
    return r[0] if r else None

# ─── Форматирование ──────────────────────────────────────────────
def fmt(n, suffix="€"):
    if n is None: return "—"
    return f"{float(n):,.2f} {suffix}".replace(",","X").replace(".",",").replace("X",".")

def short(s, n=28): return s[:n]+"…" if len(str(s))>n else str(s)



def back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главное меню", callback_data="dashboard")]])

# ─── Языки / Sprachen / Ngôn ngữ ─────────────────────────────────
LANG = {
    "ru": {
        "welcome":       "👋 Привет, *{name}*!\n\nЗдесь ты можешь заказать продукты для ресторана.",
        "btn_order":     "🛒 Сделать заказ",
        "btn_myorders":  "📋 Мои заказы",
        "order_title":   "🛒 *Новый заказ*",
        "low_hint":      "💡 *На складе заканчивается:*",
        "order_prompt":  "Напиши что нужно — в любом формате:\n_Лосось 10кг, авокадо 2кг_\n\nКогда всё написал — напиши *готово*",
        "recorded":      "📝 Записал. Продолжай или напиши *готово*",
        "sent":          "✅ *Заказ #{id} отправлен!*\n\n{items}\n\n⏳ Ожидай подтверждения.",
        "approved":      "✅ Твой заказ одобрен! Продукты будут заказаны.",
        "rejected":      "❌ Твой заказ отклонён.",
        "empty":         "Список пустой! Напиши что нужно заказать.",
        "my_orders":     "📋 *Твои заказы:*",
        "no_orders":     "У тебя ещё нет заказов.",
        "done_words":    ["готово","отправить","send","fertig","done","ok","ок","xong","сделано"],
    },
    "de": {
        "welcome":       "👋 Hallo, *{name}*!\n\nHier kannst du Produkte für das Restaurant bestellen.",
        "btn_order":     "🛒 Bestellung aufgeben",
        "btn_myorders":  "📋 Meine Bestellungen",
        "order_title":   "🛒 *Neue Bestellung*",
        "low_hint":      "💡 *Fast leer im Lager:*",
        "order_prompt":  "Schreib was du brauchst — in beliebigem Format:\n_Lachs 10kg, Avocado 2kg_\n\nWenn fertig — schreib *fertig*",
        "recorded":      "📝 Notiert. Weiter schreiben oder *fertig* tippen",
        "sent":          "✅ *Bestellung #{id} gesendet!*\n\n{items}\n\n⏳ Warte auf Bestätigung.",
        "approved":      "✅ Deine Bestellung wurde genehmigt!",
        "rejected":      "❌ Deine Bestellung wurde abgelehnt.",
        "empty":         "Liste ist leer! Schreib was bestellt werden soll.",
        "my_orders":     "📋 *Deine Bestellungen:*",
        "no_orders":     "Du hast noch keine Bestellungen.",
        "done_words":    ["fertig","done","send","готово","ok","xong","сделано"],
    },
    "vi": {
        "welcome":       "👋 Xin chào, *{name}*!\n\nBạn có thể đặt hàng thực phẩm cho nhà hàng tại đây.",
        "btn_order":     "🛒 Đặt hàng",
        "btn_myorders":  "📋 Đơn hàng của tôi",
        "order_title":   "🛒 *Đơn hàng mới*",
        "low_hint":      "💡 *Sắp hết trong kho:*",
        "order_prompt":  "Viết những gì bạn cần — theo bất kỳ định dạng nào:\n_Cá hồi 10kg, bơ 2kg_\n\nKhi xong — gõ *xong*",
        "recorded":      "📝 Đã ghi lại. Tiếp tục viết hoặc gõ *xong*",
        "sent":          "✅ *Đơn hàng #{id} đã gửi!*\n\n{items}\n\n⏳ Chờ xác nhận.",
        "approved":      "✅ Đơn hàng của bạn đã được duyệt!",
        "rejected":      "❌ Đơn hàng của bạn bị từ chối.",
        "empty":         "Danh sách trống! Hãy viết những gì cần đặt.",
        "my_orders":     "📋 *Đơn hàng của tôi:*",
        "no_orders":     "Bạn chưa có đơn hàng nào.",
        "done_words":    ["xong","done","fertig","готово","ok","send","сделано"],
    },
}

def t(uid, key, **kwargs):
    """Получить перевод для пользователя"""
    st = get_staff(uid)
    lang = st.get("language", "ru") if st else "ru"
    if lang not in LANG: lang = "ru"
    text = LANG[lang].get(key, LANG["ru"].get(key, key))
    return text.format(**kwargs) if kwargs else text

def is_done_word(uid, text):
    """Проверить что написано 'готово' на любом языке"""
    st = get_staff(uid)
    lang = st.get("language","ru") if st else "ru"
    words = LANG.get(lang, LANG["ru"])["done_words"]
    return text.lower().strip() in words


# ─── Графики ─────────────────────────────────────────────────────
DARK_BG = "#0d1117"; CARD_BG = "#161b22"
ACCENT = "#e8a045"; GREEN = "#3fb950"; RED = "#f85149"
ORANGE = "#ff7b72"; BLUE = "#58a6ff"; TEXT = "#c9d1d9"; SUBTEXT = "#8b949e"

def setup_fig(w=12, h=7):
    fig, ax = plt.subplots(figsize=(w, h))
    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(CARD_BG)
    ax.tick_params(colors=TEXT, labelsize=11)
    ax.spines[:].set_visible(False)
    return fig, ax

def bar_chart(labels, values, title, subtitle="", color=ACCENT, unit=""):
    fig, ax = setup_fig(12, max(5, len(labels)*0.7+2))
    y = range(len(labels))
    bars = ax.barh(list(y), values, color=color, height=0.6, edgecolor="none")
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, color=TEXT, fontsize=11)
    ax.invert_yaxis()
    mx = max(values) if values else 1
    for bar, val in zip(bars, values):
        lbl = f"{val:,.1f}{unit}" if unit else f"{val:,.0f}"
        ax.text(bar.get_width()+mx*0.01, bar.get_y()+bar.get_height()/2,
                lbl, va="center", color=TEXT, fontsize=11, fontweight="bold")
    ax.set_xlim(0, mx*1.2)
    ax.xaxis.set_visible(False)
    fig.text(0.02, 0.98, title, color=TEXT, fontsize=14, fontweight="bold", va="top")
    if subtitle: fig.text(0.02, 0.93, subtitle, color=SUBTEXT, fontsize=10, va="top")
    plt.tight_layout(rect=[0,0,1,0.92])
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    buf.seek(0); plt.close(); return buf

def stock_level_chart(items):
    if not items: return None
    labels = [short(x["name"], 25) for x in items[:12]]
    values = [x["pct"] for x in items[:12]]
    colors = [RED if v<30 else ORANGE if v<70 else GREEN for v in values]
    fig, ax = setup_fig(12, max(5, len(labels)*0.75+2))
    y = range(len(labels))
    ax.barh(list(y), values, color=colors, height=0.6, edgecolor="none")
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, color=TEXT, fontsize=11)
    ax.invert_yaxis()
    ax.axvline(100, color="#30363d", linestyle="--", linewidth=1.5, alpha=0.7)
    for i, (val, item) in enumerate(zip(values, items[:12])):
        ax.text(val+1, i, f"{val:.0f}%  ({item['qty']:.1f}/{item['min']:.0f} {item['unit']})",
                va="center", color=TEXT, fontsize=10)
    ax.set_xlim(0, 130)
    ax.xaxis.set_visible(False)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=RED,label="Критично <30%"),Patch(color=ORANGE,label="Мало <70%"),Patch(color=GREEN,label="Норма")],
              loc="lower right", facecolor=CARD_BG, edgecolor="#30363d", labelcolor=TEXT, fontsize=10)
    fig.text(0.02, 0.98, "⚠️ Уровень запасов", color=TEXT, fontsize=14, fontweight="bold", va="top")
    fig.text(0.02, 0.93, "% от минимального остатка", color=SUBTEXT, fontsize=10, va="top")
    plt.tight_layout(rect=[0,0,1,0.92])
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    buf.seek(0); plt.close(); return buf

# ─── Главное меню ────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    try:
        # Сначала проверяем — сотрудник?
        worker = is_worker(uid)
        manager = is_manager(uid)

        if worker and not manager:
            # Это сотрудник — показываем его панель
            st = get_staff(uid)
            if not st:
                await update.message.reply_text("❌ Ты не зарегистрирован. Обратись к менеджеру.")
                return
            # Если язык ещё не выбран
            if not st.get("language"):
                keyboard = [
                    [InlineKeyboardButton("🇷🇺 Русский", callback_data="setlang_ru")],
                    [InlineKeyboardButton("🇩🇪 Deutsch", callback_data="setlang_de")],
                    [InlineKeyboardButton("🇻🇳 Tiếng Việt", callback_data="setlang_vi")],
                ]
                await update.message.reply_text(
                    "👋 Привет! / Hallo! / Xin chào!\n\nВыбери язык / Sprache wählen / Chọn ngôn ngữ:",
                    reply_markup=InlineKeyboardMarkup(keyboard))
                return
            # Язык выбран — показываем меню сотрудника
            keyboard = [
                [InlineKeyboardButton(t(uid,"btn_order"), callback_data="worker_order")],
                [InlineKeyboardButton(t(uid,"btn_myorders"), callback_data="worker_my_orders")],
            ]
            await update.message.reply_text(
                t(uid, "welcome", name=st["name"]),
                parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
            return

        if manager:
            # Это менеджер — показываем дашборд
            await send_quick_dashboard(update.message)
            return

        # Неизвестный пользователь
        await update.message.reply_text("⛔ Нет доступа. Обратись к менеджеру.")

    except Exception as e:
        logging.error(f"Error in start for uid={uid}: {e}")
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def send_quick_dashboard(msg):
    r  = supabase.table("stock").select("quantity,last_purchase_price,min_quantity").execute().data
    lagerwert = sum(float(x["quantity"] or 0)*float(x["last_purchase_price"] or 0) for x in r if x["last_purchase_price"])
    knapp     = sum(1 for x in r if x["min_quantity"] and float(x["quantity"] or 0) < float(x["min_quantity"] or 0))
    week_ago  = (datetime.now()-timedelta(days=7)).strftime("%Y-%m-%d")
    r3        = supabase.table("documents").select("total_brutto,total_netto").gte("doc_date", week_ago).execute().data
    week_sum  = sum(float(x.get("total_brutto") or x.get("total_netto") or 0) for x in r3)
    r4        = supabase.table("order_requests").select("id").eq("status","pending").execute().data
    r5        = supabase.table("price_history").select("id").gte("price_date", week_ago).execute().data

    text = (f"🐉 *Asia Dragon — Дашборд*\n━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Стоимость склада: *{fmt(lagerwert)}*\n"
            f"⚠️ Товары заканчиваются: *{knapp}*\n"
            f"📦 Закупки за неделю: *{fmt(week_sum)}*\n"
            f"🔔 Новые заказы от сотрудников: *{len(r4)}*\n"
            f"📈 Изменения цен: *{len(r5)}*\n━━━━━━━━━━━━━━━━━━━━━━")
    keyboard = [
        [InlineKeyboardButton("⚠️ Что заканчивается", callback_data="stock_low"),
         InlineKeyboardButton("📦 Закупки", callback_data="purchases")],
        [InlineKeyboardButton("🔔 Заказы сотрудников", callback_data="staff_orders"),
         InlineKeyboardButton("📈 Цены изменились", callback_data="price_changes")],
        [InlineKeyboardButton("📊 Склад по группам", callback_data="stock_groups"),
         InlineKeyboardButton("🧾 Загрузить чек", callback_data="upload_receipt")],
        [InlineKeyboardButton("📉 Аналитика", callback_data="analytics"),
         InlineKeyboardButton("🤖 Спросить AI", callback_data="ask_ai")],
        [InlineKeyboardButton("📋 Каталог поставщиков", callback_data="catalog")],
        [InlineKeyboardButton("👥 Управление сотрудниками", callback_data="manage_staff")],
    ]
    await msg.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

# ─── Товары заканчиваются ────────────────────────────────────────
async def stock_low(update, ctx):
    msg = update.message or update.callback_query.message
    r = supabase.table("stock").select("product_id,quantity,unit,min_quantity").execute().data
    p = {x["id"]: x for x in supabase.table("products").select("id,product_name,last_lieferant").execute().data}
    items = []
    for x in r:
        if x["min_quantity"] and float(x["quantity"] or 0) < float(x["min_quantity"] or 0):
            prod = p.get(x["product_id"], {})
            pct  = float(x["quantity"] or 0)/float(x["min_quantity"])*100
            items.append({"name":prod.get("product_name","?"),"qty":float(x["quantity"] or 0),
                         "min":float(x["min_quantity"]),"unit":x["unit"] or "",
                         "lieferant":prod.get("last_lieferant","?"),"pct":round(pct,1)})
    items.sort(key=lambda x: x["pct"])
    if not items: await msg.reply_text("✅ Все товары в норме!"); return
    buf = stock_level_chart(items)
    caption = f"⚠️ *Заканчивается {len(items)} товаров*\n\n"
    for x in items[:8]:
        emoji = "🔴" if x["pct"]<30 else "🟡"
        caption += f"{emoji} *{short(x['name'])}*\n   {x['qty']:.1f}/{x['min']:.0f} {x['unit']} → _{x['lieferant']}_\n"
    if len(items)>8: caption += f"\n_...ещё {len(items)-8} товаров_"
    await msg.reply_photo(buf, caption=caption, parse_mode="Markdown", reply_markup=back_kb())

# ─── Изменения цен ───────────────────────────────────────────────
async def price_changes(update, ctx):
    msg = update.message or update.callback_query.message
    r = supabase.table("price_history").select("*").order("created_at", desc=True).limit(20).execute().data
    p = {x["id"]: x["product_name"] for x in supabase.table("products").select("id,product_name").execute().data}
    if not r: await msg.reply_text("📈 Изменений цен пока нет.\nПоявятся после следующих закупок."); return
    text = "📈 *Изменения цен*\n━━━━━━━━━━━━━━━━━━━━\n"
    for x in r[:15]:
        arrow = "🔴 ↑" if float(x["change_pct"] or 0)>0 else "🟢 ↓"
        text += f"{arrow} *{short(p.get(x['product_id'],'?'))}*\n"
        text += f"   {fmt(x['old_price'])} → {fmt(x['new_price'])} ({x['change_pct']:+.1f}%)\n"
        text += f"   _{x['lieferant_key']} | {x['price_date']}_\n"
    await msg.reply_text(text, parse_mode="Markdown", reply_markup=back_kb())

# ─── Склад по группам ────────────────────────────────────────────
async def stock_groups(update, ctx):
    msg = update.message or update.callback_query.message
    keyboard = [
        [InlineKeyboardButton("🍺 Auerbräu", callback_data="sg_auerbraeu"),
         InlineKeyboardButton("🛒 Kaufland", callback_data="sg_kaufland")],
        [InlineKeyboardButton("🥩 Kagerer", callback_data="sg_kagerer"),
         InlineKeyboardButton("🌏 Asia Markt", callback_data="sg_asia_markt")],
        [InlineKeyboardButton("🥬 Feldbrach/Özpack", callback_data="sg_feldbrach"),
         InlineKeyboardButton("📦 Все", callback_data="sg_all")],
    ]
    await msg.reply_text("📊 *Выбери поставщика:*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def stock_by_supplier(update, ctx, lieferant):
    msg = update.callback_query.message
    r     = supabase.table("stock").select("product_id,quantity,unit,min_quantity,last_purchase_price").execute().data
    p_all = supabase.table("products").select("id,product_name,last_lieferant").execute().data
    p_map = {x["id"]: x for x in p_all} if lieferant=="all" else {x["id"]: x for x in p_all if x.get("last_lieferant","").lower()==lieferant}
    items = []
    for x in r:
        if x["product_id"] in p_map:
            qty = float(x["quantity"] or 0); mn = float(x["min_quantity"] or 0)
            items.append({"name":p_map[x["product_id"]]["product_name"],"qty":qty,"unit":x["unit"] or "",
                         "min":mn,"price":float(x["last_purchase_price"] or 0),"pct":qty/mn*100 if mn>0 else 100})
    items.sort(key=lambda x: x["pct"])
    if not items: await msg.reply_text(f"Нет товаров: {lieferant}"); return
    names  = [short(x["name"],30) for x in items[:15]]
    values = [x["qty"] for x in items[:15]]
    colors = [RED if x["pct"]<30 else ORANGE if x["pct"]<70 else ACCENT for x in items[:15]]
    titles = {"auerbraeu":"🍺 Auerbräu","kaufland":"🛒 Kaufland","kagerer":"🥩 Kagerer",
              "asia_markt":"🌏 Asia Markt","feldbrach":"🥬 Feldbrach","all":"📦 Все"}
    fig, ax = setup_fig(12, max(6, len(names)*0.7+2))
    y = range(len(names))
    bars = ax.barh(list(y), values, color=colors, height=0.6, edgecolor="none")
    ax.set_yticks(list(y)); ax.set_yticklabels(names, color=TEXT, fontsize=10); ax.invert_yaxis()
    mx = max(values) if values else 1
    for bar, val, item in zip(bars, values, items[:15]):
        ax.text(bar.get_width()+mx*0.01, bar.get_y()+bar.get_height()/2,
                f"{val:.1f} {item['unit']}", va="center", color=TEXT, fontsize=10)
    ax.xaxis.set_visible(False)
    fig.text(0.02, 0.98, f"Склад: {titles.get(lieferant,lieferant)}", color=TEXT, fontsize=14, fontweight="bold", va="top")
    fig.text(0.02, 0.93, f"Позиций: {len(items)}", color=SUBTEXT, fontsize=10, va="top")
    plt.tight_layout(rect=[0,0,1,0.92])
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    buf.seek(0); plt.close()
    total_val = sum(x["qty"]*x["price"] for x in items)
    await msg.reply_photo(buf, caption=f"*{titles.get(lieferant,lieferant)}* — {len(items)} позиций\n💰 Стоимость: *{fmt(total_val)}*",
                         parse_mode="Markdown")


# ─── Каталог поставщиков ─────────────────────────────────────────
async def catalog_menu(update, ctx):
    msg = update.message or update.callback_query.message
    keyboard = [
        [InlineKeyboardButton("🥩 Kagerer (475 арт.)",   callback_data="cat_kagerer")],
        [InlineKeyboardButton("🥬 Feldbrach (191 арт.)", callback_data="cat_feldbrach")],
        [InlineKeyboardButton("🛒 Steiner (147 арт.)",   callback_data="cat_steiner")],
        [InlineKeyboardButton("🍺 Auerbräu (32 арт.)",   callback_data="cat_auerbraeu")],
        [InlineKeyboardButton("🔍 Поиск по всем",        callback_data="cat_search")],
        [InlineKeyboardButton("📄 Обновить цены (фото)", callback_data="cat_update_prices")],
    ]
    await msg.reply_text(
        "📋 *Каталог поставщиков*\n━━━━━━━━━━━━━━━━━━━━\n"
        "Выбери поставщика или поищи товар:",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def catalog_by_supplier(update, ctx, lieferant):
    msg = update.callback_query.message
    r = supabase.table("lieferant_catalog").select(
        "artikel_nr,artikel_name,kategorie,preis,einheit,gebinde"
    ).eq("lieferant_key", lieferant).order("kategorie").execute().data
    if not r: await msg.reply_text("Каталог пуст"); return

    from collections import defaultdict
    cats = defaultdict(list)
    for x in r:
        cats[x.get("kategorie") or "Прочее"].append(x)

    names = {"kagerer":"🥩 Kagerer","feldbrach":"🥬 Feldbrach",
             "steiner":"🛒 Steiner","auerbraeu":"🍺 Auerbräu"}
    text = f"📋 *{names.get(lieferant,lieferant)}* — {len(r)} позиций\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for cat, items in list(cats.items())[:8]:
        text += f"*{cat}*\n"
        for it in items[:5]:
            preis = f"{float(it['preis']):.2f}€" if it.get("preis") else "—"
            einheit = it.get("einheit") or it.get("gebinde") or ""
            text += f"  `{it.get('artikel_nr','—')}` {short(it['artikel_name'],35)} — *{preis}* {einheit}\n"
        if len(items)>5: text += f"  _...ещё {len(items)-5}_\n"
        text += "\n"
    if len(text)>4000: text = text[:3900]+"\n_...обрезано_"
    keyboard = [[InlineKeyboardButton("🔍 Найти товар", callback_data=f"catsearch_{lieferant}")]]
    await msg.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def catalog_search_start(update, ctx, lieferant=None):
    msg = update.callback_query.message if update.callback_query else update.message
    ctx.user_data["catalog_search"] = True
    ctx.user_data["catalog_lieferant"] = lieferant
    hint = f" у *{lieferant}*" if lieferant else " во всех каталогах"
    await msg.reply_text(f"🔍 Поиск{hint}\n\nНапиши название товара или артикул:", parse_mode="Markdown")

async def handle_catalog_search(update, ctx, query):
    lieferant = ctx.user_data.get("catalog_lieferant")
    ctx.user_data["catalog_search"] = False
    q = supabase.table("lieferant_catalog").select(
        "lieferant_key,artikel_nr,artikel_name,kategorie,preis,einheit,gebinde"
    )
    if lieferant: q = q.eq("lieferant_key", lieferant)
    r_name = q.ilike("artikel_name", f"%{query}%").limit(10).execute().data
    r_art  = supabase.table("lieferant_catalog").select(
        "lieferant_key,artikel_nr,artikel_name,kategorie,preis,einheit,gebinde"
    ).ilike("artikel_nr", f"%{query}%").limit(5).execute().data
    all_r = r_name + [x for x in r_art if x not in r_name]
    if not all_r:
        await update.message.reply_text(f"❌ *{query}* — ничего не найдено.", parse_mode="Markdown"); return
    lnames = {"kagerer":"🥩","feldbrach":"🥬","steiner":"🛒","auerbraeu":"🍺"}
    text = f"🔍 *{query}* ({len(all_r)} найдено)\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for it in all_r[:15]:
        preis = f"{float(it['preis']):.2f}€" if it.get("preis") else "—"
        einh  = it.get("einheit") or it.get("gebinde") or ""
        em    = lnames.get(it["lieferant_key"],"📦")
        text += f"{em} `{it.get('artikel_nr','—')}` *{short(it['artikel_name'],38)}*\n💰 {preis} {einh}\n\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def catalog_update_prices_start(update, ctx):
    msg = update.callback_query.message if update.callback_query else update.message
    ctx.user_data["updating_prices"] = True
    await msg.reply_text(
        "📄 *Обновление цен из каталога*\n\n"
        "Отправь фото страницы каталога с новыми ценами.\n"
        "Claude прочитает цены и обновит каталог.\n\n"
        "_Для отмены — /stop_", parse_mode="Markdown")

async def process_catalog_photo(update, ctx):
    await update.message.reply_text("🔍 Читаю новые цены...")
    photo      = await update.message.photo[-1].get_file()
    photo_bytes= await photo.download_as_bytearray()
    image_data = base64.b64encode(photo_bytes).decode("utf-8")
    response   = ai.messages.create(
        model="claude-sonnet-4-5", max_tokens=2000,
        messages=[{"role":"user","content":[
            {"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":image_data}},
            {"type":"text","text":"""Это страница каталога поставщика для ресторана.
Найди все товары с ценами. Верни ТОЛЬКО JSON без markdown:
{"lieferant":"название если видно","items":[{"artikel_nr":"артикул","artikel_name":"название","preis":0.00,"einheit":"единица"}]}
Цены как числа с точкой (12.50). Если артикул не виден — пустая строка."""}
        ]}]
    )
    import json
    try:
        data = json.loads(response.content[0].text)
        items = data.get("items", [])
        if not items: await update.message.reply_text("❌ Не нашёл товары с ценами на этом фото."); return
        text = f"✅ *Найдено {len(items)} позиций*"
        if data.get("lieferant"): text += f" ({data['lieferant']})"
        text += "\n━━━━━━━━━━━━━━━━━━━━\n\n"
        for it in items[:12]:
            text += f"`{it.get('artikel_nr','—')}` {short(it['artikel_name'],35)} → *{it['preis']:.2f}€*\n"
        if len(items)>12: text += f"_...ещё {len(items)-12}_\n"
        ctx.user_data["pending_catalog_update"] = items
        keyboard = [[
            InlineKeyboardButton("✅ Обновить цены в каталоге", callback_data="apply_catalog_prices"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel_catalog")
        ]]
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def apply_catalog_prices(q, ctx):
    items = ctx.user_data.get("pending_catalog_update", [])
    if not items: await q.message.reply_text("❌ Нет данных"); return
    updated, not_found = 0, 0
    for it in items:
        if not it.get("preis"): continue
        if it.get("artikel_nr"):
            r = supabase.table("lieferant_catalog").select("id").eq("artikel_nr", it["artikel_nr"]).execute().data
            if r:
                supabase.table("lieferant_catalog").update({
                    "preis": it["preis"], "updated_at": datetime.now().isoformat()
                }).eq("artikel_nr", it["artikel_nr"]).execute()
                updated += 1; continue
        r = supabase.table("lieferant_catalog").select("id").ilike(
            "artikel_name", f"%{it['artikel_name'][:20]}%"
        ).limit(1).execute().data
        if r:
            supabase.table("lieferant_catalog").update({
                "preis": it["preis"], "updated_at": datetime.now().isoformat()
            }).eq("id", r[0]["id"]).execute()
            updated += 1
        else:
            not_found += 1
    ctx.user_data.pop("pending_catalog_update", None)
    ctx.user_data["updating_prices"] = False
    await q.message.reply_text(
        f"✅ *Цены обновлены!*\n\n✅ Обновлено: {updated}\n❓ Не найдено: {not_found}",
        parse_mode="Markdown")

# ─── Аналитика ───────────────────────────────────────────────────
async def analytics(update, ctx):
    msg = update.message or update.callback_query.message
    keyboard = [
        [InlineKeyboardButton("💰 Топ 10 по выручке", callback_data="an_top_revenue"),
         InlineKeyboardButton("💹 Топ 10 по марже", callback_data="an_top_marge")],
        [InlineKeyboardButton("📈 Топ по количеству", callback_data="an_top_qty"),
         InlineKeyboardButton("💸 По поставщикам", callback_data="an_suppliers")],
        [InlineKeyboardButton("🔝 Дорогие блюда", callback_data="an_expensive"),
         InlineKeyboardButton("📉 Подорожавшие", callback_data="an_price_up")],
    ]
    await msg.reply_text("📉 *Аналитика:*", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def an_top_revenue(msg):
    from collections import defaultdict
    r = supabase.table("orderbird_sales").select("product_name,total_price").execute().data
    agg = defaultdict(float)
    for x in r: agg[x["product_name"]] += float(x.get("total_price") or 0)
    top = sorted(agg.items(), key=lambda x: x[1], reverse=True)[:10]
    if not top: await msg.reply_text("Нет данных"); return
    buf = bar_chart([short(x[0]) for x in top], [x[1] for x in top], "💰 Топ 10 по выручке", "€", ACCENT, "€")
    await msg.reply_photo(buf, caption="💰 *Топ 10 по выручке*", parse_mode="Markdown", reply_markup=back_kb())

async def an_top_marge(msg):
    r = supabase.table("recipes_hauptspeisen").select("dish_name,sell_price,cost_per_portion").execute().data
    items = [(x["dish_name"], round((1-float(x["cost_per_portion"])/float(x["sell_price"]))*100,1))
             for x in r if x["sell_price"] and x["cost_per_portion"] and float(x["sell_price"])>0]
    top = sorted(items, key=lambda x: x[1], reverse=True)[:10]
    buf = bar_chart([short(x[0]) for x in top], [x[1] for x in top], "💹 Топ 10 по марже", "%", GREEN, "%")
    await msg.reply_photo(buf, caption="💹 *Топ 10 по марже*", parse_mode="Markdown", reply_markup=back_kb())

async def an_top_qty(msg):
    from collections import defaultdict
    r = supabase.table("orderbird_sales").select("product_name,quantity").execute().data
    agg = defaultdict(int)
    for x in r: agg[x["product_name"]] += int(x.get("quantity") or 0)
    top = sorted(agg.items(), key=lambda x: x[1], reverse=True)[:10]
    if not top: await msg.reply_text("Нет данных"); return
    buf = bar_chart([short(x[0]) for x in top], [x[1] for x in top], "📈 Топ по количеству", "порций", BLUE, " пор.")
    await msg.reply_photo(buf, caption="📈 *Топ по количеству*", parse_mode="Markdown", reply_markup=back_kb())

async def an_suppliers(msg):
    from collections import defaultdict
    r = supabase.table("documents").select("lieferant_name,total_brutto,total_netto").execute().data
    agg = defaultdict(float)
    for x in r: agg[x["lieferant_name"]] += float(x.get("total_brutto") or x.get("total_netto") or 0)
    top = sorted(agg.items(), key=lambda x: x[1], reverse=True)[:8]
    buf = bar_chart([x[0] for x in top], [x[1] for x in top], "💰 Закупки по поставщикам", "€", BLUE, "€")
    await msg.reply_photo(buf, caption="💰 *Закупки по поставщикам*", parse_mode="Markdown", reply_markup=back_kb())

async def an_expensive(msg):
    r = supabase.table("recipes_hauptspeisen").select("dish_name,sell_price").order("sell_price", desc=True).limit(10).execute().data
    buf = bar_chart([short(x["dish_name"]) for x in r], [float(x["sell_price"]) for x in r],
                    "💸 Дорогие блюда", "€", ORANGE, "€")
    await msg.reply_photo(buf, caption="💸 *Самые дорогие блюда*", parse_mode="Markdown", reply_markup=back_kb())

async def an_price_up(msg):
    r = supabase.table("price_history").select("product_id,change_pct,old_price,new_price").gt("change_pct",0).order("change_pct",desc=True).limit(10).execute().data
    p = {x["id"]: x["product_name"] for x in supabase.table("products").select("id,product_name").execute().data}
    if not r: await msg.reply_text("📉 Подорожавших пока нет."); return
    buf = bar_chart([short(p.get(x["product_id"],"?")) for x in r], [float(x["change_pct"]) for x in r],
                    "📉 Подорожавшие ингредиенты", "%", RED, "%")
    await msg.reply_photo(buf, caption="📉 *Подорожавшие ингредиенты*", parse_mode="Markdown", reply_markup=back_kb())

# ─── Закупки ─────────────────────────────────────────────────────
async def purchases(update, ctx):
    msg = update.message or update.callback_query.message
    r = supabase.table("documents").select("lieferant_name,doc_date,total_brutto,total_netto,bon_nr").order("doc_date",desc=True).limit(10).execute().data
    text = "📦 *Последние закупки*\n━━━━━━━━━━━━━━━━━━━━\n"
    for x in r:
        summe = x.get("total_brutto") or x.get("total_netto") or 0
        text += f"📅 *{x['doc_date']}* — {x['lieferant_name']}\n   {fmt(summe)} | #{x.get('bon_nr','—')}\n"
    month_ago = (datetime.now()-timedelta(days=30)).strftime("%Y-%m-%d")
    r2 = supabase.table("documents").select("total_brutto,total_netto").gte("doc_date",month_ago).execute().data
    month_sum = sum(float(x.get("total_brutto") or x.get("total_netto") or 0) for x in r2)
    text += f"\n💰 *За 30 дней: {fmt(month_sum)}*"
    await msg.reply_text(text, parse_mode="Markdown", reply_markup=back_kb())

# ─── Сканирование чека + обновление склада ───────────────────────
async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_manager(uid): return
    # Режим обновления цен каталога
    if ctx.user_data.get("updating_prices"):
        await process_catalog_photo(update, ctx)
        return
    await update.message.reply_text("🔍 Сканирую чек...")
    photo      = await update.message.photo[-1].get_file()
    photo_bytes= await photo.download_as_bytearray()
    image_data = base64.b64encode(photo_bytes).decode("utf-8")
    response   = ai.messages.create(
        model="claude-sonnet-4-5", max_tokens=2000,
        messages=[{"role":"user","content":[
            {"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":image_data}},
            {"type":"text","text":"""Анализируй чек немецкого поставщика для ресторана Asia Dragon.
Поставщики: kaufland, lidl, oezpack, kagerer, steiner, asia_markt, ho_asia_markt, ngoc_lan, auerbraeu, feldbrach, edeka_cc
Верни ТОЛЬКО JSON без markdown:
{"lieferant_key":"...","lieferant_name":"...","bon_nr":"...","doc_date":"YYYY-MM-DD","total_brutto":0.00,
"items":[{"raw_text":"...","quantity":0.0,"unit":"kg/st/fl/pk/l","unit_price":0.00,"total_price":0.00,"tax_class":"A"}]}
Цены с точкой (1.29), дата YYYY-MM-DD"""}
        ]}]
    )
    import json
    try:
        data = json.loads(response.content[0].text)
        text = (f"✅ *Чек распознан!*\n🏪 {data['lieferant_name']}\n"
                f"📅 {data['doc_date']} | 🧾 #{data.get('bon_nr','—')}\n"
                f"💰 {fmt(data.get('total_brutto',0))}\n📋 Позиций: {len(data['items'])}\n\n")
        for item in data["items"][:8]:
            text += f"• {short(item['raw_text'],30)} — {item['quantity']} {item['unit']} × {fmt(item['unit_price'])}\n"
        if len(data["items"])>8: text += f"_...ещё {len(data['items'])-8}_\n"
        keyboard = [[InlineKeyboardButton("✅ Сохранить и обновить склад", callback_data="save_receipt"),
                     InlineKeyboardButton("❌ Отмена", callback_data="cancel")]]
        ctx.user_data["pending_receipt"] = data
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка распознавания: {e}")

async def save_receipt_and_update_stock(q, receipt):
    """Сохраняет чек и обновляет склад"""
    # 1. Сохраняем документ
    doc = supabase.table("documents").insert({
        "lieferant_key": receipt["lieferant_key"],
        "lieferant_name": receipt["lieferant_name"],
        "doc_type": "Kassenbon",
        "doc_date": receipt["doc_date"],
        "bon_nr": receipt.get("bon_nr"),
        "total_brutto": receipt.get("total_brutto"),
    }).execute()
    doc_id = doc.data[0]["id"]

    # 2. Сохраняем позиции
    for item in receipt["items"]:
        supabase.table("document_items").insert({
            "document_id": doc_id,
            "lieferant_key": receipt["lieferant_key"],
            "raw_text": item["raw_text"],
            "quantity": item["quantity"],
            "unit": item["unit"],
            "unit_price": item["unit_price"],
            "total_price": item["total_price"],
            "tax_class": item.get("tax_class"),
        }).execute()

    # 3. Обновляем склад через ingredient_mapping
    updated, not_found = [], []
    for item in receipt["items"]:
        if not item["quantity"] or float(item["quantity"]) <= 0:
            continue

        # Ищем product_id через маппинг
        r = supabase.table("ingredient_mapping").select("product_id") \
            .eq("lieferant_key", receipt["lieferant_key"]) \
            .ilike("raw_text", item["raw_text"]) \
            .eq("is_confirmed", True).execute().data

        # Если не нашли точно — нечёткий поиск
        if not r:
            all_mappings = supabase.table("ingredient_mapping").select("product_id,raw_text") \
                .eq("lieferant_key", receipt["lieferant_key"]) \
                .eq("is_confirmed", True).execute().data
            for m in all_mappings:
                if m["raw_text"].lower() in item["raw_text"].lower() or \
                   item["raw_text"].lower() in m["raw_text"].lower():
                    r = [m]; break

        if r:
            pid = r[0]["product_id"]
            qty = float(item["quantity"])

            # stock_movements — запись движения
            supabase.table("stock_movements").insert({
                "product_id":    pid,
                "movement_type": "purchase",
                "quantity":      qty,
                "unit":          item["unit"],
                "unit_price":    item["unit_price"],
                "total_price":   item["total_price"],
                "document_type": "documents",
                "document_id":   doc_id,
                "movement_date": datetime.now().isoformat(),
                "notes":         item["raw_text"],
            }).execute()

            # stock — обновляем количество
            existing = supabase.table("stock").select("quantity").eq("product_id", pid).execute().data
            if existing:
                new_qty = float(existing[0]["quantity"] or 0) + qty
                supabase.table("stock").update({
                    "quantity": new_qty,
                    "last_purchase_price": item["unit_price"],
                    "last_purchase_date": receipt["doc_date"],
                    "updated_at": datetime.now().isoformat(),
                }).eq("product_id", pid).execute()
            else:
                supabase.table("stock").insert({
                    "product_id": pid, "quantity": qty, "unit": item["unit"],
                    "last_purchase_price": item["unit_price"],
                    "last_purchase_date": receipt["doc_date"],
                }).execute()

            # products — обновляем последнюю цену
            if item["unit_price"]:
                supabase.table("products").update({
                    "last_price": item["unit_price"],
                    "last_price_date": receipt["doc_date"],
                    "last_lieferant": receipt["lieferant_key"],
                }).eq("id", pid).execute()

            prod = supabase.table("products").select("product_name").eq("id", pid).execute().data
            name = prod[0]["product_name"] if prod else "?"
            updated.append(f"✅ {name}: +{qty} {item['unit']}")
        else:
            not_found.append(f"❓ {short(item['raw_text'],25)}")

    # 4. Формируем ответ
    result = f"✅ *Чек сохранён!* ID: {doc_id}\n\n"
    result += f"📦 *Склад обновлён ({len(updated)} позиций):*\n"
    result += "\n".join(updated[:10])
    if not_found:
        result += f"\n\n⚠️ *Не найдено в маппинге ({len(not_found)}):*\n"
        result += "\n".join(not_found[:5])
        result += "\n_Добавь маппинг чтобы эти позиции тоже обновляли склад_"

    await q.message.reply_text(result, parse_mode="Markdown")

# ─── Заказы сотрудников (через order_requests) ───────────────────
async def staff_orders_view(update, ctx):
    msg = update.message or update.callback_query.message
    r = supabase.table("order_requests").select("*").eq("status","pending").order("created_at",desc=True).execute().data
    if not r: await msg.reply_text("✅ Нет новых заказов от сотрудников", reply_markup=back_kb()); return

    text = f"🔔 *Заказы сотрудников* ({len(r)} новых)\n━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = []
    for order in r:
        items = supabase.table("order_request_items").select("product_name,quantity,unit,notes") \
            .eq("order_request_id", order["id"]).execute().data
        staff_name = order.get("staff_name") or order.get("requested_by","?")
        text += f"\n👤 *{staff_name}* | {str(order['created_at'])[:10]}\n"
        for it in items:
            text += f"  • {it.get('product_name','?')} — {it['quantity']} {it['unit'] or 'шт'}\n"
        if order.get("notes"): text += f"  📝 _{order['notes']}_\n"
        keyboard.append([
            InlineKeyboardButton(f"✅ Одобрить #{order['id']}", callback_data=f"approve_order_{order['id']}"),
            InlineKeyboardButton(f"❌ Отклонить", callback_data=f"reject_order_{order['id']}")
        ])
    await msg.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

# ─── Панель сотрудника ───────────────────────────────────────────
async def worker_order_start(update, ctx):
    msg = update.message or update.callback_query.message
    uid = update.effective_user.id
    if not is_worker(uid): return

    # Подсказка что заканчивается
    r = supabase.table("stock").select("product_id,quantity,min_quantity,unit").execute().data
    p = {x["id"]: x for x in supabase.table("products").select("id,product_name").execute().data}
    low = []
    for x in r:
        if x["min_quantity"] and float(x["quantity"] or 0) < float(x["min_quantity"] or 0):
            prod = p.get(x["product_id"],{})
            pct  = float(x["quantity"] or 0)/float(x["min_quantity"])*100
            emoji = "🔴" if pct<30 else "🟡"
            low.append(f"{emoji} {prod.get('product_name','?')}")

    text = "🛒 *Новый заказ*\n\n"
    if low:
        text += f"💡 *На складе заканчивается:*\n" + "\n".join(low[:8])
        if len(low)>8: text += f"\n_...ещё {len(low)-8}_"
        text += "\n\n"

    text += ("Напиши что нужно заказать — пиши свободно на любом языке:\n\n"
             "🇷🇺 _Лосось 10кг, авокадо 2кг_\n"
             "🇩🇪 _Lachs 10kg, Avocado 2kg_\n"
             "🇻🇳 _Cá hồi 10kg, bơ 2kg_\n\n"
             "Можно писать всё в одном сообщении или по одному.\n"
             "Когда всё написал — напиши *готово* или *fertig*")

    ctx.user_data["worker_ordering"] = True
    ctx.user_data["worker_messages"] = []
    await msg.reply_text(text, parse_mode="Markdown")

async def worker_my_orders(update, ctx):
    msg = update.message or update.callback_query.message
    uid = update.effective_user.id
    r = supabase.table("order_requests").select("*").eq("telegram_id", uid).order("created_at", desc=True).limit(10).execute().data
    if not r: await msg.reply_text(t(uid, "no_orders")); return
    text = t(uid, "my_orders") + "\n\n"
    status_emoji = {"pending":"⏳","approved":"✅","ordered":"📦","received":"🎉","cancelled":"❌"}
    for o in r:
        emoji = status_emoji.get(o["status"],"❓")
        text += f"{emoji} *{str(o['created_at'])[:10]}* — {o['status']}\n"
    await msg.reply_text(text, parse_mode="Markdown")

async def handle_worker_order_text(update, ctx, text):
    uid      = update.effective_user.id
    st       = get_staff(uid)
    messages = ctx.user_data.get("worker_messages", [])

    if is_done_word(uid, text):
        if not messages:
            await update.message.reply_text(t(uid, "empty")); return

        await update.message.reply_text("🔄 ...")

        full_text = "\n".join(messages)
        response = ai.messages.create(
            model="claude-sonnet-4-5", max_tokens=1000,
            messages=[{"role":"user","content":f"""Parse this restaurant order list. Text can be in any language (Russian, German, Vietnamese, mixed).

ORDER TEXT:
{full_text}

Return ONLY a JSON array, no markdown:
[{{"name": "product name in Russian", "qty": number, "unit": "кг/шт/л/уп/г/мл"}}]

Rules:
- name always in Russian
- qty as number
- unit: кг, шт, л, уп, г, мл
- If unit not specified use "шт"
- If qty not specified use 1"""}]
        )

        import json, re
        try:
            raw = response.content[0].text.strip()
            match = re.search(r'\[.*\]', raw, re.DOTALL)
            items = json.loads(match.group() if match else raw)
        except:
            items = []

        if not items:
            await update.message.reply_text("❌ Не смог разобрать список. Попробуй ещё раз."); return

        order = supabase.table("order_requests").insert({
            "requested_by": st["name"],
            "staff_name":   st["name"],
            "telegram_id":  uid,
            "status":       "pending",
            "order_date":   datetime.now().strftime("%Y-%m-%d"),
            "notes":        f"Заказ через Telegram. Язык: {st.get('language','ru')}. Оригинал: {full_text[:150]}",
        }).execute().data[0]

        for it in items:
            supabase.table("order_request_items").insert({
                "order_request_id": order["id"],
                "product_name":     it["name"],
                "quantity":         it["qty"],
                "unit":             it["unit"],
            }).execute()

        ctx.user_data["worker_ordering"] = False
        ctx.user_data["worker_messages"] = []

        item_text = "\n".join([f"  • {it['name']} — {it['qty']} {it['unit']}" for it in items])
        notify = (
            f"🔔 *Новый заказ продуктов*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 *{st['name']}*\n"
            f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n"
            f"📋 Заказ *#{order['id']}*\n\n"
            f"*Список:*\n{item_text}"
        )
        for manager_id in MANAGER_IDS:
            try:
                await ctx.bot.send_message(manager_id, notify, parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_order_{order['id']}"),
                        InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_order_{order['id']}")
                    ]]))
            except: pass

        await update.message.reply_text(
            t(uid, "sent", id=order["id"], items=item_text),
            parse_mode="Markdown")
        return

    # Накапливаем сообщения
    messages.append(text)
    ctx.user_data["worker_messages"] = messages
    await update.message.reply_text(
        t(uid, "recorded") + f" ({len(messages)})",
        parse_mode="Markdown")

# ─── Управление сотрудниками ─────────────────────────────────────
async def manage_staff(update, ctx):
    msg = update.message or update.callback_query.message
    if not is_manager(update.effective_user.id): return
    r = supabase.table("staff").select("*").eq("is_active",True).execute().data
    text = "👥 *Сотрудники*\n━━━━━━━━━━━━━━━━━━━━\n"
    for s in r:
        text += f"• *{s['name']}* (ID: `{s['telegram_id']}`)\n"
    text += "\n*Добавить:* `/addstaff [telegram_id] [имя]`\n*Удалить:* `/removestaff [telegram_id]`"
    await msg.reply_text(text, parse_mode="Markdown", reply_markup=back_kb())

async def add_staff(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_manager(update.effective_user.id): return
    args = ctx.args
    if len(args)<2: await update.message.reply_text("Использование: `/addstaff [telegram_id] [имя]`", parse_mode="Markdown"); return
    try:
        tg_id = int(args[0]); name = " ".join(args[1:])
        supabase.table("staff").upsert({"telegram_id":tg_id,"name":name,"role":"worker","is_active":True}).execute()
        await update.message.reply_text(f"✅ Сотрудник *{name}* добавлен!\n\nПусть напишет боту /start", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ─── AI ──────────────────────────────────────────────────────────
def load_full_context():
    from collections import defaultdict
    stock_r  = supabase.table("stock").select("product_id,quantity,unit,min_quantity,last_purchase_price").execute().data
    prods_r  = supabase.table("products").select("id,product_name,last_lieferant,unit").execute().data
    sales_r  = supabase.table("orderbird_sales").select("product_name,quantity,total_price,plu").execute().data
    docs_r   = supabase.table("documents").select("lieferant_name,doc_date,total_brutto,total_netto").order("doc_date",desc=True).limit(30).execute().data
    haupt_r  = supabase.table("recipes_hauptspeisen").select("dish_number,dish_name,sell_price,cost_per_portion").execute().data
    sushi_r  = supabase.table("recipes_sushi").select("dish_number,dish_name,sell_price,cost_per_portion").execute().data
    vor_r    = supabase.table("recipes_vorspeisen").select("dish_number,dish_name,sell_price,cost_per_portion").execute().data
    mittag_r = supabase.table("recipes_mittag_hauptspeisen").select("dish_number,dish_name,sell_price,cost_per_portion").execute().data
    price_r  = supabase.table("price_history").select("product_id,old_price,new_price,change_pct,price_date,lieferant_key").order("created_at",desc=True).limit(20).execute().data
    prods = {x["id"]: x for x in prods_r}
    stock_info, knapp_list, lagerwert = [], [], 0
    for x in stock_r:
        p = prods.get(x["product_id"],{}); qty=float(x["quantity"] or 0); mn=float(x["min_quantity"] or 0); prc=float(x["last_purchase_price"] or 0)
        lagerwert += qty*prc
        stock_info.append({"id":x["product_id"],"name":p.get("product_name"),"qty":qty,"unit":x["unit"],"min":mn,"price":prc,"lieferant":p.get("last_lieferant")})
        if mn>0 and qty<mn:
            knapp_list.append({"name":p.get("product_name"),"qty":qty,"min":mn,"unit":x["unit"],"lieferant":p.get("last_lieferant"),"pct":round(qty/mn*100,1)})
    knapp_list.sort(key=lambda x: x["pct"])
    sales_agg = defaultdict(lambda:{"qty":0,"revenue":0})
    for x in sales_r:
        sales_agg[x["product_name"]]["qty"]     += int(x.get("quantity") or 0)
        sales_agg[x["product_name"]]["revenue"] += float(x.get("total_price") or 0)
    supplier_agg = defaultdict(float)
    for x in docs_r: supplier_agg[x["lieferant_name"]] += float(x.get("total_brutto") or x.get("total_netto") or 0)
    all_recipes = haupt_r + sushi_r + vor_r + mittag_r
    recipes_with_marge = []
    for r in all_recipes:
        sp=float(r.get("sell_price") or 0); cp=float(r.get("cost_per_portion") or 0)
        marge=round((1-cp/sp)*100,1) if sp>0 and cp>0 else None
        recipes_with_marge.append({**r,"marge_pct":marge,"profit":round(sp-cp,2) if sp>0 and cp>0 else 0})
    price_with_names = [{**x,"product_name":prods.get(x["product_id"],{}).get("product_name","?")} for x in price_r]
    return {"stock":stock_info,"lagerwert":round(lagerwert,2),"knapp":knapp_list,
            "recipes":recipes_with_marge,"sales":dict(sorted(sales_agg.items(),key=lambda x:x[1]["qty"],reverse=True)[:60]),
            "docs":docs_r,"suppliers":dict(sorted(supplier_agg.items(),key=lambda x:x[1],reverse=True)),
            "price_changes":price_with_names}

async def ask_ai_menu(update, ctx):
    msg = update.message or update.callback_query.message
    ctx.user_data["ai_mode"] = True
    keyboard = [
        [InlineKeyboardButton("🏥 Полный анализ системы",   callback_data="ai_full_analysis")],
        [InlineKeyboardButton("💰 Анализ прибыльности",     callback_data="ai_profit_analysis")],
        [InlineKeyboardButton("⚠️ Анализ рисков склада",    callback_data="ai_risk_analysis")],
        [InlineKeyboardButton("📊 Рекомендации по меню",    callback_data="ai_menu_advice")],
    ]
    await msg.reply_text(
        "🤖 *AI Ассистент Asia Dragon*\n\n"
        "📊 *По базе:* себестоимость блюда 271, сколько Lachs, что заказать у Kagerer...\n"
        "🌍 *Любые вопросы:* foodcost, HACCP, переводы, общение 😊\n\n"
        "Выбери анализ или просто пиши вопрос:\n",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def ai_full_analysis(msg):
    await msg.reply_text("🔄 Полный анализ... (~15 сек)")
    d = load_full_context()
    top_marge = sorted([r for r in d["recipes"] if r.get("marge_pct")],key=lambda x:x["marge_pct"],reverse=True)[:5]
    low_marge = sorted([r for r in d["recipes"] if r.get("marge_pct") and r["marge_pct"]<40],key=lambda x:x["marge_pct"])[:5]
    top_sales = sorted(d["sales"].items(),key=lambda x:x[1]["revenue"],reverse=True)[:5]
    prompt = f"""Ты эксперт-консультант по ресторанному бизнесу. Сделай ПОЛНЫЙ анализ ресторана Asia Dragon (Bad Aibling, Германия).

ДАННЫЕ: Склад={d["lagerwert"]}€ | Ниже минимума={len(d["knapp"])} | Рецептов={len(d["recipes"])}
Поставщики: {d["suppliers"]}
Топ маржа: {[(r["dish_name"],r["marge_pct"]) for r in top_marge]}
Низкая маржа: {[(r["dish_name"],r["marge_pct"]) for r in low_marge]}
Топ продажи: {[(k,v["revenue"]) for k,v in top_sales]}
Проблемы склада: {d["knapp"][:8]}

Напиши анализ по разделам (по-русски, с цифрами):
1. 💰 ФИНАНСЫ
2. 🍽 МЕНЮ
3. ⚠️ РИСКИ
4. 📈 ВОЗМОЖНОСТИ
5. ✅ ТОП-3 ДЕЙСТВИЯ прямо сейчас"""
    response = ai.messages.create(model="claude-sonnet-4-5",max_tokens=2000,messages=[{"role":"user","content":prompt}])
    text = response.content[0].text
    for i in range(0,len(text),4000): await msg.reply_text(text[i:i+4000],parse_mode="Markdown")

async def ai_profit_analysis(msg):
    await msg.reply_text("🔄 Анализирую прибыльность...")
    d = load_full_context()
    combined = []
    for r in d["recipes"]:
        sd = d["sales"].get(r["dish_name"],{"qty":0,"revenue":0})
        if r.get("marge_pct") and sd["qty"]>0:
            combined.append({"name":r["dish_name"],"marge":r["marge_pct"],"sold":sd["qty"],"revenue":sd["revenue"],"profit_total":round(r["profit"]*sd["qty"],2)})
    combined.sort(key=lambda x:x["profit_total"],reverse=True)
    prompt = f"""Анализ прибыльности Asia Dragon.
Топ-15 по прибыли (маржа × продажи): {combined[:15]}
Все рецепты с маржой: {[(r["dish_name"],r.get("marge_pct"),r.get("sell_price")) for r in d["recipes"] if r.get("marge_pct")]}
Анализ по-русски: что приносит прибыль, что продвигать, рекомендации по ценам."""
    response = ai.messages.create(model="claude-sonnet-4-5",max_tokens=1500,messages=[{"role":"user","content":prompt}])
    await msg.reply_text(response.content[0].text,parse_mode="Markdown")

async def ai_risk_analysis(msg):
    await msg.reply_text("🔄 Анализирую риски...")
    d = load_full_context()
    prompt = f"""Анализ рисков склада Asia Dragon.
Ниже минимума: {d["knapp"]}
Склад: {d["lagerwert"]}€ | Изменения цен: {d["price_changes"]}
Поставщики: {d["suppliers"]}
Дай по-русски: что купить СРОЧНО, что на этой неделе, список заказа на завтра."""
    response = ai.messages.create(model="claude-sonnet-4-5",max_tokens=1500,messages=[{"role":"user","content":prompt}])
    await msg.reply_text(response.content[0].text,parse_mode="Markdown")

async def ai_menu_advice(msg):
    await msg.reply_text("🔄 Анализирую меню...")
    d = load_full_context()
    sold_names = {k for k,v in d["sales"].items() if v["qty"]>0}
    not_sold = [r["dish_name"] for r in d["recipes"] if r["dish_name"] not in sold_names]
    prompt = f"""Анализ меню Asia Dragon.
Продажи: {list(d["sales"].items())[:40]}
Не продавались: {not_sold[:20]}
Все блюда с маржой: {[(r["dish_name"],r.get("marge_pct"),r.get("sell_price")) for r in d["recipes"] if r.get("marge_pct")]}
По-русски: что убрать, что продвигать, как поднять средний чек."""
    response = ai.messages.create(model="claude-sonnet-4-5",max_tokens=1500,messages=[{"role":"user","content":prompt}])
    await msg.reply_text(response.content[0].text,parse_mode="Markdown")

async def handle_ai_question(update, ctx, question):
    await update.message.reply_text("🤔 Думаю...")
    d = load_full_context()
    prompt = f"""Ты AI ассистент ресторана Asia Dragon (Bad Aibling, Германия). Дружелюбный и умный.

СКЛАД: {d["stock"]}
РЕЦЕПТЫ (с маржой): {d["recipes"]}
ПРОДАЖИ: {d["sales"]}
ЗАКУПКИ: {d["docs"][:15]}
ИЗМЕНЕНИЯ ЦЕН: {d["price_changes"]}

ВОПРОС: {question}

ПРАВИЛА:
- Вопрос о блюде → полная инфо (цена, себестоимость, маржа, продажи за месяц)
- Вопрос о продукте → инфо из склада (кол-во, цена, поставщик, минимум)
- Вопрос о ресторане → используй все данные
- НЕ связан с рестораном → отвечай как обычный AI, дружелюбно
- Всегда по-русски, с цифрами, с эмодзи"""
    response = ai.messages.create(model="claude-sonnet-4-5",max_tokens=1500,messages=[{"role":"user","content":prompt}])
    text = response.content[0].text
    for i in range(0,len(text),4000): await update.message.reply_text(text[i:i+4000],parse_mode="Markdown")

# ─── Текст и документы ───────────────────────────────────────────
async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text
    if ctx.user_data.get("worker_ordering") and is_worker(uid):
        await handle_worker_order_text(update, ctx, text); return
    if ctx.user_data.get("catalog_search") and is_manager(uid):
        await handle_catalog_search(update, ctx, text); return
    if ctx.user_data.get("ai_mode") and is_manager(uid):
        await handle_ai_question(update, ctx, text); return

async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_manager(uid): return
    doc = update.message.document; fname = doc.file_name or ""
    if fname.endswith(".csv") and "report" in fname.lower():
        await update.message.reply_text("📊 Получил Orderbird CSV — обрабатываю...")
        file = await doc.get_file(); data = await file.download_as_bytearray()
        await process_orderbird_csv(update, ctx, data.decode("utf-8-sig"), fname)
    else:
        await update.message.reply_text("📄 Отправь фото чека или CSV из Orderbird.")

async def process_orderbird_csv(update, ctx, text, fname):
    lines = text.split("\n")
    date_from, date_to = "2026-01-01","2026-12-31"
    for line in lines[:5]:
        if "Datum:" in line:
            parts = line.split(";")
            try:
                date_from = datetime.strptime(parts[1].strip(),"%d.%m.%Y").strftime("%Y-%m-%d")
                date_to   = datetime.strptime(parts[2].strip(),"%d.%m.%Y").strftime("%Y-%m-%d")
            except: pass
    total_brutto = 0.0
    for line in lines[:30]:
        parts = line.split(";")
        if parts[0]=="Total" and len(parts)>=4:
            try: total_brutto = float(parts[3].replace(",",".")); break
            except: pass
    start_idx = next((i+1 for i,l in enumerate(lines) if l.startswith("Produkte;")), None)
    if not start_idx: await update.message.reply_text("❌ Секция Produkte не найдена"); return
    sales = []
    for line in lines[start_idx:]:
        if not line.strip(): break
        parts = line.split(";")
        if len(parts)>=4 and parts[1] and parts[2]:
            name,plu = parts[0].strip(),parts[1].strip().rstrip(".")
            try:
                qty,total = int(parts[2]),float(parts[3].replace(",","."))
                if "KUNDENKARTE" in name or "Wertgutschein" in name: continue
                sales.append({"name":name,"plu":plu if plu!="0" else None,"qty":qty,"total":total,"unit_price":round(total/qty,4) if qty else 0})
            except: pass
    report = supabase.table("orderbird_reports").insert({
        "report_type":"day" if date_from==date_to else "month",
        "date_from":date_from,"date_to":date_to,"total_brutto":total_brutto,
        "total_portions":sum(s["qty"] for s in sales),"file_name":fname,"processed":False
    }).execute().data[0]
    rid = report["id"]
    for i in range(0,len(sales),50):
        supabase.table("orderbird_sales").insert([
            {"report_id":rid,"plu":s["plu"],"product_name":s["name"],"quantity":s["qty"],"total_price":s["total"],"unit_price":s["unit_price"],"matched":False}
            for s in sales[i:i+50]
        ]).execute()
    matched = auto_match(rid)
    supabase.table("orderbird_reports").update({"processed":True}).eq("id",rid).execute()
    await update.message.reply_text(
        f"✅ *CSV загружен!*\n📅 {date_from} → {date_to}\n💰 {fmt(total_brutto)}\n🍽 Позиций: {len(sales)}\n🔗 Сопоставлено: {matched}/{len(sales)}",
        parse_mode="Markdown")

def auto_match(report_id):
    recipe_map = {}
    for tbl,col in [("recipes_hauptspeisen","dish_number"),("recipes_vorspeisen","dish_number"),
                     ("recipes_sushi","dish_number"),("recipes_sushi_sets","dish_number"),
                     ("recipes_beilagen","dish_number"),("recipes_nachspeisen","dish_number"),
                     ("recipes_mittag_hauptspeisen","dish_number")]:
        for r in supabase.table(tbl).select(f"id,{col}").execute().data or []:
            if r.get(col): recipe_map[r[col]] = {"table":tbl,"id":r["id"]}
    for r in supabase.table("sushi_mittag").select("id,dish_code").execute().data or []:
        if r.get("dish_code"): recipe_map[r["dish_code"]] = {"table":"sushi_mittag","id":r["id"]}
    drink_map = {r["orderbird_name"]:r["recipe_drink_id"] for r in supabase.table("orderbird_drink_mapping").select("*").execute().data or [] if r.get("recipe_drink_id")}
    sales = supabase.table("orderbird_sales").select("id,plu,product_name").eq("report_id",report_id).eq("matched",False).execute().data or []
    count = 0
    for s in sales:
        if s["plu"] and s["plu"] in recipe_map:
            rec = recipe_map[s["plu"]]
            supabase.table("orderbird_sales").update({"recipe_table":rec["table"],"recipe_id":rec["id"],"matched":True}).eq("id",s["id"]).execute()
            count += 1
        elif not s["plu"] and s["product_name"] in drink_map:
            supabase.table("orderbird_sales").update({"recipe_table":"recipes_getraenke","recipe_id":drink_map[s["product_name"]],"matched":True}).eq("id",s["id"]).execute()
            count += 1
    return count

async def stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["ai_mode"] = False
    ctx.user_data["worker_ordering"] = False
    ctx.user_data["catalog_search"] = False
    ctx.user_data["updating_prices"] = False
    await update.message.reply_text("✅ /start для меню.")

# ─── Callback обработчик ─────────────────────────────────────────
async def button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer(); d = q.data
    if   d == "dashboard":          await send_quick_dashboard(q.message)
    elif d == "stock_low":          await stock_low(update, ctx)
    elif d == "purchases":          await purchases(update, ctx)
    elif d == "price_changes":      await price_changes(update, ctx)
    elif d == "stock_groups":       await stock_groups(update, ctx)
    elif d == "analytics":          await analytics(update, ctx)
    elif d == "ask_ai":             await ask_ai_menu(update, ctx)
    elif d == "staff_orders":       await staff_orders_view(update, ctx)
    elif d == "manage_staff":       await manage_staff(update, ctx)
    elif d == "worker_order":       await worker_order_start(update, ctx)
    elif d == "worker_my_orders":   await worker_my_orders(update, ctx)
    elif d == "upload_receipt":     await q.message.reply_text("📷 Отправь фото чека")
    elif d == "cancel":             await q.message.reply_text("❌ Отменено")
    elif d.startswith("setlang_"):
        lang = d.split("_")[1]
        uid2 = update.effective_user.id
        supabase.table("staff").update({"language": lang}).eq("telegram_id", uid2).execute()
        st2 = get_staff(uid2)
        names = {"ru":"🇷🇺 Русский","de":"🇩🇪 Deutsch","vi":"🇻🇳 Tiếng Việt"}
        keyboard2 = [
            [InlineKeyboardButton(t(uid2,"btn_order"), callback_data="worker_order")],
            [InlineKeyboardButton(t(uid2,"btn_myorders"), callback_data="worker_my_orders")],
        ]
        await q.message.reply_text(
            f"✅ {names[lang]}\n\n" + t(uid2, "welcome", name=st2["name"]),
            parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard2))
    elif d == "catalog":              await catalog_menu(update, ctx)
    elif d == "cat_search":           await catalog_search_start(update, ctx)
    elif d == "cat_update_prices":    await catalog_update_prices_start(update, ctx)
    elif d == "apply_catalog_prices": await apply_catalog_prices(q, ctx)
    elif d == "cancel_catalog":
        ctx.user_data["updating_prices"] = False
        await q.message.reply_text("❌ Отменено")
    elif d.startswith("catsearch_"):
        await catalog_search_start(update, ctx, d[10:])
    elif d.startswith("cat_") and len(d)>4:
        await catalog_by_supplier(update, ctx, d[4:])
    elif d == "ai_full_analysis":   await ai_full_analysis(q.message)
    elif d == "ai_profit_analysis": await ai_profit_analysis(q.message)
    elif d == "ai_risk_analysis":   await ai_risk_analysis(q.message)
    elif d == "ai_menu_advice":     await ai_menu_advice(q.message)
    elif d.startswith("sg_"):       await stock_by_supplier(update, ctx, d[3:])
    elif d.startswith("an_"):
        msg = q.message
        if   d == "an_top_revenue": await an_top_revenue(msg)
        elif d == "an_top_marge":   await an_top_marge(msg)
        elif d == "an_top_qty":     await an_top_qty(msg)
        elif d == "an_suppliers":   await an_suppliers(msg)
        elif d == "an_expensive":   await an_expensive(msg)
        elif d == "an_price_up":    await an_price_up(msg)
    elif d.startswith("approve_order_"):
        order_id = int(d.split("_")[-1])
        supabase.table("order_requests").update({"status":"approved","confirmed_by":"manager","confirmed_at":datetime.now().isoformat()}).eq("id",order_id).execute()
        order = supabase.table("order_requests").select("*").eq("id",order_id).execute().data[0]
        try: await ctx.bot.send_message(order["telegram_id"],"✅ Твой заказ одобрен! Продукты будут заказаны.")
        except: pass
        await q.message.reply_text(f"✅ Заказ #{order_id} одобрен!")
    elif d.startswith("reject_order_"):
        order_id = int(d.split("_")[-1])
        supabase.table("order_requests").update({"status":"cancelled"}).eq("id",order_id).execute()
        order = supabase.table("order_requests").select("*").eq("id",order_id).execute().data[0]
        try: await ctx.bot.send_message(order["telegram_id"],"❌ Твой заказ отклонён.")
        except: pass
        await q.message.reply_text(f"❌ Заказ #{order_id} отклонён")
    elif d == "save_receipt":
        receipt = ctx.user_data.get("pending_receipt")
        if receipt:
            try:
                await save_receipt_and_update_stock(q, receipt)
                ctx.user_data.pop("pending_receipt", None)
            except Exception as e:
                await q.message.reply_text(f"❌ Ошибка: {e}")

# ─── Запуск ──────────────────────────────────────────────────────
def start_health_server():
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
        def log_message(self,*a): pass
    port = int(os.environ.get("PORT",10000))
    threading.Thread(target=HTTPServer(("0.0.0.0",port),H).serve_forever, daemon=True).start()
    print(f"✅ Health server :{port}")

async def run_bot():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("stop",      stop))
    app.add_handler(CommandHandler("addstaff",  add_staff))
    app.add_handler(CommandHandler("dashboard", lambda u,c: send_quick_dashboard(u.message)))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🐉 Asia Dragon Bot v3 запущен!")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    while True: await asyncio.sleep(3600)

def main():
    start_health_server()
    asyncio.run(run_bot())

if __name__ == "__main__":
    main()
