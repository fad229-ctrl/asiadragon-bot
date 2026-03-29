import os
import io
import base64
import logging
import asyncio
import anthropic
from supabase import create_client
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from datetime import datetime, timedelta
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

# ─── Конфигурация ────────────────────────────────────────────────
TELEGRAM_TOKEN    = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_KEY     = os.environ["ANTHROPIC_API_KEY"]
SUPABASE_URL      = os.environ["SUPABASE_URL"]
SUPABASE_KEY      = os.environ["SUPABASE_SERVICE_KEY"]
MANAGER_IDS       = list(map(int, os.environ.get("ALLOWED_USER_IDS","").split(","))) if os.environ.get("ALLOWED_USER_IDS") else []

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
ai       = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ─── Права доступа ───────────────────────────────────────────────
def is_manager(uid): return not MANAGER_IDS or uid in MANAGER_IDS

def is_worker(uid):
    r = supabase.table("staff").select("id,role").eq("telegram_id", uid).eq("is_active", True).execute().data
    return bool(r)

def get_staff(uid):
    r = supabase.table("staff").select("*").eq("telegram_id", uid).eq("is_active", True).execute().data
    return r[0] if r else None

# ─── Форматирование ──────────────────────────────────────────────
def fmt(n, suffix="€"):
    if n is None: return "—"
    return f"{float(n):,.2f} {suffix}".replace(",","X").replace(".",",").replace("X",".")

def short(s, n=28): return s[:n]+"…" if len(str(s))>n else str(s)

# ─── Графики ─────────────────────────────────────────────────────
DARK_BG   = "#0d1117"
CARD_BG   = "#161b22"
ACCENT    = "#e8a045"
GREEN     = "#3fb950"
RED       = "#f85149"
ORANGE    = "#ff7b72"
BLUE      = "#58a6ff"
TEXT      = "#c9d1d9"
SUBTEXT   = "#8b949e"

def setup_fig(w=12, h=7):
    fig, ax = plt.subplots(figsize=(w, h))
    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(CARD_BG)
    ax.tick_params(colors=TEXT, labelsize=11)
    ax.spines[:].set_visible(False)
    for spine in ax.spines.values(): spine.set_color("#30363d")
    return fig, ax

def bar_chart(labels, values, title, subtitle="", color=ACCENT, unit="", show_values=True):
    fig, ax = setup_fig(12, max(5, len(labels)*0.7+2))
    y = range(len(labels))
    bars = ax.barh(list(y), values, color=color, height=0.6, edgecolor="none")
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, color=TEXT, fontsize=11)
    ax.invert_yaxis()
    if show_values:
        mx = max(values) if values else 1
        for bar, val in zip(bars, values):
            lbl = f"{val:,.1f}{unit}" if unit else f"{val:,.0f}"
            ax.text(bar.get_width() + mx*0.01, bar.get_y()+bar.get_height()/2,
                    lbl, va="center", color=TEXT, fontsize=11, fontweight="bold")
    ax.set_xlim(0, max(values)*1.2 if values else 1)
    ax.xaxis.set_visible(False)
    fig.text(0.02, 0.98, title, color=TEXT, fontsize=14, fontweight="bold", va="top")
    if subtitle:
        fig.text(0.02, 0.93, subtitle, color=SUBTEXT, fontsize=10, va="top")
    plt.tight_layout(rect=[0,0,1,0.92])
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    buf.seek(0); plt.close(); return buf

def stock_level_chart(items):
    """Специальный график уровня запасов с цветовыми зонами"""
    if not items: return None
    labels = [short(x["name"], 25) for x in items[:12]]
    values = [x["pct"] for x in items[:12]]
    colors = [RED if v<30 else ORANGE if v<70 else GREEN for v in values]

    fig, ax = setup_fig(12, max(5, len(labels)*0.75+2))
    y = range(len(labels))
    bars = ax.barh(list(y), values, color=colors, height=0.6, edgecolor="none")
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, color=TEXT, fontsize=11)
    ax.invert_yaxis()
    ax.axvline(100, color="#30363d", linestyle="--", linewidth=1.5, alpha=0.7)
    for bar, val, item in zip(bars, values, items[:12]):
        ax.text(bar.get_width()+1, bar.get_y()+bar.get_height()/2,
                f"{val:.0f}%  ({item['qty']:.1f}/{item['min']:.0f} {item['unit']})",
                va="center", color=TEXT, fontsize=10)
    ax.set_xlim(0, 130)
    ax.xaxis.set_visible(False)

    # Легенда
    from matplotlib.patches import Patch
    legend = [Patch(color=RED, label="Критично <30%"),
              Patch(color=ORANGE, label="Мало <70%"),
              Patch(color=GREEN, label="Норма")]
    ax.legend(handles=legend, loc="lower right", facecolor=CARD_BG,
              edgecolor="#30363d", labelcolor=TEXT, fontsize=10)

    fig.text(0.02, 0.98, "⚠️ Уровень запасов", color=TEXT, fontsize=14, fontweight="bold", va="top")
    fig.text(0.02, 0.93, "% от минимального остатка", color=SUBTEXT, fontsize=10, va="top")
    plt.tight_layout(rect=[0,0,1,0.92])
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    buf.seek(0); plt.close(); return buf

