import os
import io
import base64
import logging
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
import matplotlib.patches as mpatches
import numpy as np

# ─── Конфигурация ───────────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_KEY    = os.environ["ANTHROPIC_API_KEY"]
SUPABASE_URL     = os.environ["SUPABASE_URL"]
SUPABASE_KEY     = os.environ["SUPABASE_SERVICE_KEY"]
ALLOWED_USER_IDS = list(map(int, os.environ.get("ALLOWED_USER_IDS", "").split(","))) if os.environ.get("ALLOWED_USER_IDS") else []

# ─── Клиенты ────────────────────────────────────────────────────
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
ai       = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ─── Вспомогательные функции ────────────────────────────────────
def fmt(n, suffix="€"):
    if n is None: return "—"
    return f"{float(n):,.2f} {suffix}".replace(",", "X").replace(".", ",").replace("X", ".")

def is_allowed(user_id: int) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS

def sql(query: str) -> list:
    result = supabase.rpc("execute_sql_fn", {"query": query}).execute()
    return result.data or []

def sql_direct(table, select="*", filters_dict=None, order=None, limit=None):
    q = supabase.table(table).select(select)
    if filters_dict:
        for k, v in filters_dict.items():
            q = q.eq(k, v)
    if order:
        q = q.order(order[0], desc=order[1])
    if limit:
        q = q.limit(limit)
    return q.execute().data or []

# ─── Генерация графиков ──────────────────────────────────────────
def make_bar_chart(labels, values, title, color="#E8A045", xlabel="", ylabel=""):
    fig, ax = plt.subplots(figsize=(10, 6))
    fig.patch.set_facecolor('#1a1a2e')
    ax.set_facecolor('#16213e')
    bars = ax.barh(labels[::-1], values[::-1], color=color, edgecolor='none', height=0.6)
    for bar, val in zip(bars, values[::-1]):
        ax.text(bar.get_width() + max(values)*0.01, bar.get_y() + bar.get_height()/2,
                f'{val:,.1f}', va='center', color='white', fontsize=11, fontweight='bold')
    ax.set_title(title, color='white', fontsize=14, fontweight='bold', pad=15)
    ax.set_xlabel(xlabel, color='#aaaaaa', fontsize=10)
    ax.tick_params(colors='white', labelsize=10)
    ax.spines[:].set_visible(False)
    ax.xaxis.set_visible(False)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close()
    return buf

def make_multi_bar_chart(categories, series_data, series_labels, title, colors=None):
    if not colors:
        colors = ['#E8A045', '#4CAF50', '#2196F3', '#E91E63']
    x = np.arange(len(categories))
    width = 0.8 / len(series_data)
    fig, ax = plt.subplots(figsize=(12, 6))
    fig.patch.set_facecolor('#1a1a2e')
    ax.set_facecolor('#16213e')
    for i, (data, label, color) in enumerate(zip(series_data, series_labels, colors)):
        offset = (i - len(series_data)/2 + 0.5) * width
        bars = ax.bar(x + offset, data, width, label=label, color=color, edgecolor='none')
    ax.set_xticks(x)
    ax.set_xticklabels(categories, rotation=45, ha='right', color='white', fontsize=9)
    ax.tick_params(colors='white')
    ax.spines[:].set_visible(False)
    ax.yaxis.set_visible(False)
    ax.set_title(title, color='white', fontsize=14, fontweight='bold', pad=15)
    ax.legend(facecolor='#1a1a2e', edgecolor='none', labelcolor='white')
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
    buf.seek(0)
    plt.close()
    return buf

