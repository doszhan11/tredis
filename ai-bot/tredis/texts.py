"""User-facing strings in Kazakh, Russian and English. {placeholders} are filled with str.format."""

T = {
    "welcome_paid": {
        "kk": "Сәлем, {name}! 🤖 TREDIS AI көмекшісіне қош келдіңіз.\nТарифіңіз: <b>{tier}</b>{until}.\n\n{help}",
        "ru": "Привет, {name}! 🤖 Добро пожаловать в TREDIS AI.\nВаш тариф: <b>{tier}</b>{until}.\n\n{help}",
        "en": "Hi, {name}! 🤖 Welcome to TREDIS AI.\nYour plan: <b>{tier}</b>{until}.\n\n{help}",
    },
    "welcome_free": {
        "kk": "Сәлем, {name}! 🤖 TREDIS AI — курс бойынша AI көмекші.\n{free}\n\n{tiers}\n\n{help}",
        "ru": "Привет, {name}! 🤖 TREDIS AI — AI-помощник по курсу.\n{free}\n\n{tiers}\n\n{help}",
        "en": "Hi, {name}! 🤖 TREDIS AI is the course AI assistant.\n{free}\n\n{tiers}\n\n{help}",
    },
    "until": {"kk": ", {date} дейін", "ru": ", до {date}", "en": ", until {date}"},
    "help": {
        "kk": ("Не істей аламын:\n• Сабақ бойынша сұрақ — жай ғана жазыңыз\n"
               "• /pine &lt;сипаттама&gt; — Pine Script код жазу (Pro/VIP)\n"
               "• /setup &lt;мәтін&gt; — алерт баптауы, мыс.: «алтын, свип 15м, MSS 1м, тек шорт»\n"
               "• /lang — тілді ауыстыру"),
        "ru": ("Что я умею:\n• Вопрос по урокам — просто напишите\n"
               "• /pine &lt;описание&gt; — написать Pine Script (Pro/VIP)\n"
               "• /setup &lt;текст&gt; — настройки алертов, напр.: «золото, свип 15м, MSS 1м, только шорт»\n"
               "• /lang — сменить язык"),
        "en": ("What I can do:\n• Course questions — just type\n"
               "• /pine &lt;description&gt; — write Pine Script (Pro/VIP)\n"
               "• /setup &lt;text&gt; — alert settings, e.g. “gold, sweep 15m, MSS 1m, shorts only”\n"
               "• /lang — change language"),
    },
    "test_note": {"kk": "🧪 Тест режимі: төлем әзірге қабылданбайды. Тариф керек болса, админге жазыңыз.",
                  "ru": "🧪 Тестовый режим: оплата пока не принимается. Нужен тариф — напишите админу.",
                  "en": "🧪 Test mode: payments are not open yet. Ask an admin if you need a plan."},
    "tiers_head": {"kk": "💎 <b>Тарифтер</b>", "ru": "💎 <b>Тарифы</b>", "en": "💎 <b>Plans</b>"},
    "tiers_foot": {"kk": "Төлем үшін: {contact}", "ru": "Для оплаты: {contact}", "en": "To pay: {contact}"},
    "free_on": {"kk": "Тарифсіз: күніне {n} тегін сұрақ.", "ru": "Без тарифа: {n} бесплатных вопроса в день.",
                "en": "Without a plan: {n} free questions a day."},
    "free_off": {"kk": "AI көмекші төленген тарифтерде қолжетімді.", "ru": "AI-помощник доступен на платных тарифах.",
                 "en": "The AI assistant is available on paid plans."},
    "lim_msgs": {"kk": "күніне {n} хабарлама", "ru": "{n} сообщений в день", "en": "{n} messages a day"},
    "lim_code": {"kk": "айына {n} Pine код", "ru": "{n} Pine-кодов в месяц", "en": "{n} Pine scripts a month"},
    "lim_lifetime": {"kk": "алғашқы 7 күн Pro AI, кейін Start", "ru": "первые 7 дней как Pro AI, затем как Start",
                     "en": "Pro AI for the first 7 days, then Start"},
    "per_days": {"kk": " / {n} күн", "ru": " / {n} дн.", "en": " / {n} days"},
    "left_today": {"kk": "Бүгін қалды: {n}", "ru": "Осталось сегодня: {n}", "en": "Left today: {n}"},
    "code_left": {"kk": "Pine код осы айда: {n}", "ru": "Pine-кодов в этом месяце: {n}", "en": "Pine scripts this month: {n}"},
    "btn_pro": {"kk": "Pro AI-ға өту", "ru": "Перейти на Pro AI", "en": "Upgrade to Pro AI"},
    "limit_msgs": {
        "kk": "Бүгінгі хабарлама лимиті бітті ({limit}). Ертең жаңарады немесе тарифті көтеріңіз.",
        "ru": "Лимит сообщений на сегодня исчерпан ({limit}). Обновится завтра, или повысьте тариф.",
        "en": "Today's message limit is used up ({limit}). It resets tomorrow, or upgrade your plan.",
    },
    "limit_code_locked": {
        "kk": "Pine код жазу Pro AI және VIP тарифтерінде қолжетімді.",
        "ru": "Написание Pine-кода доступно на тарифах Pro AI и VIP.",
        "en": "Pine Script generation is available on Pro AI and VIP.",
    },
    "limit_code": {
        "kk": "Осы айдағы Pine код лимиті бітті ({limit}).",
        "ru": "Лимит Pine-кодов на этот месяц исчерпан ({limit}).",
        "en": "This month's Pine Script limit is used up ({limit}).",
    },
    "refused": {
        "kk": "Кешіріңіз, бұл сұраққа жауап бере алмаймын. Сұрақты басқаша қойып көріңіз.",
        "ru": "Извините, на этот вопрос я ответить не могу. Попробуйте сформулировать иначе.",
        "en": "Sorry, I can't answer that. Please try rephrasing.",
    },
    "truncated": {"kk": "…(жауап қысқартылды)", "ru": "…(ответ обрезан)", "en": "…(answer truncated)"},
    "ai_error": {
        "kk": "AI уақытша қолжетімсіз. Біраздан соң қайталаңыз. Лимит жұмсалмады.",
        "ru": "AI временно недоступен. Попробуйте позже. Лимит не списан.",
        "en": "AI is temporarily unavailable. Please try later. No limit was used.",
    },
    "alert_missing": {
        "kk": "Алерт #{id} табылмады.", "ru": "Алерт #{id} не найден.", "en": "Alert #{id} not found.",
    },
    "pine_usage": {"kk": "Мысал: /pine 15м таймфреймде FVG аймақтарын белгілейтін индикатор",
                   "ru": "Пример: /pine индикатор, который отмечает FVG на 15м",
                   "en": "Example: /pine indicator that marks FVG zones on 15m"},
    "setup_usage": {"kk": "Мысал: /setup алтын, свип 15м, MSS 1м, тек шорт",
                    "ru": "Пример: /setup золото, свип 15м, MSS 1м, только шорт",
                    "en": "Example: /setup gold, sweep 15m, MSS 1m, shorts only"},
    "setup_failed": {
        "kk": "Баптауларды түсіне алмадым. Нарықты және таймфреймді нақты жазыңыз.",
        "ru": "Не удалось распознать настройки. Укажите рынок и таймфрейм.",
        "en": "Couldn't parse the settings. Please name the market and timeframe.",
    },
    "setup_confirm": {
        "kk": "Баптауларды тексеріңіз:\n{s}\n\nСақтаймыз ба?",
        "ru": "Проверьте настройки:\n{s}\n\nСохранить?",
        "en": "Check the settings:\n{s}\n\nSave?",
    },
    "setup_fields": {
        "kk": "Нарық: {market}\nSweep TF: {sweep_tf}\nMSS TF: {mss_tf}\nБағыт: {direction}",
        "ru": "Рынок: {market}\nSweep TF: {sweep_tf}\nMSS TF: {mss_tf}\nНаправление: {direction}",
        "en": "Market: {market}\nSweep TF: {sweep_tf}\nMSS TF: {mss_tf}\nDirection: {direction}",
    },
    "btn_yes": {"kk": "Иә", "ru": "Да", "en": "Yes"},
    "btn_no": {"kk": "Жоқ", "ru": "Нет", "en": "No"},
    "setup_saved": {"kk": "✅ Сақталды.", "ru": "✅ Сохранено.", "en": "✅ Saved."},
    "setup_cancel": {"kk": "Болдырылмады.", "ru": "Отменено.", "en": "Cancelled."},
    "setup_expired": {"kk": "Баптау ескірді, /setup қайта жіберіңіз.",
                      "ru": "Настройки устарели, отправьте /setup ещё раз.",
                      "en": "These settings expired, send /setup again."},
    "lang_pick": {"kk": "Тілді таңдаңыз:", "ru": "Выберите язык:", "en": "Choose a language:"},
    "lang_set": {"kk": "Тіл: қазақша ✅", "ru": "Язык: русский ✅", "en": "Language: English ✅"},
    "not_admin": {"kk": "Бұл команда тек админдерге.", "ru": "Команда только для админов.", "en": "Admins only."},
}

TIER_NAME = {"none": "None (тарифсіз)", "start": "Start", "pro": "Pro AI", "vip": "VIP", "lifetime": "Lifetime"}


def t(key: str, lang: str, **kw) -> str:
    row = T[key]
    s = row.get(lang) or row["kk"]
    return s.format(**kw) if kw else s


def lang_from_tg(code) -> str:
    code = (code or "").lower()
    if code.startswith("ru"):
        return "ru"
    if code.startswith("en"):
        return "en"
    return "kk"