def supplier_chart(data):
    """График закупок по поставщикам — горизонтальный бар с суммами"""
    labels = [x[0] for x in data]
    values = [x[1] for x in data]
    return bar_chart(labels, values, "💰 Закупки по поставщикам", "общая сумма €", BLUE, "€")

# ─── Главное меню ────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    # Если сотрудник (не менеджер)
    if not is_manager(uid) and is_worker(uid):
        st = get_staff(uid)
        keyboard = [
            [InlineKeyboardButton("🛒 Сделать заказ", callback_data="worker_order")],
            [InlineKeyboardButton("📋 Мои заказы", callback_data="worker_my_orders")],
        ]
        await update.message.reply_text(
            f"👋 Привет, *{st['name']}*!\n\nЗдесь ты можешь заказать продукты для ресторана.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if not is_manager(uid): return

    # Быстрый дашборд для менеджера
    await send_quick_dashboard(update.message)

async def send_quick_dashboard(msg):
    """Быстрый дашборд на главном экране"""
    # Lagerwert
    r = supabase.table("stock").select("quantity,last_purchase_price").execute().data
    lagerwert = sum(float(x["quantity"] or 0)*float(x["last_purchase_price"] or 0) for x in r if x["last_purchase_price"])

    # Товары под минимумом
    knapp = sum(1 for x in r if x.get("min_quantity") and float(x.get("quantity") or 0) < float(x.get("min_quantity") or 0))
    r2 = supabase.table("stock").select("quantity,min_quantity").execute().data
    knapp = sum(1 for x in r2 if x["min_quantity"] and float(x["quantity"] or 0) < float(x["min_quantity"] or 0))

    # Закупки за неделю
    week_ago = (datetime.now()-timedelta(days=7)).strftime("%Y-%m-%d")
    r3 = supabase.table("documents").select("total_brutto,total_netto,doc_date").gte("doc_date", week_ago).execute().data
    week_sum = sum(float(x.get("total_brutto") or x.get("total_netto") or 0) for x in r3)

    # Открытые поставки (заказы сотрудников)
    r4 = supabase.table("staff_orders").select("id").eq("status","pending").execute().data

    # Изменения цен за неделю
    r5 = supabase.table("price_history").select("id").gte("price_date", week_ago).execute().data

    text = (
        f"🐉 *Asia Dragon — Дашборд*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Стоимость склада: *{fmt(lagerwert)}*\n"
        f"⚠️ Товары заканчиваются: *{knapp}*\n"
        f"📦 Закупки за неделю: *{fmt(week_sum)}*\n"
        f"🔔 Заказы сотрудников: *{len(r4)}*\n"
        f"📈 Изменения цен: *{len(r5)}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    keyboard = [
        [InlineKeyboardButton("⚠️ Что заканчивается", callback_data="stock_low"),
         InlineKeyboardButton("📦 Закупки", callback_data="purchases")],
        [InlineKeyboardButton("🔔 Заказы сотрудников", callback_data="staff_orders"),
         InlineKeyboardButton("📈 Цены изменились", callback_data="price_changes")],
        [InlineKeyboardButton("📊 Склад по группам", callback_data="stock_groups"),
         InlineKeyboardButton("🧾 Загрузить чек", callback_data="upload_receipt")],
        [InlineKeyboardButton("📉 Аналитика", callback_data="analytics"),
         InlineKeyboardButton("🤖 Спросить AI", callback_data="ask_ai")],
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
            pct = float(x["quantity"] or 0)/float(x["min_quantity"])*100
            items.append({"name": prod.get("product_name","?"), "qty": float(x["quantity"] or 0),
                         "min": float(x["min_quantity"]), "unit": x["unit"] or "",
                         "lieferant": prod.get("last_lieferant","?"), "pct": round(pct,1)})

    items.sort(key=lambda x: x["pct"])
    if not items:
        await msg.reply_text("✅ Все товары в норме!"); return

    buf = stock_level_chart(items)
    caption = f"⚠️ *Заканчивается {len(items)} товаров*\n\n"
    for x in items[:8]:
        emoji = "🔴" if x["pct"]<30 else "🟡"
        caption += f"{emoji} *{short(x['name'])}*\n   {x['qty']:.1f}/{x['min']:.0f} {x['unit']} → _{x['lieferant']}_\n"
    if len(items)>8: caption += f"\n_...ещё {len(items)-8} товаров_"

    await msg.reply_photo(buf, caption=caption, parse_mode="Markdown")

# ─── Изменения цен ───────────────────────────────────────────────
async def price_changes(update, ctx):
    msg = update.message or update.callback_query.message
    r = supabase.table("price_history").select("*").order("created_at", desc=True).limit(20).execute().data
    p = {x["id"]: x["product_name"] for x in supabase.table("products").select("id,product_name").execute().data}

    if not r:
        await msg.reply_text("📈 Изменений цен пока нет.\nОни появятся после следующих закупок."); return

    text = "📈 *Изменения цен*\n━━━━━━━━━━━━━━━━━━━━\n"
    for x in r[:15]:
        name = p.get(x["product_id"], "?")
        arrow = "🔴 ↑" if float(x["change_pct"] or 0)>0 else "🟢 ↓"
        text += f"{arrow} *{short(name)}*\n"
        text += f"   {fmt(x['old_price'])} → {fmt(x['new_price'])} ({x['change_pct']:+.1f}%)\n"
        text += f"   _{x['lieferant_key']} | {x['price_date']}_\n"
    await msg.reply_text(text, parse_mode="Markdown")

# ─── Склад по группам ────────────────────────────────────────────
async def stock_groups(update, ctx):
    msg = update.message or update.callback_query.message
    keyboard = [
        [InlineKeyboardButton("🍺 Auerbräu (напитки)", callback_data="sg_auerbraeu"),
         InlineKeyboardButton("🛒 Kaufland", callback_data="sg_kaufland")],
        [InlineKeyboardButton("🥩 Kagerer", callback_data="sg_kagerer"),
         InlineKeyboardButton("🌏 Asia Markt", callback_data="sg_asia_markt")],
        [InlineKeyboardButton("🥬 Feldbrach/Özpack", callback_data="sg_feldbrach"),
         InlineKeyboardButton("📦 Все товары", callback_data="sg_all")],
    ]
    await msg.reply_text("📊 *Выбери поставщика:*", parse_mode="Markdown",
                         reply_markup=InlineKeyboardMarkup(keyboard))

async def stock_by_supplier(update, ctx, lieferant):
    msg = update.callback_query.message
    r = supabase.table("stock").select("product_id,quantity,unit,min_quantity,last_purchase_price").execute().data
    p_all = supabase.table("products").select("id,product_name,last_lieferant").execute().data

    if lieferant == "all":
        p_map = {x["id"]: x for x in p_all}
    else:
        p_map = {x["id"]: x for x in p_all if x.get("last_lieferant","").lower() == lieferant}

    items = []
    for x in r:
        if x["product_id"] in p_map:
            prod = p_map[x["product_id"]]
            qty = float(x["quantity"] or 0)
            mn  = float(x["min_quantity"] or 0)
            items.append({
                "name": prod["product_name"],
                "qty": qty, "unit": x["unit"] or "",
                "min": mn, "price": float(x["last_purchase_price"] or 0),
                "pct": qty/mn*100 if mn>0 else 100
            })

    items.sort(key=lambda x: x["pct"])
    if not items:
        await msg.reply_text(f"Нет товаров для поставщика: {lieferant}"); return

    names  = [short(x["name"],30) for x in items[:15]]
    values = [x["qty"] for x in items[:15]]
    colors = [RED if x["pct"]<30 else ORANGE if x["pct"]<70 else ACCENT for x in items[:15]]

    fig, ax = setup_fig(12, max(6, len(names)*0.7+2))
    y = range(len(names))
    bars = ax.barh(list(y), values, color=colors, height=0.6, edgecolor="none")
    ax.set_yticks(list(y))
    ax.set_yticklabels(names, color=TEXT, fontsize=10)
    ax.invert_yaxis()
    for bar, val, item in zip(bars, values, items[:15]):
        ax.text(bar.get_width()+max(values)*0.01, bar.get_y()+bar.get_height()/2,
                f"{val:.1f} {item['unit']}", va="center", color=TEXT, fontsize=10)
    ax.xaxis.set_visible(False)
    titles = {"auerbraeu":"🍺 Auerbräu","kaufland":"🛒 Kaufland","kagerer":"🥩 Kagerer",
              "asia_markt":"🌏 Asia Markt","feldbrach":"🥬 Feldbrach","all":"📦 Все"}
    fig.text(0.02, 0.98, f"Склад: {titles.get(lieferant, lieferant)}", color=TEXT, fontsize=14, fontweight="bold", va="top")
    fig.text(0.02, 0.93, f"Всего позиций: {len(items)}", color=SUBTEXT, fontsize=10, va="top")
    plt.tight_layout(rect=[0,0,1,0.92])
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=DARK_BG)
    buf.seek(0); plt.close()

    total_val = sum(x["qty"]*x["price"] for x in items)
    await msg.reply_photo(buf, caption=f"*{titles.get(lieferant,lieferant)}* — {len(items)} позиций\n💰 Стоимость: *{fmt(total_val)}*",
                         parse_mode="Markdown")

# ─── Аналитика ───────────────────────────────────────────────────
async def analytics(update, ctx):
    msg = update.message or update.callback_query.message
    keyboard = [
        [InlineKeyboardButton("💰 Топ 10 по выручке", callback_data="an_top_revenue"),
         InlineKeyboardButton("💹 Топ 10 по марже", callback_data="an_top_marge")],
        [InlineKeyboardButton("📈 Топ продажи (кол-во)", callback_data="an_top_qty"),
         InlineKeyboardButton("💸 Закупки по поставщикам", callback_data="an_suppliers")],
        [InlineKeyboardButton("🔝 Дорогие блюда", callback_data="an_expensive"),
         InlineKeyboardButton("📉 Подорожавшие", callback_data="an_price_up")],
    ]
    await msg.reply_text("📉 *Аналитика — выбери отчёт:*", parse_mode="Markdown",
                         reply_markup=InlineKeyboardMarkup(keyboard))

async def an_top_revenue(msg):
    r = supabase.table("orderbird_sales").select("product_name,total_price").execute().data
    from collections import defaultdict
    agg = defaultdict(float)
    for x in r: agg[x["product_name"]] += float(x.get("total_price") or 0)
    top = sorted(agg.items(), key=lambda x: x[1], reverse=True)[:10]
    if not top: await msg.reply_text("Нет данных о продажах"); return
    buf = bar_chart([short(x[0]) for x in top], [x[1] for x in top],
                    "💰 Топ 10 по выручке", "март 2026 | €", ACCENT, "€")
    await msg.reply_photo(buf, caption="💰 *Топ 10 блюд по выручке*", parse_mode="Markdown")

async def an_top_marge(msg):
    r = supabase.table("recipes_hauptspeisen").select("dish_name,sell_price,cost_per_portion").execute().data
    items = [(x["dish_name"], round((1-float(x["cost_per_portion"])/float(x["sell_price"]))*100,1))
             for x in r if x["sell_price"] and x["cost_per_portion"] and float(x["sell_price"])>0]
    top = sorted(items, key=lambda x: x[1], reverse=True)[:10]
    buf = bar_chart([short(x[0]) for x in top], [x[1] for x in top],
                    "💹 Топ 10 по марже", "Hauptspeisen | %", GREEN, "%")
    await msg.reply_photo(buf, caption="💹 *Топ 10 самых прибыльных блюд*", parse_mode="Markdown")

async def an_top_qty(msg):
    r = supabase.table("orderbird_sales").select("product_name,quantity").execute().data
    from collections import defaultdict
    agg = defaultdict(int)
    for x in r: agg[x["product_name"]] += int(x.get("quantity") or 0)
    top = sorted(agg.items(), key=lambda x: x[1], reverse=True)[:10]
    if not top: await msg.reply_text("Нет данных о продажах"); return
    buf = bar_chart([short(x[0]) for x in top], [x[1] for x in top],
                    "📈 Топ 10 по количеству", "март 2026 | порций", BLUE, " пор.")
    await msg.reply_photo(buf, caption="📈 *Топ 10 самых популярных блюд*", parse_mode="Markdown")

async def an_suppliers(msg):
    r = supabase.table("documents").select("lieferant_name,total_brutto,total_netto").execute().data
    from collections import defaultdict
    agg = defaultdict(float)
    for x in r: agg[x["lieferant_name"]] += float(x.get("total_brutto") or x.get("total_netto") or 0)
    top = sorted(agg.items(), key=lambda x: x[1], reverse=True)[:8]
    buf = supplier_chart(top)
    await msg.reply_photo(buf, caption="💰 *Закупки по поставщикам*", parse_mode="Markdown")

async def an_expensive(msg):
    r = supabase.table("recipes_hauptspeisen").select("dish_name,sell_price").order("sell_price", desc=True).limit(10).execute().data
    buf = bar_chart([short(x["dish_name"]) for x in r], [float(x["sell_price"]) for x in r],
                    "💸 Топ 10 дорогих блюд", "цена продажи | €", ORANGE, "€")
    await msg.reply_photo(buf, caption="💸 *Самые дорогие блюда в меню*", parse_mode="Markdown")

async def an_price_up(msg):
    r = supabase.table("price_history").select("product_id,change_pct,old_price,new_price").gt("change_pct",0).order("change_pct",desc=True).limit(10).execute().data
    p = {x["id"]: x["product_name"] for x in supabase.table("products").select("id,product_name").execute().data}
    if not r: await msg.reply_text("📉 Подорожавших ингредиентов пока нет.\nПоявятся после следующих закупок."); return
    buf = bar_chart([short(p.get(x["product_id"],"?")) for x in r],
                    [float(x["change_pct"]) for x in r],
                    "📉 Подорожавшие ингредиенты", "рост цены | %", RED, "%")
    await msg.reply_photo(buf, caption="📉 *Ингредиенты которые подорожали*", parse_mode="Markdown")

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
    await msg.reply_text(text, parse_mode="Markdown")

# ─── Сканирование чеков ──────────────────────────────────────────
async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_manager(uid): return
    await update.message.reply_text("🔍 Сканирую чек...")
    photo = await update.message.photo[-1].get_file()
    photo_bytes = await photo.download_as_bytearray()
    image_data = base64.b64encode(photo_bytes).decode("utf-8")
    response = ai.messages.create(
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
        keyboard = [[InlineKeyboardButton("✅ Сохранить", callback_data="save_receipt"),
                     InlineKeyboardButton("❌ Отмена", callback_data="cancel")]]
        ctx.user_data["pending_receipt"] = data
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ─── Заказы сотрудников ──────────────────────────────────────────
async def staff_orders_view(update, ctx):
    msg = update.message or update.callback_query.message
    r = supabase.table("staff_orders").select("*").eq("status","pending").order("created_at",desc=True).execute().data
    if not r:
        await msg.reply_text("✅ Нет новых заказов от сотрудников"); return

    text = f"🔔 *Заказы сотрудников* ({len(r)} новых)\n━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = []
    for order in r:
        items = supabase.table("staff_order_items").select("product_name,quantity,unit").eq("order_id",order["id"]).execute().data
        text += f"\n👤 *{order['staff_name']}* | {order['created_at'][:10]}\n"
        for it in items:
            text += f"  • {it['product_name']} — {it['quantity']} {it['unit']}\n"
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

    # Показываем популярные продукты для заказа
    r = supabase.table("stock").select("product_id,quantity,min_quantity,unit").execute().data
    p = {x["id"]: x for x in supabase.table("products").select("id,product_name,last_lieferant").execute().data}

    # Показываем что заканчивается
    low = []
    for x in r:
        if x["min_quantity"] and float(x["quantity"] or 0) < float(x["min_quantity"] or 0):
            prod = p.get(x["product_id"],{})
            low.append(f"• {prod.get('product_name','?')} ({float(x['quantity']):.1f}/{float(x['min_quantity']):.0f} {x['unit'] or ''})")

    text = "🛒 *Новый заказ продуктов*\n\n"
    if low:
        text += f"⚠️ *Заканчивается ({len(low)}):\n*" + "\n".join(low[:10]) + "\n\n"
    text += "Напиши что нужно заказать в формате:\n_Продукт — количество единица_\n\nНапример:\nЛосось — 10 кг\nАвокадо — 2 кг\nГинджер — 1 кг"

    ctx.user_data["worker_ordering"] = True
    ctx.user_data["worker_items"] = []
    await msg.reply_text(text, parse_mode="Markdown")

async def worker_my_orders(update, ctx):
    msg = update.message or update.callback_query.message
    uid = update.effective_user.id
    r = supabase.table("staff_orders").select("*").eq("telegram_id",uid).order("created_at",desc=True).limit(10).execute().data
    if not r:
        await msg.reply_text("У тебя ещё нет заказов."); return
    text = "📋 *Твои заказы:*\n\n"
    status_emoji = {"pending":"⏳","approved":"✅","ordered":"📦","received":"🎉","cancelled":"❌"}
    for o in r:
        emoji = status_emoji.get(o["status"],"❓")
        text += f"{emoji} *{o['created_at'][:10]}* — {o['status']}\n"
        if o.get("notes"): text += f"   _{o['notes']}_\n"
    await msg.reply_text(text, parse_mode="Markdown")

# ─── Управление сотрудниками ─────────────────────────────────────
async def manage_staff(update, ctx):
    msg = update.message or update.callback_query.message
    uid = update.effective_user.id
    if not is_manager(uid): return
    r = supabase.table("staff").select("*").eq("is_active",True).execute().data
    text = "👥 *Сотрудники*\n━━━━━━━━━━━━━━━━━━━━\n"
    for s in r:
        text += f"• *{s['name']}* (ID: {s['telegram_id']}) — {s['role']}\n"
    text += "\n_Чтобы добавить сотрудника:_\n`/addstaff [telegram_id] [имя]`"
    await msg.reply_text(text, parse_mode="Markdown")

async def add_staff(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_manager(uid): return
    args = ctx.args
    if len(args) < 2:
        await update.message.reply_text("Использование: `/addstaff [telegram_id] [имя]`", parse_mode="Markdown"); return
    try:
        tg_id = int(args[0])
        name  = " ".join(args[1:])
        supabase.table("staff").upsert({"telegram_id":tg_id,"name":name,"role":"worker","is_active":True}).execute()
        await update.message.reply_text(f"✅ Сотрудник *{name}* добавлен!", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ─── AI Анализ ───────────────────────────────────────────────────
async def ask_ai_menu(update, ctx):
    msg = update.message or update.callback_query.message
    ctx.user_data["ai_mode"] = True
    await msg.reply_text(
        "🤖 *AI Режим активирован*\n\n"
        "Задай любой вопрос:\n"
        "• _Какая себестоимость блюда 271?_\n"
        "• _Сколько стоит Lachs на складе?_\n"
        "• _Топ 5 блюд по марже?_\n"
        "• _Что нужно заказать у Kagerer?_\n"
        "• _Сравни продажи Com Ga и Com Vit_\n\n"
        "Для выхода: /stop", parse_mode="Markdown")

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    # Режим заказа сотрудника
    if ctx.user_data.get("worker_ordering") and is_worker(uid):
        await handle_worker_order_text(update, ctx, text)
        return

    # AI режим (только менеджер)
    if ctx.user_data.get("ai_mode") and is_manager(uid):
        await handle_ai_question(update, ctx, text)
        return

async def handle_ai_question(update, ctx, question):
    await update.message.reply_text("🤔 Анализирую...")

    # Собираем полный контекст из базы
    stock_r   = supabase.table("stock").select("product_id,quantity,unit,min_quantity,last_purchase_price").execute().data
    prods_r   = supabase.table("products").select("id,product_name,last_lieferant,unit").execute().data
    sales_r   = supabase.table("orderbird_sales").select("product_name,quantity,total_price,plu").execute().data
    docs_r    = supabase.table("documents").select("lieferant_name,doc_date,total_brutto,total_netto").order("doc_date",desc=True).limit(20).execute().data
    haupt_r   = supabase.table("recipes_hauptspeisen").select("dish_number,dish_name,sell_price,cost_per_portion").execute().data
    sushi_r   = supabase.table("recipes_sushi").select("dish_number,dish_name,sell_price,cost_per_portion").execute().data
    vor_r     = supabase.table("recipes_vorspeisen").select("dish_number,dish_name,sell_price,cost_per_portion").execute().data

    prods = {x["id"]: x for x in prods_r}

    # Строим контекст
    stock_info = []
    for x in stock_r:
        p = prods.get(x["product_id"],{})
        stock_info.append({"id":x["product_id"],"name":p.get("product_name"),"qty":float(x["quantity"] or 0),
                           "unit":x["unit"],"min":float(x["min_quantity"] or 0),
                           "price":float(x["last_purchase_price"] or 0),"lieferant":p.get("last_lieferant")})

    from collections import defaultdict
    sales_agg = defaultdict(lambda:{"qty":0,"revenue":0,"plu":""})
    for x in sales_r:
        sales_agg[x["product_name"]]["qty"]     += int(x.get("quantity") or 0)
        sales_agg[x["product_name"]]["revenue"] += float(x.get("total_price") or 0)
        sales_agg[x["product_name"]]["plu"]      = x.get("plu","")

    all_recipes = haupt_r + sushi_r + vor_r

    prompt = f"""Ты AI помощник ресторана Asia Dragon (Германия, Bad Aibling).
У тебя есть ПОЛНЫЙ доступ к базе данных ресторана.

СКЛАД ({len(stock_info)} позиций):
{stock_info}

ВСЕ РЕЦЕПТЫ ({len(all_recipes)} блюд):
{all_recipes}

ПРОДАЖИ март 2026:
{dict(list(sales_agg.items())[:50])}

ЗАКУПКИ (последние 20):
{docs_r}

Вопрос: {question}

Отвечай по-русски, конкретно с цифрами из данных.
Если спрашивают о конкретном блюде — найди его в рецептах и дай полную информацию.
Если спрашивают о продукте — найди в складе и дай полную информацию.
Используй эмодзи для читаемости."""

    response = ai.messages.create(
        model="claude-sonnet-4-5", max_tokens=1500,
        messages=[{"role":"user","content":prompt}]
    )
    await update.message.reply_text(response.content[0].text, parse_mode="Markdown")

async def handle_worker_order_text(update, ctx, text):
    uid = update.effective_user.id
    st  = get_staff(uid)
    items = ctx.user_data.get("worker_items",[])

    if text.lower() in ["/done","готово","отправить","send"]:
        if not items:
            await update.message.reply_text("Список пустой. Добавь продукты."); return

        # Сохраняем заказ
        order = supabase.table("staff_orders").insert({
            "telegram_id":uid,"staff_name":st["name"],"status":"pending"
        }).execute().data[0]

        for it in items:
            supabase.table("staff_order_items").insert({
                "order_id":order["id"],"product_name":it["name"],
                "quantity":it["qty"],"unit":it["unit"]
            }).execute()

        ctx.user_data["worker_ordering"] = False
        ctx.user_data["worker_items"] = []

        # Уведомляем менеджеров
        item_text = "\n".join([f"• {it['name']} — {it['qty']} {it['unit']}" for it in items])
        notify = f"🔔 *Новый заказ от {st['name']}*\n\n{item_text}"
        for manager_id in MANAGER_IDS:
            try:
                await ctx.bot.send_message(manager_id, notify, parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_order_{order['id']}"),
                        InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_order_{order['id']}")
                    ]]))
            except: pass

        await update.message.reply_text(
            f"✅ Заказ отправлен менеджеру!\n\n{item_text}\n\nОжидай подтверждения.", parse_mode="Markdown")
        return

    # Парсим строку "Продукт — количество единица"
    try:
        parts = text.replace("—","-").replace("–","-").split("-")
        name  = parts[0].strip()
        rest  = parts[1].strip().split() if len(parts)>1 else ["1","шт"]
        qty   = float(rest[0].replace(",","."))
        unit  = rest[1] if len(rest)>1 else "шт"
        items.append({"name":name,"qty":qty,"unit":unit})
        ctx.user_data["worker_items"] = items
        await update.message.reply_text(
            f"✅ Добавлено: *{name}* — {qty} {unit}\n\nПродолжай добавлять или напиши *готово* для отправки.",
            parse_mode="Markdown")
    except:
        await update.message.reply_text(
            "❓ Не понял формат. Пиши так:\n_Лосось — 10 кг_\n_Авокадо — 2 кг_\n\nИли напиши *готово* для отправки заказа.",
            parse_mode="Markdown")

async def stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["ai_mode"] = False
    ctx.user_data["worker_ordering"] = False
    await update.message.reply_text("✅ /start для меню.")

# ─── Загрузка Orderbird CSV ──────────────────────────────────────
async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_manager(uid): return
    doc   = update.message.document
    fname = doc.file_name or ""
    if fname.endswith(".csv") and "report" in fname.lower():
        await update.message.reply_text("📊 Получил Orderbird CSV — обрабатываю...")
        file  = await doc.get_file()
        data  = await file.download_as_bytearray()
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
    if not start_idx:
        await update.message.reply_text("❌ Секция Produkte не найдена"); return
    sales = []
    for line in lines[start_idx:]:
        if not line.strip(): break
        parts = line.split(";")
        if len(parts)>=4 and parts[1] and parts[2]:
            name,plu = parts[0].strip(),parts[1].strip().rstrip(".")
            try:
                qty,total = int(parts[2]),float(parts[3].replace(",","."))
                if "KUNDENKARTE" in name or "Wertgutschein" in name: continue
                sales.append({"name":name,"plu":plu if plu!="0" else None,"qty":qty,"total":total,
                               "unit_price":round(total/qty,4) if qty else 0})
            except: pass
    report = supabase.table("orderbird_reports").insert({
        "report_type":"day" if date_from==date_to else "month",
        "date_from":date_from,"date_to":date_to,"total_brutto":total_brutto,
        "total_portions":sum(s["qty"] for s in sales),"file_name":fname,"processed":False
    }).execute().data[0]
    rid = report["id"]
    for i in range(0,len(sales),50):
        supabase.table("orderbird_sales").insert([
            {"report_id":rid,"plu":s["plu"],"product_name":s["name"],
             "quantity":s["qty"],"total_price":s["total"],"unit_price":s["unit_price"],"matched":False}
            for s in sales[i:i+50]
        ]).execute()
    matched = auto_match(rid)
    supabase.table("orderbird_reports").update({"processed":True}).eq("id",rid).execute()
    await update.message.reply_text(
        f"✅ *CSV загружен!*\n📅 {date_from} → {date_to}\n💰 {fmt(total_brutto)}\n"
        f"🍽 Позиций: {len(sales)}\n🔗 Сопоставлено: {matched}/{len(sales)}",
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
    drink_map = {r["orderbird_name"]:r["recipe_drink_id"]
                 for r in supabase.table("orderbird_drink_mapping").select("*").execute().data or []
                 if r.get("recipe_drink_id")}
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

# ─── Callback обработчик ─────────────────────────────────────────
async def button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data

    if d == "dashboard":          await send_quick_dashboard(q.message)
    elif d == "stock_low":        await stock_low(update, ctx)
    elif d == "purchases":        await purchases(update, ctx)
    elif d == "price_changes":    await price_changes(update, ctx)
    elif d == "stock_groups":     await stock_groups(update, ctx)
    elif d == "analytics":        await analytics(update, ctx)
    elif d == "ask_ai":           await ask_ai_menu(update, ctx)
    elif d == "staff_orders":     await staff_orders_view(update, ctx)
    elif d == "manage_staff":     await manage_staff(update, ctx)
    elif d == "worker_order":     await worker_order_start(update, ctx)
    elif d == "worker_my_orders": await worker_my_orders(update, ctx)
    elif d == "upload_receipt":   await q.message.reply_text("📷 Отправь фото чека")
    elif d == "cancel":           await q.message.reply_text("❌ Отменено")

    elif d.startswith("sg_"):
        lieferant = d[3:]
        await stock_by_supplier(update, ctx, lieferant)

    elif d.startswith("an_"):
        msg = q.message
        if d == "an_top_revenue": await an_top_revenue(msg)
        elif d == "an_top_marge": await an_top_marge(msg)
        elif d == "an_top_qty":   await an_top_qty(msg)
        elif d == "an_suppliers": await an_suppliers(msg)
        elif d == "an_expensive": await an_expensive(msg)
        elif d == "an_price_up":  await an_price_up(msg)

    elif d.startswith("approve_order_"):
        order_id = int(d.split("_")[-1])
        supabase.table("staff_orders").update({"status":"approved","approved_by":"manager","approved_at":datetime.now().isoformat()}).eq("id",order_id).execute()
        order = supabase.table("staff_orders").select("*").eq("id",order_id).execute().data[0]
        try: await ctx.bot.send_message(order["telegram_id"],"✅ Твой заказ одобрен! Продукты будут заказаны.")
        except: pass
        await q.message.reply_text(f"✅ Заказ #{order_id} одобрен!")

    elif d.startswith("reject_order_"):
        order_id = int(d.split("_")[-1])
        supabase.table("staff_orders").update({"status":"cancelled"}).eq("id",order_id).execute()
        order = supabase.table("staff_orders").select("*").eq("id",order_id).execute().data[0]
        try: await ctx.bot.send_message(order["telegram_id"],"❌ Твой заказ отклонён менеджером.")
        except: pass
        await q.message.reply_text(f"❌ Заказ #{order_id} отклонён")

    elif d == "save_receipt":
        receipt = ctx.user_data.get("pending_receipt")
        if receipt:
            try:
                doc = supabase.table("documents").insert({
                    "lieferant_key":receipt["lieferant_key"],"lieferant_name":receipt["lieferant_name"],
                    "doc_type":"Kassenbon","doc_date":receipt["doc_date"],
                    "bon_nr":receipt.get("bon_nr"),"total_brutto":receipt.get("total_brutto")
                }).execute()
                doc_id = doc.data[0]["id"]
                for item in receipt["items"]:
                    supabase.table("document_items").insert({
                        "document_id":doc_id,"lieferant_key":receipt["lieferant_key"],
                        "raw_text":item["raw_text"],"quantity":item["quantity"],"unit":item["unit"],
                        "unit_price":item["unit_price"],"total_price":item["total_price"]
                    }).execute()
                await q.message.reply_text(f"✅ Чек сохранён! ID: {doc_id}, позиций: {len(receipt['items'])}")
                ctx.user_data.pop("pending_receipt",None)
            except Exception as e:
                await q.message.reply_text(f"❌ Ошибка: {e}")

# ─── Health server + запуск ──────────────────────────────────────
def start_health_server():
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers()
            self.wfile.write(b"OK")
        def log_message(self,*a): pass
    port = int(os.environ.get("PORT",10000))
    HTTPServer(("0.0.0.0",port),H).serve_forever() if False else \
    threading.Thread(target=HTTPServer(("0.0.0.0",port),H).serve_forever,daemon=True).start()
    print(f"✅ Health server :{port}")

async def run_bot():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("stop",   stop))
    app.add_handler(CommandHandler("addstaff", add_staff))
    app.add_handler(CommandHandler("dashboard", lambda u,c: send_quick_dashboard(u.message)))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🐉 Asia Dragon Bot v2 запущен!")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    while True: await asyncio.sleep(3600)

def main():
    start_health_server()
    asyncio.run(run_bot())

if __name__ == "__main__":
    main()
