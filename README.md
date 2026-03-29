# 🐉 Asia Dragon Telegram Bot

## Что умеет бот:
- 📊 Дашборд — Lagerwert, статистика, топ продажи
- ⚠️ Склад — что заканчивается с графиком
- 🏆 Топ продажи — график топ 10 блюд
- 💹 Топ маржа — график топ 10 по прибыльности
- 📦 Закупки — последние чеки
- 📈 Графики — столбики по поставщикам и складу
- 🤖 AI режим — задаёшь любой вопрос о ресторане
- 📷 Сканирование чеков — фото → Claude → база данных

## Деплой на Railway.app

### Шаг 1 — GitHub
1. Зайди на github.com
2. Создай новый репозиторий: `asiadragon-bot`
3. Загрузи три файла: bot.py, requirements.txt, railway.toml

### Шаг 2 — Railway
1. Зайди на railway.app
2. Нажми "New Project"
3. Выбери "Deploy from GitHub repo"
4. Выбери свой репозиторий asiadragon-bot

### Шаг 3 — Переменные окружения
В Railway → Variables добавь:

```
TELEGRAM_TOKEN      = твой_токен_от_botfather
ANTHROPIC_API_KEY   = твой_anthropic_ключ
SUPABASE_URL        = https://tcnmytkvpyviqufxsrxl.supabase.co
SUPABASE_SERVICE_KEY = твой_service_role_ключ
ALLOWED_USER_IDS    = твой_telegram_id (узнай у @userinfobot)
```

### Шаг 4 — Запуск
Railway автоматически запустит бот. Открой Telegram → найди своего бота → /start

## Команды бота:
- /start — главное меню
- /dashboard — полный дашборд
- /склад — что заканчивается
- /продажи — топ продажи
- /закупки — последние закупки
- /ai — AI режим (задавай вопросы)
- /stop — выключить AI режим