# ─── Команды ────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    keyboard = [
        [InlineKeyboardButton("📊 Дашборд", callback_data="dashboard"),
         InlineKeyboardButton("⚠️ Склад", callback_data="stock_low")],
        [InlineKeyboardButton("🏆 Топ продажи", callback_data="top_sales"),
         InlineKeyboardButton("💹 Топ маржа", callback_data="top_marge")],
        [InlineKeyboardButton("📦 Закупки", callback_data="purchases"),
         InlineKeyboardButton("📈 Графики", callback_data="charts")],
        [InlineKeyboardButton("🤖 Спросить AI", callback_data="ask_ai")],
    ]
    await update.message.reply_text(
        "🐉 *Asia Dragon — Управление рестораном*\n\n"
        "Выбери что хочешь посмотреть:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def dashboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return
    msg = update.message or update.callback_query.message

    # Lagerwert
    r = supabase.table("stock").select("quantity,last_purchase_price").execute().data
    lagerwert = sum((float(x["quantity"] or 0)) * (float(x["last_purchase_price"] or 0)) for x in r if x["last_purchase_price"])

    # Товары под минимумом
    r2 = supabase.table("stock").select("quantity,min_quantity").execute().data
    knapp = sum(1 for x in r2 if x["min_quantity"] and float(x["quantity"] or 0) < float(x["min_quantity"] or 0))

    # Закупки за неделю
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    r3 = supabase.table("documents").select("total_brutto,total_netto,doc_date").gte("doc_date", week_ago).execute().data
    week_sum = sum(float(x.get("total_brutto") or x.get("total_netto") or 0) for x in r3)

    # Открытые поставки
    r4 = supabase.table("order_requests").select("id").in_("status", ["ordered","pending","draft"]).execute().data

    # Топ 3 продажи
    r5 = supabase.table("orderbird_sales").select("product_name,quantity").execute().data
    from collections import defaultdict
    sales_agg = defaultdict(int)
    for x in r5:
        if x.get("quantity"):
            sales_agg[x["product_name"]] += int(x["quantity"])
    top3 = sorted(sales_agg.items(), key=lambda x: x[1], reverse=True)[:3]

    text = (
        f"📊 *ДАШБОРД Asia Dragon*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Lagerwert: *{fmt(lagerwert)}*\n"
        f"⚠️ Товары заканчиваются: *{knapp}*\n"
        f"📦 Закупки за неделю: *{fmt(week_sum)}*\n"
        f"🚚 Открытые поставки: *{len(r4)}*\n\n"
        f"🏆 *ТОП ПРОДАЖИ (март)*\n"
    )
    for i, (name, qty) in enumerate(top3, 1):
        short = name[:30] + "…" if len(name) > 30 else name
        text += f"{i}. {short} — *{qty} порций*\n"

    await msg.reply_text(text, parse_mode="Markdown")

async def stock_low(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return
    msg = update.message or update.callback_query.message

    r = supabase.table("stock").select("product_id,quantity,unit,min_quantity").execute().data
    p = supabase.table("products").select("id,product_name,last_lieferant").execute().data
    products = {x["id"]: x for x in p}

    low = []
    for x in r:
        if x["min_quantity"] and float(x["quantity"] or 0) < float(x["min_quantity"] or 0):
            prod = products.get(x["product_id"], {})
            low.append({
                "name": prod.get("product_name", "?"),
                "qty": float(x["quantity"] or 0),
                "min": float(x["min_quantity"] or 0),
                "unit": x["unit"] or "",
                "lieferant": prod.get("last_lieferant", "?")
            })

    low.sort(key=lambda x: x["qty"] / x["min"] if x["min"] else 1)

    if not low:
        await msg.reply_text("✅ Все товары в норме!")
        return

    text = f"⚠️ *ТОВАРЫ ЗАКАНЧИВАЮТСЯ* ({len(low)} позиций)\n━━━━━━━━━━━━━━━━━━━━\n"
    for x in low[:15]:
        pct = int(x["qty"] / x["min"] * 100) if x["min"] else 0
        emoji = "🔴" if pct < 30 else "🟡"
        text += f"{emoji} *{x['name'][:28]}*\n"
        text += f"   {x['qty']:.1f}/{x['min']:.0f} {x['unit']} → {x['lieferant']}\n"

    await msg.reply_text(text, parse_mode="Markdown")

async def top_sales(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return
    msg = update.message or update.callback_query.message

    r = supabase.table("orderbird_sales").select("product_name,quantity,total_price").execute().data
    from collections import defaultdict
    agg = defaultdict(lambda: {"qty": 0, "revenue": 0})
    for x in r:
        if x.get("quantity"):
            agg[x["product_name"]]["qty"] += int(x["quantity"])
            agg[x["product_name"]]["revenue"] += float(x.get("total_price") or 0)

    top = sorted(agg.items(), key=lambda x: x[1]["qty"], reverse=True)[:10]

    labels = [x[0][:25] for x in top]
    values = [x[1]["qty"] for x in top]

    buf = make_bar_chart(labels, values, "🏆 Топ 10 продаж (март 2026)", "#E8A045", ylabel="Порций")
    await msg.reply_photo(buf, caption="🏆 *Топ 10 самых продаваемых блюд*\n_(март 2026)_", parse_mode="Markdown")

async def top_marge(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return
    msg = update.message or update.callback_query.message

    r = supabase.table("recipes_hauptspeisen").select(
        "dish_number,dish_name,sell_price,cost_per_portion"
    ).execute().data

    items = []
    for x in r:
        if x["sell_price"] and x["cost_per_portion"] and float(x["sell_price"]) > 0:
            marge = (1 - float(x["cost_per_portion"]) / float(x["sell_price"])) * 100
            items.append({"name": x["dish_name"], "marge": round(marge, 1),
                         "sell": float(x["sell_price"]), "cost": float(x["cost_per_portion"])})

    top = sorted(items, key=lambda x: x["marge"], reverse=True)[:10]

    labels = [x["name"][:28] for x in top]
    values = [x["marge"] for x in top]

    buf = make_bar_chart(labels, values, "💹 Топ 10 по марже (%)", "#4CAF50", ylabel="%")
    await msg.reply_photo(buf, caption="💹 *Топ 10 блюд по марже*", parse_mode="Markdown")

async def purchases(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return
    msg = update.message or update.callback_query.message

    r = supabase.table("documents").select(
        "lieferant_name,doc_date,total_brutto,total_netto,bon_nr"
    ).order("doc_date", desc=True).limit(10).execute().data

    text = "📦 *ПОСЛЕДНИЕ ЗАКУПКИ*\n━━━━━━━━━━━━━━━━━━━━\n"
    for x in r:
        summe = x.get("total_brutto") or x.get("total_netto") or 0
        text += f"📅 *{x['doc_date']}* — {x['lieferant_name']}\n"
        text += f"   {fmt(summe)} | #{x.get('bon_nr','—')}\n"

    # Итого за месяц
    month_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    r2 = supabase.table("documents").select("total_brutto,total_netto").gte("doc_date", month_ago).execute().data
    month_sum = sum(float(x.get("total_brutto") or x.get("total_netto") or 0) for x in r2)
    text += f"\n💰 *Итого за 30 дней: {fmt(month_sum)}*"

    await msg.reply_text(text, parse_mode="Markdown")

async def charts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return
    msg = update.message or update.callback_query.message

    keyboard = [
        [InlineKeyboardButton("📊 Продажи по категориям", callback_data="chart_categories")],
        [InlineKeyboardButton("💰 Закупки по поставщикам", callback_data="chart_suppliers")],
        [InlineKeyboardButton("📈 Мало на складе", callback_data="chart_stock")],
    ]
    await msg.reply_text("Выбери график:", reply_markup=InlineKeyboardMarkup(keyboard))

async def chart_suppliers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.callback_query.message

    r = supabase.table("documents").select("lieferant_name,total_brutto,total_netto").execute().data
    from collections import defaultdict
    agg = defaultdict(float)
    for x in r:
        summe = float(x.get("total_brutto") or x.get("total_netto") or 0)
        agg[x["lieferant_name"]] += summe

    top = sorted(agg.items(), key=lambda x: x[1], reverse=True)[:8]
    labels = [x[0] for x in top]
    values = [x[1] for x in top]

    buf = make_bar_chart(labels, values, "💰 Закупки по поставщикам (€)", "#2196F3")
    await msg.reply_photo(buf, caption="💰 *Закупки по поставщикам*", parse_mode="Markdown")

async def chart_stock(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.callback_query.message

    r = supabase.table("stock").select("product_id,quantity,min_quantity").execute().data
    p = supabase.table("products").select("id,product_name").execute().data
    products = {x["id"]: x["product_name"] for x in p}

    low = []
    for x in r:
        if x["min_quantity"] and float(x["quantity"] or 0) < float(x["min_quantity"] or 0):
            name = products.get(x["product_id"], "?")[:20]
            pct = float(x["quantity"] or 0) / float(x["min_quantity"]) * 100
            low.append((name, round(pct, 0)))

    low.sort(key=lambda x: x[1])
    labels = [x[0] for x in low[:10]]
    values = [x[1] for x in low[:10]]
    colors = ["#f44336" if v < 30 else "#FF9800" for v in values]

    fig, ax = plt.subplots(figsize=(10, 6))
    fig.patch.set_facecolor('#1a1a2e')
    ax.set_facecolor('#16213e')
    bars = ax.barh(labels, values, color=colors, edgecolor='none')
    ax.axvline(x=100, color='white', linestyle='--', alpha=0.3, label='Минимум')
    for bar, val in zip(bars, values):
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height()/2,
                f'{val:.0f}%', va='center', color='white', fontsize=10)
    ax.set_title("⚠️ Уровень запасов (% от минимума)", color='white', fontsize=13, fontweight='bold')
    ax.tick_params(colors='white')
    ax.spines[:].set_visible(False)
    ax.xaxis.set_visible(False)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor='#1a1a2e')
    buf.seek(0)
    plt.close()

    await msg.reply_photo(buf, caption="⚠️ *Товары ниже минимального уровня*", parse_mode="Markdown")

# ─── Сканирование чеков ──────────────────────────────────────────
async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return

    await update.message.reply_text("🔍 Сканирую чек... подожди секунду")

    photo = await update.message.photo[-1].get_file()
    photo_bytes = await photo.download_as_bytearray()
    image_data = base64.b64encode(photo_bytes).decode("utf-8")

    response = ai.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_data
                    }
                },
                {
                    "type": "text",
                    "text": """Ты анализируешь чеки немецких поставщиков для ресторана Asia Dragon.
Поставщики: kaufland, lidl, oezpack, kagerer, steiner, asia_markt, ho_asia_markt, ngoc_lan, auerbraeu, feldbrach, edeka_cc

Верни ТОЛЬКО JSON без комментариев и без markdown:
{
  "lieferant_key": "...",
  "lieferant_name": "...",
  "bon_nr": "...",
  "doc_date": "YYYY-MM-DD",
  "total_brutto": 0.00,
  "items": [
    {
      "raw_text": "оригинальное название",
      "quantity": 0.0,
      "unit": "kg/st/fl/pk/l",
      "unit_price": 0.00,
      "total_price": 0.00,
      "tax_class": "A или B"
    }
  ]
}

Правила:
- Цены с точкой (1.29 не 1,29)
- Дата YYYY-MM-DD
- Только продукты для ресторана"""
                }
            ]
        }]
    )

    import json
    try:
        data = json.loads(response.content[0].text)

        text = (
            f"✅ *Чек распознан!*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏪 Поставщик: *{data['lieferant_name']}*\n"
            f"📅 Дата: *{data['doc_date']}*\n"
            f"🧾 Bon: *{data.get('bon_nr', '—')}*\n"
            f"💰 Сумма: *{fmt(data.get('total_brutto', 0))}*\n\n"
            f"📋 *Позиций: {len(data['items'])}*\n"
        )
        for item in data["items"][:8]:
            text += f"• {item['raw_text'][:30]} — {item['quantity']} {item['unit']} × {fmt(item['unit_price'])}\n"

        keyboard = [[
            InlineKeyboardButton("✅ Сохранить в базу", callback_data=f"save_receipt"),
            InlineKeyboardButton("❌ Отмена", callback_data="cancel")
        ]]

        ctx.user_data["pending_receipt"] = data
        await update.message.reply_text(text, parse_mode="Markdown",
                                        reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка распознавания: {str(e)}")

async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return

    doc = update.message.document
    fname = doc.file_name or ""

    # CSV от Orderbird
    if fname.endswith(".csv") and "report" in fname.lower():
        await update.message.reply_text("📊 Получил Orderbird CSV — обрабатываю...")
        try:
            file = await doc.get_file()
            data = await file.download_as_bytearray()
            text = data.decode("utf-8-sig")
            await process_orderbird_csv(update, ctx, text, fname)
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
        return

    # PDF чек
    if fname.lower().endswith(".pdf"):
        await update.message.reply_text(
            "📄 Получил PDF!\n"
            "Для сканирования пришли **фотографию** чека.\n"
            "Сфотографируй и отправь как изображение.",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text("❓ Неизвестный файл. Отправь фото чека или CSV из Orderbird.")


async def process_orderbird_csv(update: Update, ctx, text: str, fname: str):
    import csv, io as sio
    from collections import defaultdict

    lines = text.split("\n")

    # Читаем дату отчёта
    date_from, date_to = "2026-01-01", "2026-12-31"
    for line in lines[:5]:
        if "Datum:" in line:
            parts = line.split(";")
            if len(parts) >= 3:
                try:
                    date_from = datetime.strptime(parts[1].strip(), "%d.%m.%Y").strftime("%Y-%m-%d")
                    date_to   = datetime.strptime(parts[2].strip(), "%d.%m.%Y").strftime("%Y-%m-%d")
                except: pass

    # Читаем total
    total_brutto = 0.0
    trinkgeld = 0.0
    for line in lines[:30]:
        parts = line.split(";")
        if "Total" in parts[0] and len(parts) >= 4:
            try: total_brutto = float(parts[3].replace(",","."))
            except: pass
        if "Trinkgeld" in parts[0] and len(parts) >= 4:
            try: trinkgeld = float(parts[3].replace(",","."))
            except: pass

    # Ищем секцию Produkte
    start_idx = None
    for i, line in enumerate(lines):
        if line.startswith("Produkte;"):
            start_idx = i + 1
            break

    if start_idx is None:
        await update.message.reply_text("❌ Не найдена секция Produkte в CSV")
        return

    # Парсим позиции
    sales = []
    for line in lines[start_idx:]:
        if not line.strip(): break
        parts = line.split(";")
        if len(parts) >= 4 and parts[1] and parts[2]:
            name = parts[0].strip()
            plu  = parts[1].strip().rstrip(".")
            try:
                qty   = int(parts[2])
                total = float(parts[3].replace(",","."))
                if "KUNDENKARTE" in name or "Wertgutschein" in name:
                    continue
                sales.append({"name": name, "plu": plu if plu != "0" else None,
                               "qty": qty, "total": total,
                               "unit_price": round(total/qty, 4) if qty else 0})
            except: pass

    if not sales:
        await update.message.reply_text("❌ Позиции не найдены в файле")
        return

    # Определяем тип отчёта
    report_type = "day" if date_from == date_to else "month"

    # Сохраняем в orderbird_reports
    report_res = supabase.table("orderbird_reports").insert({
        "report_type":    report_type,
        "date_from":      date_from,
        "date_to":        date_to,
        "total_brutto":   total_brutto,
        "trinkgeld":      trinkgeld,
        "total_portions": sum(s["qty"] for s in sales),
        "file_name":      fname,
        "processed":      False
    }).execute()

    report_id = report_res.data[0]["id"]

    # Сохраняем позиции
    batch = []
    for s in sales:
        batch.append({
            "report_id":    report_id,
            "plu":          s["plu"],
            "product_name": s["name"],
            "quantity":     s["qty"],
            "total_price":  s["total"],
            "unit_price":   s["unit_price"],
            "matched":      False
        })

    # Вставляем батчами по 50
    for i in range(0, len(batch), 50):
        supabase.table("orderbird_sales").insert(batch[i:i+50]).execute()

    # Автоматическое сопоставление с рецептами
    matched = auto_match_sales(report_id)

    # Обновляем статус
    supabase.table("orderbird_reports").update({"processed": True}).eq("id", report_id).execute()

    text_reply = (
        f"✅ *Orderbird CSV загружен!*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 Период: {date_from} → {date_to}\n"
        f"💰 Выручка: *{fmt(total_brutto)}*\n"
        f"🍽 Позиций: *{len(sales)}*\n"
        f"🔗 Сопоставлено: *{matched}* из {len(sales)}\n"
        f"📊 Report ID: {report_id}"
    )
    await update.message.reply_text(text_reply, parse_mode="Markdown")


def auto_match_sales(report_id: int) -> int:
    """Автоматически сопоставляет продажи с рецептами"""
    matched_count = 0

    # Загружаем все рецепты
    tables = [
        ("recipes_hauptspeisen",      "dish_number"),
        ("recipes_vorspeisen",        "dish_number"),
        ("recipes_sushi",             "dish_number"),
        ("recipes_sushi_sets",        "dish_number"),
        ("recipes_beilagen",          "dish_number"),
        ("recipes_nachspeisen",       "dish_number"),
        ("recipes_mittag_hauptspeisen","dish_number"),
    ]

    recipe_map = {}
    for table, col in tables:
        rows = supabase.table(table).select(f"id,{col}").execute().data or []
        for r in rows:
            if r.get(col):
                recipe_map[r[col]] = {"table": table, "id": r["id"]}

    # Sushi mittag
    sm = supabase.table("sushi_mittag").select("id,dish_code").execute().data or []
    for r in sm:
        if r.get("dish_code"):
            recipe_map[r["dish_code"]] = {"table": "sushi_mittag", "id": r["id"]}

    # Напитки
    drink_map = {}
    dm = supabase.table("orderbird_drink_mapping").select("orderbird_name,recipe_drink_id").execute().data or []
    for r in dm:
        if r.get("recipe_drink_id"):
            drink_map[r["orderbird_name"]] = r["recipe_drink_id"]

    # Загружаем несопоставленные продажи
    sales = supabase.table("orderbird_sales").select("id,plu,product_name").eq("report_id", report_id).eq("matched", False).execute().data or []

    for s in sales:
        matched = False
        # По PLU
        if s["plu"] and s["plu"] in recipe_map:
            rec = recipe_map[s["plu"]]
            supabase.table("orderbird_sales").update({
                "recipe_table": rec["table"],
                "recipe_id":    rec["id"],
                "matched":      True
            }).eq("id", s["id"]).execute()
            matched = True

        # По названию напитка
        elif not s["plu"] and s["product_name"] in drink_map:
            supabase.table("orderbird_sales").update({
                "recipe_table": "recipes_getraenke",
                "recipe_id":    drink_map[s["product_name"]],
                "matched":      True
            }).eq("id", s["id"]).execute()
            matched = True

        if matched:
            matched_count += 1

    return matched_count

# ─── AI Анализ ──────────────────────────────────────────────────
async def ask_ai(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return
    msg = update.message or update.callback_query.message
    ctx.user_data["ai_mode"] = True
    await msg.reply_text(
        "🤖 *AI Режим активирован*\n\n"
        "Задай любой вопрос о своём ресторане:\n"
        "• _Что у нас заканчивается?_\n"
        "• _Какие блюда самые выгодные?_\n"
        "• _Сколько мы потратили на Kagerer?_\n"
        "• _Где у нас проблемы?_\n\n"
        "Для выхода напиши /stop",
        parse_mode="Markdown"
    )

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id): return
    if not ctx.user_data.get("ai_mode"): return

    question = update.message.text
    await update.message.reply_text("🤔 Анализирую...")

    # Собираем контекст из базы
    stock_r = supabase.table("stock").select("product_id,quantity,unit,min_quantity,last_purchase_price").execute().data
    products_r = supabase.table("products").select("id,product_name,last_lieferant").execute().data
    sales_r = supabase.table("orderbird_sales").select("product_name,quantity,total_price").execute().data
    docs_r = supabase.table("documents").select("lieferant_name,doc_date,total_brutto,total_netto").order("doc_date", desc=True).limit(20).execute().data

    products = {x["id"]: x for x in products_r}

    stock_summary = []
    for x in stock_r[:30]:
        p = products.get(x["product_id"], {})
        stock_summary.append({
            "name": p.get("product_name"),
            "qty": float(x["quantity"] or 0),
            "unit": x["unit"],
            "min": float(x["min_quantity"] or 0),
            "price": float(x["last_purchase_price"] or 0),
            "lieferant": p.get("last_lieferant")
        })

    from collections import defaultdict
    sales_agg = defaultdict(lambda: {"qty": 0, "revenue": 0})
    for x in sales_r:
        sales_agg[x["product_name"]]["qty"] += int(x.get("quantity") or 0)
        sales_agg[x["product_name"]]["revenue"] += float(x.get("total_price") or 0)
    top_sales = sorted(sales_agg.items(), key=lambda x: x[1]["qty"], reverse=True)[:15]

    context = f"""Ты AI помощник для ресторана Asia Dragon в Германии.

СКЛАД (топ позиции):
{stock_summary}

ПРОДАЖИ (топ 15):
{top_sales}

ПОСЛЕДНИЕ ЗАКУПКИ:
{docs_r[:10]}

Вопрос менеджера: {question}

Ответь коротко, по-русски, с конкретными цифрами из данных. Используй эмодзи."""

    response = ai.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1000,
        messages=[{"role": "user", "content": context}]
    )

    await update.message.reply_text(response.content[0].text, parse_mode="Markdown")

async def stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["ai_mode"] = False
    await update.message.reply_text("✅ AI режим выключен. /start для меню.")

# ─── Callback handler ────────────────────────────────────────────
async def button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    if data == "dashboard":       await dashboard(update, ctx)
    elif data == "stock_low":     await stock_low(update, ctx)
    elif data == "top_sales":     await top_sales(update, ctx)
    elif data == "top_marge":     await top_marge(update, ctx)
    elif data == "purchases":     await purchases(update, ctx)
    elif data == "charts":        await charts(update, ctx)
    elif data == "ask_ai":        await ask_ai(update, ctx)
    elif data == "chart_suppliers": await chart_suppliers(update, ctx)
    elif data == "chart_stock":   await chart_stock(update, ctx)
    elif data == "cancel":
        await q.message.reply_text("❌ Отменено")
    elif data == "save_receipt":
        receipt = ctx.user_data.get("pending_receipt")
        if receipt:
            try:
                doc = supabase.table("documents").insert({
                    "lieferant_key": receipt["lieferant_key"],
                    "lieferant_name": receipt["lieferant_name"],
                    "doc_type": "Kassenbon",
                    "doc_date": receipt["doc_date"],
                    "bon_nr": receipt.get("bon_nr"),
                    "total_brutto": receipt.get("total_brutto"),
                }).execute()
                doc_id = doc.data[0]["id"]
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
                await q.message.reply_text(
                    f"✅ *Чек сохранён в базу!*\nID документа: {doc_id}\n"
                    f"Позиций: {len(receipt['items'])}",
                    parse_mode="Markdown"
                )
                ctx.user_data.pop("pending_receipt", None)
            except Exception as e:
                await q.message.reply_text(f"❌ Ошибка сохранения: {e}")
        else:
            await q.message.reply_text("❌ Нет данных для сохранения")

# ─── Запуск ─────────────────────────────────────────────────────
def start_health_server():
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler
    class Health(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Asia Dragon Bot OK")
        def log_message(self, *args): pass
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), Health)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"✅ Health server на порту {port}")

def main():
    start_health_server()
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("dashboard", dashboard))
    app.add_handler(CommandHandler("sklad", stock_low))
    app.add_handler(CommandHandler("prodazhi", top_sales))
    app.add_handler(CommandHandler("zakupki", purchases))
    app.add_handler(CommandHandler("marga", top_marge))
    app.add_handler(CommandHandler("ai", ask_ai))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🐉 Asia Dragon Bot запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
