async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if not is_manager(uid) and is_worker(uid):
        st = get_staff(uid)
        keyboard = [
            [InlineKeyboardButton("🛒 Сделать заказ", callback_data="worker_order")],
            [InlineKeyboardButton("📋 Мои заявки", callback_data="worker_my_orders"), InlineKeyboardButton("📦 Остатки", callback_data="worker_stock")],
            [InlineKeyboardButton("ℹ️ Помощь", callback_data="worker_help")],
        ]
        await update.message.reply_text(
            f"👋 Привет, *{st['name']}*!\n\nЭто закрытая панель сотрудника. Здесь можно заказывать продукты и смотреть свои заявки.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if not is_manager(uid):
        return

    await send_quick_dashboard(update.message)

async def send_quick_dashboard(msg):
    m = dashboard_metrics()
    low_preview = "\n".join([
        f"• {short(x['name'], 22)} — {x['qty']:.1f}/{x['min']:.0f} {x['unit']}"
        for x in m["low_items"][:3]
    ]) or "• Всё в норме"
    text = (
        f"🐉 *Asia Dragon — Главный экран*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Стоимость склада: *{fmt(m['lagerwert'])}*\n"
        f"📦 Закупки за 7 дней: *{fmt(m['week_sum'])}*\n"
        f"⚠️ Заканчиваются товары: *{len(m['low_items'])}*\n"
        f"🔔 Заявки сотрудников: *{len(m['pending_orders'])}*\n"
        f"🚚 Открытые поставки: *{len(m['open_deliveries'])}*\n"
        f"📈 Подорожали товары: *{m['price_up']}*\n"
        f"🔄 Любые изменения цен: *{m['price_changed']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"*Сейчас требуют внимания:*\n{low_preview}"
    )
    keyboard = [
        [InlineKeyboardButton(f"⚠️ Низкий остаток ({len(m['low_items'])})", callback_data="stock_low"), InlineKeyboardButton(f"🔔 Заявки ({len(m['pending_orders'])})", callback_data="staff_orders")],
        [InlineKeyboardButton(f"🚚 Открытые поставки ({len(m['open_deliveries'])})", callback_data="open_deliveries"), InlineKeyboardButton(f"📈 Цены ({m['price_changed']})", callback_data="price_changes")],
        [InlineKeyboardButton("🧾 Загрузить Rechnung", callback_data="upload_receipt"), InlineKeyboardButton("➕ Добавить товар", callback_data="add_product")],
        [InlineKeyboardButton("📊 Проверить склад", callback_data="stock_groups"), InlineKeyboardButton("📦 Последние закупки", callback_data="purchases")],
        [InlineKeyboardButton("📉 Kurze Analitika", callback_data="analytics_short"), InlineKeyboardButton("🤖 Спросить AI", callback_data="ask_ai")],
        [InlineKeyboardButton("👥 Сотрудники", callback_data="manage_staff"), InlineKeyboardButton("🏠 Обновить", callback_data="dashboard")],
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
    if not is_worker(uid):
        return

    m = dashboard_metrics()
    low = [f"• {x['name']} ({x['qty']:.1f}/{x['min']:.0f} {x['unit']})" for x in m["low_items"][:10]]
    text = "🛒 *Новый заказ продуктов*\n\n"
    if low:
        text += f"⚠️ *Сейчас заканчивается ({len(m['low_items'])}):*\n" + "\n".join(low) + "\n\n"
    text += (
        "Напиши заказ обычным текстом на русском, немецком или вьетнамском.\n\n"
        "Примеры:\n"
        "• Лосось 10 кг, авокадо 5 кг, рис суши 20 кг\n"
        "• Lachs 10 kg, Avocado 5 kg, Sushi Reis 20 kg\n"
        "• Cá hồi 10kg, bơ 5kg, gạo sushi 20kg\n\n"
        "После распознавания я покажу сумму и остатки. Затем напиши *готово* для отправки шефу."
    )
    ctx.user_data["worker_ordering"] = True
    ctx.user_data["worker_items"] = []
    ctx.user_data["parsed_order_items"] = []
    ctx.user_data["parsed_order_raw_text"] = ""
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

async def worker_stock(update, ctx):
    msg = update.message or update.callback_query.message
    uid = update.effective_user.id
    if not is_worker(uid):
        return
    m = dashboard_metrics()
    low = m["low_items"][:20]
    if not low:
        await msg.reply_text("✅ Критически низких остатков сейчас нет.")
        return
    text = "📦 *Что сейчас заканчивается:*\n\n"
    for x in low:
        icon = "🔴" if x["pct"] < 30 else "🟡"
        text += f"{icon} *{x['name']}* — {x['qty']:.1f}/{x['min']:.0f} {x['unit']}\n"
    await msg.reply_text(text, parse_mode="Markdown")

async def help_cmd(update, ctx):
    msg = update.message or update.callback_query.message
    await msg.reply_text(
        "ℹ️ *Помощь*\n\n"
        "/order — создать заявку\n"
        "/my_orders — мои заявки\n"
        "/stock — остатки\n"
        "/help — помощь\n\n"
        "Можно писать заказ обычным текстом на русском, немецком и вьетнамском.\n\n"
        "Примеры:\n"
        "• Лосось 10 кг, авокадо 5 кг, рис суши 20 кг\n"
        "• Lachs 10 kg, Avocado 5 kg, Sushi Reis 20 kg\n"
        "• Cá hồi 10kg, bơ 5kg, gạo sushi 20kg",
        parse_mode="Markdown"
    )

async def open_deliveries(update, ctx):
    msg = update.message or update.callback_query.message
    rows = supabase.table("staff_orders").select("*").in_("status", ["approved", "ordered"]).order("created_at", desc=True).limit(20).execute().data or []
    if not rows:
        await msg.reply_text("✅ Сейчас нет открытых поставок.")
        return
    text = "🚚 *Открытые поставки / offene Bestellungen*\n━━━━━━━━━━━━━━━━━━━━\n"
    keyboard = []
    for order in rows[:10]:
        items = supabase.table("staff_order_items").select("product_name,quantity,unit").eq("order_id", order["id"]).execute().data or []
        text += f"\n📅 *{order['created_at'][:10]}* | 👤 {order['staff_name']} | *{order['status']}*\n"
        for it in items[:5]:
            text += f"  • {it['product_name']} — {it['quantity']} {it['unit']}\n"
        keyboard.append([InlineKeyboardButton(f"✅ Получено #{order['id']}", callback_data=f"received_order_{order['id']}")])
    await msg.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def analytics_short(update, ctx):
    msg = update.message or update.callback_query.message
    keyboard = [
        [InlineKeyboardButton("💸 Топ дорогих блюд", callback_data="an_expensive"), InlineKeyboardButton("💹 Топ по марже", callback_data="an_top_marge")],
        [InlineKeyboardButton("📉 Подорожавшие ингредиенты", callback_data="an_price_up"), InlineKeyboardButton("📈 Топ продаж", callback_data="an_top_qty")],
    ]
    await msg.reply_text("📉 *Kurze Analitika*\nБыстрые полезные отчёты прямо с главного экрана.", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

# ─── Управление сотрудниками# ─── Управление сотрудниками ─────────────────────────────────────
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
{dict(list(sales_agg.items())[:120])}

ЗАКУПКИ (последние 20):
{docs_r}

Вопрос: {question}

Отвечай по-русски, конкретно с цифрами из данных.
Если спрашивают о конкретном блюде — найди его в рецептах и дай полную информацию.
Если спрашивают о продукте — найди в складе и дай полную информацию.
Если спрашивают о графике — предложи лучший тип графика и коротко объясни, что именно должен показать график.
Если спрашивают о конкретном блюде — дай себестоимость, цену продажи, маржу и всё найденное.
Если спрашивают о конкретном продукте — дай остаток, минимум, поставщика и цену закупки.
Используй эмодзи и понятные мини-блоки для читаемости."""

    response = ai.messages.create(
        model="claude-sonnet-4-5", max_tokens=2200,
        messages=[{"role":"user","content":prompt}]
    )
    await update.message.reply_text(response.content[0].text, parse_mode="Markdown")

async def handle_worker_order_text(update, ctx, text):
    uid = update.effective_user.id
    st  = get_staff(uid)

    if normalize_text(text) in ["/done", "готово", "отправить", "send", "fertig", "xong"]:
        draft = ctx.user_data.get("parsed_order_items", [])
        if not draft:
            await update.message.reply_text("Список пустой. Сначала пришли текст заказа.")
            return

        order = supabase.table("staff_orders").insert({
            "telegram_id": uid,
            "staff_name": st["name"],
            "status": "pending",
            "notes": ctx.user_data.get("parsed_order_raw_text", "")
        }).execute().data[0]

        total_sum = 0
        for it in draft:
            total_sum += safe_float(it.get("approx_total"))
            base_row = {
                "order_id": order["id"],
                "product_name": it["name"],
                "quantity": it["qty"],
                "unit": it["unit"]
            }
            try:
                rich_row = dict(base_row)
                rich_row.update({
                    "product_id": it["product_id"],
                    "approx_total": it["approx_total"],
                    "last_price": it["last_price"],
                    "stock_qty": it["stock_qty"]
                })
                supabase.table("staff_order_items").insert(rich_row).execute()
            except Exception:
                supabase.table("staff_order_items").insert(base_row).execute()

        ctx.user_data["worker_ordering"] = False
        ctx.user_data["parsed_order_items"] = []
        ctx.user_data["parsed_order_raw_text"] = ""

        msg_lines = []
        for i, it in enumerate(draft, start=1):
            warn = " ⚠️" if it["stock_qty"] < it["qty"] or (it["min_qty"] and it["stock_qty"] < it["min_qty"]) else ""
            price_line = f"   💰 ~{fmt(it['approx_total'])} ({fmt(it['last_price'])}/{it['unit']})\n" if it["last_price"] else ""
            stock_line = f"   📊 Сейчас на складе: {it['stock_qty']:.2f} {it['unit']}{warn}"
            msg_lines.append(f"{i}. {it['name']} - {it['qty']} {it['unit']}\n{price_line}{stock_line}")

        username = f" (@{update.effective_user.username})" if update.effective_user.username else ""
        notify = (
            f"🔔 *НОВЫЙ ЗАКАЗ ОТ СОТРУДНИКА*\n"
            f"👤 Сотрудник: {st['name']}{username}\n"
            f"📅 Дата: {datetime.now().strftime('%d.%m.%Y, %H:%M')}\n\n"
            f"📦 *ЗАКАЗ:*\n" + "\n\n".join(msg_lines) + f"\n\n💵 *ИТОГО:* ~{fmt(total_sum)}"
        )
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_order_{order['id']}"), InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_order_{order['id']}")],
            [InlineKeyboardButton("📦 Отметить заказанным", callback_data=f"ordered_order_{order['id']}"), InlineKeyboardButton("🎉 Получено", callback_data=f"received_order_{order['id']}")]
        ])
        for manager_id in MANAGER_IDS:
            try:
                await ctx.bot.send_message(manager_id, notify, parse_mode="Markdown", reply_markup=reply_markup)
            except Exception as e:
                log.warning(f"notify manager failed: {e}")

        await update.message.reply_text(
            f"✅ Заказ отправлен шефу.\n\nПозиций: {len(draft)}\nСумма: ~{fmt(total_sum)}\n\nОжидай подтверждения.",
            parse_mode="Markdown"
        )
        return

    try:
        await update.message.reply_text("🤖 Распознаю заказ...")
        catalog = get_product_catalog()
        parsed = await parse_order_with_ai(text, catalog)
        final_items, unmatched = enrich_order_items(parsed, catalog)
        if not final_items:
            await update.message.reply_text("❌ Не смог распознать товары.\nПопробуй так:\nЛосось 10 кг, авокадо 5 кг, рис суши 20 кг")
            return
        ctx.user_data["parsed_order_items"] = final_items
        ctx.user_data["parsed_order_raw_text"] = text
        total_sum = sum(safe_float(x["approx_total"]) for x in final_items)
        preview = []
        for it in final_items:
            warn = " ⚠️ мало на складе" if it["stock_qty"] < it["qty"] else ""
            price = f"~{fmt(it['approx_total'])}" if it["approx_total"] else "цена неизвестна"
            preview.append(f"• *{it['name']}* — {it['qty']} {it['unit']}\n  💰 {price}\n  📊 Остаток: {it['stock_qty']:.2f} {it['unit']}{warn}")
        msg = f"✅ *Заказ распознан*\n🌐 Язык: `{parsed.get('language', 'unknown')}`\n\n" + "\n\n".join(preview) + f"\n\n💵 *Итого:* ~{fmt(total_sum)}"
        if unmatched:
            msg += "\n\n❓ Не распознано:\n" + "\n".join([f"• {x}" for x in unmatched])
        msg += "\n\nНапиши *готово* для отправки или пришли исправленный текст."
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        log.exception("worker order parse failed")
        await update.message.reply_text(f"❌ Ошибка распознавания заказа: {e}")

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
    elif d == "worker_stock":     await worker_stock(update, ctx)
    elif d == "worker_help":      await help_cmd(update, ctx)
    elif d == "open_deliveries":  await open_deliveries(update, ctx)
    elif d == "analytics_short":  await analytics_short(update, ctx)
    elif d == "add_product":      await q.message.reply_text("➕ Добавление нового товара лучше сделать отдельной формой. Пока вынес кнопку на главный экран как быстрый доступ.")
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

    elif d.startswith("ordered_order_"):
        order_id = int(d.split("_")[-1])
        supabase.table("staff_orders").update({"status":"ordered"}).eq("id",order_id).execute()
        order = supabase.table("staff_orders").select("*").eq("id",order_id).execute().data[0]
        try: await ctx.bot.send_message(order["telegram_id"],"📦 Твой заказ принят и уже отправлен поставщику.")
        except: pass
        await q.message.reply_text(f"📦 Заказ #{order_id} отмечен как заказанный")

    elif d.startswith("received_order_"):
        order_id = int(d.split("_")[-1])
        supabase.table("staff_orders").update({"status":"received"}).eq("id",order_id).execute()
        order = supabase.table("staff_orders").select("*").eq("id",order_id).execute().data[0]
        try: await ctx.bot.send_message(order["telegram_id"],"🎉 Заказ получен и закрыт.")
        except: pass
        await q.message.reply_text(f"🎉 Заказ #{order_id} отмечен как полученный")

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
    app.add_handler(CommandHandler("order", worker_order_start))
    app.add_handler(CommandHandler("my_orders", worker_my_orders))
    app.add_handler(CommandHandler("stock", worker_stock))
    app.add_handler(CommandHandler("help", help_cmd))
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
