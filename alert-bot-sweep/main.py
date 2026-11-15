import asyncio, hashlib, html, io, json, logging, os, re, secrets, sys
from collections import OrderedDict
from datetime import datetime
from typing import Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

from aiohttp import web
from telegram import (BotCommand, InlineKeyboardButton, InlineKeyboardMarkup,
                      LinkPreviewOptions, Update)
from telegram.constants import ParseMode
from telegram.error import BadRequest, NetworkError, RetryAfter, TelegramError, TimedOut
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

# ============================================================ CONFIG
# Токен тек айнымалыдан алынады (кодта сақталмайды).
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
# Бас админдер: үтірмен бөлінген Telegram ID-лер. Кейін ботта «👑 Бас админ ету» арқылы да қосылады.
OWNER_IDS = [int(x) for x in os.environ.get("OWNER_IDS", "").replace(" ", "").split(",") if x.strip().isdigit()]
# Бастапқы админдер: тек бірінші іске қосылғанда қосылады (кейін бас админ өзгерте алады).
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x.strip().isdigit()]
PLACEHOLDER_NAMES = ("Бас админ", "Админ")
_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
PUBLIC_BASE_URL = (os.environ.get("PUBLIC_BASE_URL") or (f"https://{_domain}" if _domain else "http://localhost:5002")).rstrip("/")
DATA_DIR = os.environ.get("DATA_DIR", ".")
PORT = int(os.environ.get("PORT", "5002"))
# Вебхук қорғанысы: TradingView-дің ресми IP-лері (https://www.tradingview.com/support/solutions/43000529348).
TV_IPS = {s.strip() for s in os.environ.get("TV_IPS", "52.89.214.238,34.212.75.30,54.218.53.128,52.32.178.7").split(",") if s.strip()}
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()   # қосымша: /webhook/<secret> де қабылданады
WEBHOOK_OPEN = os.environ.get("WEBHOOK_OPEN") == "1"            # тек тест үшін: IP тексерісін өшіреді

# Негізгі дерек FOREXCOM. Басқа брокер дерегі "СИМВОЛ_БИРЖА" кілтімен бөлек нарық болады.
MARKETS = ["XAUUSD", "XAUUSD_OANDA", "XAUEUR", "BTCUSD", "XAGUSD", "GBPUSD", "EURUSD", "EURUSD_OANDA",
           "GER40", "AUDUSD", "USDJPY", "CADJPY"]
TFS = ["12", "15", "20", "30", "45", "60", "240", "D"]
TZ = ZoneInfo("Asia/Almaty")
PAGE = 8

DEFAULTS = {
    "indicator_link": os.environ.get("INDICATOR_LINK", "").strip(),   # бас админ ботта өзгерте алады
    "send_image": "1",
    "txt_welcome": "Сәлеметсіз бе! GENESIS SWEEP ботына қош келдіңіз.\n\nӨтініш жіберу үшін аты-жөніңізді жазыңыз:",
    "txt_approved": ("🎉 GENESIS SWEEP курсына қош келдіңіз, {name}!\n\n"
                     "GENESIS SWEEP — свеча фракталды фитильмен алып, кері жабылған сәтті (sweep) тауып, "
                     "Entry, Stop, TP 1 және TP 2 деңгейлерін көрсететін индикатор.\n\n"
                     "📎 Индикатор сілтемесі (БІР РЕТ жұмыс істейді):\n{link}\n\n"
                     "Доступ ашу үшін TradingView юзернейміңізді осы чатқа жазыңыз.\n"
                     "Табу жолы: TradingView → оң жақ жоғарыдағы профиль суреті → профиль бетіндегі @-тан кейінгі ат."),
    "txt_granted": "🎉 Құттықтаймыз, {name}! TradingView-де индикаторға доступ ашылды.\nЕнді нарықтар мен таймфреймдерді таңдаңыз.",
    "txt_rejected": "Кешіріңіз, өтінішіңіз қабылданбады.",
}
LABELS = {
    "indicator_link": "🔗 Индикатор сілтемесі",
    "txt_welcome": "👋 /start мәтіні",
    "txt_approved": "✅ Қабылдау мәтіні  ({name}, {link})",
    "txt_granted": "🎉 Доступ ашылғанда  ({name})",
    "txt_rejected": "❌ Қабылдамау мәтіні",
}
ICON = {"pending": "⏳", "approved": "📨", "awaiting_tv": "🔑", "active": "🟢", "removed": "⚫️", "rejected": "🔴"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)   # әйтпесе токен логқа URL ішінде жазылады
log = logging.getLogger("sweep")
tg_app: Optional[Application] = None
bg_tasks: set = set()
seen: "OrderedDict[str, bool]" = OrderedDict()

# ============================================================ STORAGE
users: dict = {}
prefs: dict = {}
settings: dict = {}
tokens: dict = {}


def _p(n): return os.path.join(DATA_DIR, n)


def rj(n, d):
    try:
        with open(_p(n), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return d
    except Exception as e:
        log.error("read %s: %s", n, e)
        return d


def wj(n, data):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = _p(n) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _p(n))
    except Exception as e:
        log.error("write %s: %s", n, e)


def save_users(): wj("users.json", users)
def save_prefs(): wj("prefs.json", prefs)
def save_settings(): wj("settings.json", settings)
def save_tokens(): wj("tokens.json", tokens)


def cfg(k): return settings.get(k, DEFAULTS[k])
def now_str(): return datetime.now(TZ).strftime("%d.%m.%Y %H:%M")
def esc(x): return html.escape(str(x)) if x not in (None, "") else "—"


def owner_ids():
    return {int(x) for x in settings.get("owners", OWNER_IDS)}


def set_owners(ids):
    settings["owners"] = sorted({int(x) for x in ids})
    save_settings()


def fill(t, **kw):
    for k, v in kw.items():
        t = t.replace("{" + k + "}", str(v))
    return t


def tfn(tf):
    tf = str(tf)
    if tf.upper() in ("D", "1D", "1440"):
        return "1Д"
    if tf.isdigit():
        n = int(tf)
        return f"{n // 60}Ч" if n >= 60 and n % 60 == 0 else f"{n}м"
    return tf


def mlabel(m):
    m = str(m)
    if "_" in m:
        sym, ex = m.split("_", 1)
        return f"{sym} ({ex})"
    return m


def market_key(symbol, tickerid=""):
    sym = str(symbol).split(":")[-1].upper()
    tid = str(tickerid or "")
    ex = tid.split(":")[0].upper() if ":" in tid else ""
    k = f"{sym}_{ex}"
    return k if k in MARKETS else sym


def tf_en(tf):
    tf = str(tf)
    if tf.upper() in ("D", "1D", "1440"):
        return "1D"
    if tf.isdigit():
        n = int(tf)
        return f"{n // 60}H" if n >= 60 and n % 60 == 0 else f"{n}m"
    return tf


def U(uid): return users.get(str(uid))
def is_owner(uid): return int(uid) in owner_ids()


def is_admin(uid):
    u = U(uid)
    return is_owner(uid) or bool(u and u.get("admin") and u.get("status") == "active")


def admin_mode(uid):
    u = U(uid)
    return is_admin(uid) and not (u or {}).get("as_user")


def admin_ids():
    s = set(owner_ids())
    s.update(int(k) for k, u in users.items() if u.get("admin") and u.get("status") == "active")
    return s


def P(uid):
    p = prefs.setdefault(str(uid), {})
    p.setdefault("markets", ["XAUUSD"])
    p.setdefault("tfs", ["60", "240"])
    p.setdefault("notify", True)
    return p


def ordered(items, universe):
    return [x for x in universe if x in set(items)]


def seed_admins():
    if settings.get("admins_seeded"):
        return
    for aid in ADMIN_IDS:
        if str(aid) not in users:
            users[str(aid)] = {"name": "Админ", "tg": None, "tv": None, "status": "active", "admin": True}
    settings["admins_seeded"] = True
    save_settings()
    save_users()


def ensure_owner_records():
    changed = False
    for oid in owner_ids():
        u = users.get(str(oid))
        if not u:
            users[str(oid)] = {"name": "Бас админ", "tg": None, "tv": None, "status": "active", "admin": True}
            changed = True
        elif u.get("status") != "active" or not u.get("admin"):
            u["status"], u["admin"] = "active", True
            changed = True
    if changed:
        save_users()


# ============================================================ UI HELPERS
def kb(rows):
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d) for t, d in r] for r in rows])


CANCEL_KB = lambda: kb([[("✖️ Бас тарту", "x")]])


async def edit(q, text, markup=None, html_mode=True):
    try:
        await q.edit_message_text(text, reply_markup=markup,
                                  parse_mode=ParseMode.HTML if html_mode else None,
                                  link_preview_options=LinkPreviewOptions(is_disabled=True))
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            log.warning("edit fail: %s", e)


async def tg_retry(fn, tries=4):
    """Telegram-ға желі үзілсе немесе лимит болса, бірнеше рет қайталап көреді."""
    for i in range(tries):
        try:
            return await fn()
        except RetryAfter as e:
            if i == tries - 1:
                raise
            await asyncio.sleep(float(getattr(e, "retry_after", 1)) + 0.5)
        except (TimedOut, NetworkError) as e:
            if isinstance(e, BadRequest) or i == tries - 1:
                raise
            await asyncio.sleep(1.5 * (i + 1))


async def send(bot, uid, text, markup=None, **kw):
    pm = kw.pop("parse_mode", None)
    try:
        await tg_retry(lambda: bot.send_message(chat_id=uid, text=text, reply_markup=markup, parse_mode=pm,
                                                link_preview_options=LinkPreviewOptions(is_disabled=True), **kw))
        return True
    except TelegramError as e:
        log.info("send fail %s: %s", uid, e)
        return False


def toggle_rows(items, chosen, prefix, back, labeler=lambda x: x):
    rows, row = [], []
    for it in items:
        row.append((("✅ " if it in chosen else "▫️ ") + labeler(it), f"{prefix}:{it}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([("⬅️ Артқа", back)])
    return rows


# ============================================================ USER MENU
def tf_list(tfs): return ", ".join(tfn(t) for t in tfs) or "—"


def menu_text(uid):
    p = P(uid)
    warn = "" if (p["markets"] and p["tfs"]) else "\n⚠️ Нарық немесе таймфрейм таңдалмаған, хабар келмейді."
    return ("⚙️ <b>Баптау · GENESIS SWEEP</b>\n"
            "Свеча фракталды фитильмен алып, алдыңғы свечаның шетін де алып, кері жабылса, келесі свеча "
            "ашылғанда Entry, Stop, TP 1 және TP 2 деңгейлерімен хабар келеді.\n\n"
            f"Нарықтар: {', '.join(mlabel(m) for m in p['markets']) or '—'}\n"
            f"Таймфреймдер: {tf_list(p['tfs'])}\n"
            f"Хабар: {'🟢 қосулы' if p['notify'] else '⚪️ өшірулі'}{warn}")


def menu_kb(uid):
    p = P(uid)
    return kb([
        [("📊 Нарықтар", "m:mk"), ("🕒 Таймфреймдер", "m:tf")],
        [("🔕 Хабарды өшіру" if p["notify"] else "🔔 Хабарды қосу", "m:nt")],
        [("🧪 Тест хабар", "m:test")],
    ])


def market_rows(chosen):
    rows = toggle_rows(MARKETS, chosen, "mt", "m:home", mlabel)
    rows.insert(-1, [("✅ Барлығы", "mt:*"), ("▫️ Тазалау", "mt:-")])
    return rows


async def show_menu(bot, uid, q=None):
    if q:
        await edit(q, menu_text(uid), menu_kb(uid))
    else:
        await send(bot, uid, menu_text(uid), menu_kb(uid), parse_mode=ParseMode.HTML)


# ============================================================ ONE-TIME LINKS
def make_link(uid):
    for t in [t for t, e in tokens.items() if e["uid"] == uid and not e["used"]]:
        del tokens[t]
    t = secrets.token_urlsafe(18)
    tokens[t] = {"uid": uid, "used": False, "at": now_str()}
    save_tokens()
    return f"{PUBLIC_BASE_URL}/link/{t}"


def revoke_links(uid):
    for t in [t for t, e in tokens.items() if e["uid"] == uid and not e["used"]]:
        del tokens[t]
    save_tokens()


def link_state(uid):
    mine = [e for e in tokens.values() if e["uid"] == uid]
    if any(not e["used"] for e in mine):
        return "жіберілген, әлі ашылмаған"
    return "ашылған" if mine else "жіберілмеген"


# ============================================================ ADMIN PANEL VIEWS
def admin_kb(uid):
    rows = [[("👥 Қолданушылар", "a:users:0"), ("⏳ Күтіп тұрғандар", "a:pend:0")],
            [("📊 Статистика", "a:stats"), ("📣 Хабар тарату", "a:bc")]]
    if is_owner(uid):
        rows += [[("🔗 Индикатор сілтемесі" + ("" if cfg("indicator_link") else " ⚠️"), "ed:indicator_link")],
                 [("✉️ Хабарлама мәтіндері", "a:cfg")],
                 [("🖼 Сурет: " + ("қосулы" if cfg("send_image") == "1" else "өшірулі"), "a:img")],
                 [("🛡 Админдер", "a:admins")]]
    rows.append([("👤 Қолданушы ретінде кіру", "a:asuser")])
    return kb(rows)


def admin_title(uid=None):
    t = "🛠 <b>Админ панелі · GENESIS SWEEP</b>\n\nҚолданушы режимінен қайту үшін /admin жазыңыз."
    if not cfg("indicator_link"):
        if uid is not None and is_owner(uid):
            t += "\n\n⚠️ Индикатор сілтемесі әлі қойылмаған: «🔗 Индикатор сілтемесі» батырмасын басыңыз."
        else:
            t += "\n\n⚠️ Индикатор сілтемесін бас админ әлі қоймаған."
    return t


def users_view(page, pending_only=False):
    flt = (lambda u: u["status"] in ("pending", "awaiting_tv")) if pending_only else (lambda u: True)
    items = [(k, u) for k, u in users.items() if flt(u)]
    items.sort(key=lambda x: (x[1]["status"] not in ("pending", "awaiting_tv"), x[1].get("name") or ""))
    pages = max(1, (len(items) + PAGE - 1) // PAGE)
    page = min(max(page, 0), pages - 1)
    pre = "pend" if pending_only else "users"
    rows = []
    for k, u in items[page * PAGE:(page + 1) * PAGE]:
        icon = "👑" if is_owner(int(k)) else ("🛡" if u.get("admin") else ICON.get(u["status"], "•"))
        rows.append([(f"{icon} {(u.get('name') or '—')[:24]}", f"uc:{k}")])
    nav = []
    if page > 0:
        nav.append(("◀️", f"a:{pre}:{page - 1}"))
    if page < pages - 1:
        nav.append(("▶️", f"a:{pre}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([("⬅️ Панель", "a:home")])
    title = "⏳ Күтіп тұрғандар" if pending_only else "👥 Қолданушылар"
    return f"{title}: {len(items)} ({page + 1}/{pages})", kb(rows)


def card(uid):
    u = U(uid)
    role = "👑 бас админ" if is_owner(uid) else ("🛡 админ" if u.get("admin") else "қолданушы")
    return (f"<b>{esc(u['name'])}</b>\nTelegram: @{esc(u['tg'])}\nTradingView: {esc(u['tv'])}\n"
            f"Статус: {ICON.get(u['status'], '')} {esc(u['status'])}\nРөлі: {role}\n"
            f"Сілтеме: {link_state(uid)}\nID: <code>{uid}</code>")


def card_kb(viewer, uid):
    u = U(uid)
    rows = []
    if u["status"] == "pending":
        rows.append([("✅ Қабылдау", f"ap:{uid}"), ("❌ Қабылдамау", f"rj:{uid}")])
    if u["status"] == "awaiting_tv":
        rows.append([("✅ Ашылды", f"ok:{uid}"), ("⚠️ Қате юзернейм", f"bad:{uid}")])
    if u["status"] in ("approved", "awaiting_tv", "active"):
        rows.append([("🔗 Жаңа бір реттік сілтеме", f"ln:{uid}")])
    if u["status"] == "active" and not is_owner(uid):
        rows.append([("🗑 Өшіру", f"udc:{uid}")])
    if u["status"] in ("removed", "rejected"):
        rows.append([("♻️ Қайта қосу", f"ur:{uid}")])
    if is_owner(viewer) and int(viewer) != int(uid):
        if is_owner(uid):
            rows.append([("👑 Бас админдіктен алу", f"uod:{uid}")])
        else:
            rows.append([("🛡 Админдіктен алу" if u.get("admin") else "🛡 Админ ету", f"ua:{uid}")])
            if u["status"] == "active":
                rows.append([("👑 Бас админ ету", f"uo:{uid}")])
    rows.append([("⬅️ Тізім", "a:users:0")])
    return kb(rows)


# ============================================================ ACCESS FLOW
async def show_home(bot, uid, q=None):
    if admin_mode(uid):
        if q:
            await edit(q, admin_title(uid), admin_kb(uid))
        else:
            await send(bot, uid, admin_title(uid), admin_kb(uid), parse_mode=ParseMode.HTML)
    else:
        await show_menu(bot, uid, q)


def remember_tg(u, tu):
    """Алдын ала қосылған (бас) админ жазбасына Telegram аты мен юзернеймін бірінші кіргенде толтыру."""
    changed = False
    if tu.username and u.get("tg") != tu.username:
        u["tg"] = tu.username
        changed = True
    if u.get("name") in (None, "", *PLACEHOLDER_NAMES) and tu.full_name:
        u["name"] = tu.full_name
        changed = True
    return changed


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    context.user_data.clear()
    u = U(uid)
    if is_owner(uid):
        ensure_owner_records()
        u = U(uid)
    if u and u.get("admin") and remember_tg(u, update.effective_user):
        save_users()
    if not u:
        context.user_data["await_name"] = True
        await update.message.reply_text(cfg("txt_welcome"))
        return
    st = u["status"]
    if st == "pending":
        await update.message.reply_text("Өтінішіңіз админге жіберілді, растауды күтіңіз ⏳")
    elif st == "approved":
        await update.message.reply_text("TradingView юзернейміңізді жіберіңіз (мысалы: dosjan_t).")
    elif st == "awaiting_tv":
        await update.message.reply_text("TradingView доступын ашуды күтіңіз ⏳")
    elif st == "active":
        await show_home(context.bot, uid)
    elif st == "rejected":
        context.user_data["await_name"] = True
        await update.message.reply_text("Өтінішті қайта жібересіз бе? Аты-жөніңізді жазыңыз:")
    else:
        await update.message.reply_text("Кешіріңіз, сізге доступ жабық.")


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    context.user_data.clear()
    if is_owner(uid):
        ensure_owner_records()
    u = U(uid)
    if u:
        u["as_user"] = False
        remember_tg(u, update.effective_user)
        save_users()
    await update.message.reply_text(admin_title(uid), reply_markup=admin_kb(uid), parse_mode=ParseMode.HTML)


TV_RE = re.compile(r"^@?([A-Za-z0-9_\-.]{3,40})$")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = (update.message.text or "").strip()
    ud = context.user_data

    key = ud.get("edit_key")
    if key and is_owner(uid):
        if key == "indicator_link" and not text.startswith("http"):
            await update.message.reply_text("Сілтеме http:// немесе https:// деп басталуы керек.", reply_markup=CANCEL_KB())
            return
        settings[key] = text
        save_settings()
        ud.clear()
        await update.message.reply_text(f"✅ Сақталды: {LABELS[key]}",
                                        reply_markup=kb([[("⬅️ Панель", "a:home")]]))
        return

    if ud.get("bc") and is_admin(uid):
        ud.pop("bc")
        ud["bc_text"] = text
        await update.message.reply_text("Мына хабар барлық белсенді қолданушыға жіберіледі:\n\n" + text,
                                        reply_markup=kb([[("✅ Жіберу", "bcy"), ("✖️ Бас тарту", "x")]]))
        return

    if ud.get("await_name"):
        if len(text) < 3:
            await update.message.reply_text("Аты-жөніңізді толық жазыңыз.")
            return
        ud.clear()
        tu = update.effective_user
        users[str(uid)] = {"name": text, "tg": tu.username, "tv": None, "status": "pending", "admin": False}
        save_users()
        await update.message.reply_text("Рақмет! Өтінішіңіз админге жіберілді, растауды күтіңіз ⏳")
        for a in admin_ids():
            await send(context.bot, a,
                       f"🆕 Жаңа өтініш\nАты: {esc(text)}\nTelegram: @{esc(tu.username)}\nID: <code>{uid}</code>",
                       kb([[("✅ Қабылдау", f"ap:{uid}"), ("❌ Қабылдамау", f"rj:{uid}")]]),
                       parse_mode=ParseMode.HTML)
        return

    u = U(uid)
    if not u:
        await update.message.reply_text("/start басыңыз")
        return
    st = u["status"]
    if st == "approved":
        m = TV_RE.match(text)
        if not m:
            await update.message.reply_text("Юзернейм дұрыс емес сияқты. Тек латын әріптер, цифрлар, _ . - (мысалы: dosjan_t)")
            return
        u["tv"] = m.group(1)
        u["status"] = "awaiting_tv"
        save_users()
        await update.message.reply_text(f"Рақмет! TradingView юзернейміңіз: {u['tv']}\nДоступ ашылған соң хабарлаймыз ⏳")
        for a in admin_ids():
            await send(context.bot, a,
                       f"🔑 Доступ сұранысы\n{esc(u['name'])} (@{esc(u['tg'])})\nTradingView: <code>{esc(u['tv'])}</code>\n\n"
                       "TradingView → индикатор → Manage access → осы юзернеймді қосыңыз.",
                       kb([[("✅ Ашылды", f"ok:{uid}"), ("⚠️ Қате юзернейм", f"bad:{uid}")]]),
                       parse_mode=ParseMode.HTML)
    elif st == "active":
        await show_home(context.bot, uid)
    elif st == "pending":
        await update.message.reply_text("Өтінішіңіз қаралуда, күтіңіз ⏳")
    elif st == "awaiting_tv":
        await update.message.reply_text("Доступ ашылуын күтіңіз ⏳")
    else:
        await update.message.reply_text("Кешіріңіз, сізге доступ жабық.")


async def do_approve(bot, uid):
    u = U(uid)
    if not u or u["status"] != "pending":
        return "⚠️ Бұрын өңделген."
    u["status"] = "approved"
    save_users()
    link = make_link(uid)
    ok = await send(bot, uid, fill(cfg("txt_approved"), name=u["name"], link=link), protect_content=True)
    res = "✅ Қабылданды" + ("" if ok else " (⚠️ хабар жіберілмеді)")
    if not cfg("indicator_link"):
        res += "\n⚠️ Индикатор сілтемесі әлі қойылмаған, сілтеме ашылмайды. Админ панелі → 🔗 Индикатор сілтемесі."
    return res


async def do_reject(bot, uid):
    u = U(uid)
    if not u:
        return "⚠️ Табылмады."
    u["status"] = "rejected"
    save_users()
    await send(bot, uid, fill(cfg("txt_rejected"), name=u["name"]))
    return "❌ Қабылданбады"


async def do_granted(bot, uid):
    u = U(uid)
    if not u or u["status"] != "awaiting_tv":
        return "⚠️ Бұрын өңделген."
    u["status"] = "active"
    save_users()
    await send(bot, uid, fill(cfg("txt_granted"), name=u["name"]))
    await show_menu(bot, uid)
    return "✅ Ашылды"


async def do_bad_tv(bot, uid):
    u = U(uid)
    if not u:
        return "⚠️ Табылмады."
    u["status"] = "approved"
    save_users()
    await send(bot, uid, "TradingView юзернеймі табылмады. Қайта тексеріп, дұрыс юзернеймді жіберіңіз.")
    return "⚠️ Қате юзернейм"


async def do_remove(bot, uid, by):
    u = U(uid)
    if not u or is_owner(uid):
        return "⚠️ Болмайды."
    if u.get("admin") and not is_owner(by):
        return "⚠️ Админді тек бас админ өшіре алады."
    u["status"] = "removed"
    u["admin"] = False
    revoke_links(uid)
    save_users()
    await send(bot, uid, "Сізге доступ жабылды.")
    return "🗑 Өшірілді. TradingView-де де доступты қолмен алып тастаңыз."


# ============================================================ HELPERS FOR SIGNALS
def fp(v):
    try:
        x = float(v)
    except Exception:
        return "—"
    s = f"{x:.5f}".rstrip("0")
    if len(s.split(".")[1]) < 2:
        s = f"{x:.2f}"
    return s


def num(d, k):
    try:
        return float(d.get(k))
    except Exception:
        return None


# ============================================================ GENESIS SWEEP: TEXT + IMAGE
SWEEP_TEST = {"src": "SWEEP", "symbol": "XAUUSD", "tickerid": "FOREXCOM:XAUUSD", "tf": "60", "dir": "SHORT",
              "entry": "4176.40", "sweep": "4182.10", "sl": "4185.30", "tp1": "4171.95", "tp2": "4165.20",
              "c1h": "4178.70", "c1l": "4165.20", "c2h": "4185.30", "c2l": "4174.80", "time": "тест"}


def norm_tf(tf):
    tf = str(tf).upper()
    return "D" if tf in ("D", "1D", "1440") else tf


def ts_str(v):
    if v in (None, ""):
        return ""
    try:
        return datetime.fromtimestamp(int(float(v)), TZ).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(v)


def rr(entry, sl, tp, short):
    if None in (entry, sl, tp):
        return None
    risk = (sl - entry) if short else (entry - sl)
    gain = (entry - tp) if short else (tp - entry)
    if risk <= 0 or gain <= 0:
        return None
    return gain / risk


def build_sweep_text(d, with_note):
    sym = esc(mlabel(d.get("market") or d.get("symbol")))
    short = d.get("dir") == "SHORT"
    tf = tfn(d.get("tf"))
    e, sl, sw = num(d, "entry"), num(d, "sl"), num(d, "sweep")
    tp1, tp2 = num(d, "tp1"), num(d, "tp2")
    r1, r2 = rr(e, sl, tp1, short), rr(e, sl, tp2, short)
    dir_line = ("🔴 Бағыт: <b>SHORT</b> (баға төмен қарай күтіледі)" if short
                else "🟢 Бағыт: <b>LONG</b> (баға жоғары қарай күтіледі)")
    if short:
        what = (f"{sym} нарығында <b>{tf}</b> таймфреймде жоғарғы фрактал {fp(sw)} алынды: свеча деңгейден "
                f"фитильмен асып, алдыңғы свечаның хайын да алды (лоуын алмады) және деңгейдің астына жабылды.")
    else:
        what = (f"{sym} нарығында <b>{tf}</b> таймфреймде төменгі фрактал {fp(sw)} алынды: свеча деңгейден "
                f"фитильмен түсіп, алдыңғы свечаның лоуын да алды (хайын алмады) және деңгейдің үстіне жабылды.")
    what += "\nКелесі свеча ашылды, Entry соның ашылу бағасы."
    items = [("Stop", sl), ("Sweep деңгейі", sw), ("Entry", e), ("TP 1", tp1 if r1 else None), ("TP 2", tp2)]
    items = [(n, v) for n, v in items if v is not None]
    items.sort(key=lambda x: -x[1])
    lines = "\n".join(f"{n}: <code>{fp(v)}</code>" for n, v in items)
    rr_parts = [f"TP {i} ≈ 1:{r:.1f}" for i, r in ((1, r1), (2, r2)) if r]

    tid = d.get("tickerid") or d.get("symbol")
    url = f"https://www.tradingview.com/chart/?symbol={quote(str(tid))}&interval={quote(norm_tf(d.get('tf')))}"
    link = f'📈 <a href="{html.escape(url)}">{sym} графигін ашу ({tf})</a>'

    parts = [f"💧 <b>GENESIS SWEEP · {sym} · {tf}</b>", dir_line, "", what, "", "Деңгейлер (жоғарыдан төмен):", lines]
    if rr_parts:
        parts.append("RR: " + " · ".join(rr_parts))
    if tp1 is not None and not r1:
        parts.append("<i>TP 1 кіру бағасының ар жағында қалды, сондықтан көрсетілмеді.</i>")
    parts += ["", link]
    if with_note:
        parts += ["", "<i>Суреттегі свечалар схема ретінде салынған. Деңгейлер нақты, сандары жоғарыдағы тізімде.</i>"]
    t = ts_str(d.get("time"))
    if t:
        parts.append(esc(t))
    return "\n".join(parts)


def draw_sweep(d):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    try:
        return _draw_sweep(d, Image, ImageDraw, ImageFont)
    except Exception:
        log.exception("sweep draw failed")
        return None


def _draw_sweep(d, Image, ImageDraw, ImageFont):
    short = d.get("dir") == "SHORT"
    s = 1 if short else -1
    E, SL, LV = num(d, "entry"), num(d, "sl"), num(d, "sweep")
    T1, T2 = num(d, "tp1"), num(d, "tp2")
    if None in (E, SL, LV, T2):
        return None
    c1n = num(d, "c1h" if short else "c1l")      # 1-свечаның стоп жағындағы шеті
    c2x = num(d, "c2h" if short else "c2l")      # 2-свечаның (манипуляция) стоп жағындағы шеті

    # a-кеңістік: a = s*(баға - Entry). Оң жағы = Stop жағы, теріс жағы = TP жағы
    def a(p): return s * (p - E)
    def price(v): return E + s * v

    top, bot = a(LV), a(T2)
    D = top - bot
    if D <= 0:
        D = max(abs(a(SL)), abs(E) * 1e-4, 1e-6)
        bot = top - D
    aC1 = a(c1n) if c1n is not None else (top + bot) / 2
    aC1 = min(max(aC1, bot + 0.2 * D), top)
    aC2 = max(a(c2x) if c2x is not None else a(SL), top + 0.02 * D)
    r1 = aC1 - bot
    c1o, c1c = bot + 0.15 * r1, aC1 - 0.12 * r1
    # (open, close, stop-жақ шеті, TP-жақ шеті)
    cs = [
        (bot + 0.15 * D, bot + 0.45 * D, bot + 0.55 * D, bot + 0.05 * D),
        (bot + 0.45 * D, top - 0.20 * D, top - 0.12 * D, bot + 0.40 * D),
        (top - 0.20 * D, top - 0.40 * D, top, top - 0.45 * D),                  # 2: фрактал
        (top - 0.40 * D, bot + 0.30 * D, top - 0.32 * D, bot + 0.22 * D),
        (bot + 0.30 * D, bot + 0.12 * D, bot + 0.40 * D, bot + 0.04 * D),
        (c1o, c1c, aC1, bot),                                                    # 5: 1-свеча
        (c1c, 0.0, aC2, min(c1c, 0.0) - 0.08 * D),                               # 6: 2-свеча (sweep)
        (0.0, 0.55 * bot, 0.06 * D, 0.55 * bot - 0.06 * D),                      # 7: 3-свеча (Entry)
    ]
    cp = []
    for (o, c_, h_, l_) in cs:
        p1, p2 = price(h_), price(l_)
        cp.append((price(o), price(c_), max(p1, p2), min(p1, p2)))

    tp1_ok = rr(E, SL, T1, short) is not None
    allp = [x for c in cp for x in c] + [SL, LV, E, T2] + ([T1] if tp1_ok else [])
    hi, lo = max(allp), min(allp)
    pad = (hi - lo) * 0.08 or 1.0
    hi += pad
    lo -= pad

    W, H, T, B = 980, 640, 100, 30
    img = Image.new("RGB", (W, H), (255, 255, 255))
    dr = ImageDraw.Draw(img)

    def font(sz):
        try:
            return ImageFont.load_default(size=sz)
        except TypeError:
            return ImageFont.load_default()
    fT, fM, fS, fL = font(26), font(17), font(14), font(18)

    def y(p): return T + (hi - p) / (hi - lo) * (H - T - B)
    def x(i): return 70 + i * 72

    GRN, RED = (8, 153, 129), (242, 54, 69)
    DARK, GRAYT, GRID = (54, 58, 69), (95, 95, 105), (238, 238, 242)
    side_c = RED if short else GRN
    x_end = x(7) + 170

    for k in range(1, 6):
        yy = T + k * (H - T - B) / 6
        dr.line([40, yy, W - 20, yy], fill=GRID, width=1)

    # Свечалар
    for i, (po, pc, ph, pl) in enumerate(cp):
        cx = x(i)
        col = GRN if pc >= po else RED
        dr.line([cx, y(ph), cx, y(pl)], fill=col, width=2)
        t_, b_ = y(max(po, pc)), y(min(po, pc))
        if b_ - t_ < 3:
            b_ = t_ + 3
        dr.rectangle([cx - 16, t_, cx + 16, b_], fill=col)

    # Sweep деңгейі (фракталдан 2-свечаға дейін)
    yl = y(LV)
    dr.line([x(2), yl, x(6), yl], fill=DARK, width=2)
    tw = dr.textlength("SWEEP", font=fL)
    dr.text(((x(2) + x(6)) / 2 - tw / 2, yl - 26 if short else yl + 6), "SWEEP", fill=GRAYT, font=fL)

    def dotted(x1, x2, yy, col):
        xx = x1
        while xx < x2:
            dr.line([xx, yy, min(xx + 8, x2), yy], fill=col, width=2)
            xx += 14

    levels = [(T2, f"TP2  {fp(T2)}", DARK, x(5), False)]
    if tp1_ok:
        levels.append((T1, f"TP1  {fp(T1)}", DARK, x(5), False))
    levels += [(E, f"ENTRY  {fp(E)}", side_c, x(7), True), (SL, f"STOP  {fp(SL)}", RED, x(6), False)]
    for p, _, col, xs, dot in levels:
        if dot:
            dotted(xs, x_end, y(p), col)
        else:
            dr.line([xs, y(p), x_end, y(p)], fill=col, width=1)
    # Жазулар бір-бірін баспауы үшін
    tags = sorted([(y(p), t, col) for p, t, col, _, _ in levels])
    last = -1e9
    for yy, t, col in tags:
        yy = max(yy, last + 22)
        dr.text((x_end + 10, yy - 10), t, fill=col, font=fM)
        last = yy

    # SELL / BUY белгісі
    tag = "SELL" if short else "BUY"
    tw = dr.textlength(tag, font=fM)
    bx = x(7)
    by = y(cp[7][2]) - 40 if short else y(cp[7][3]) + 12
    dr.rounded_rectangle([bx - tw / 2 - 10, by, bx + tw / 2 + 10, by + 28], radius=5, fill=side_c)
    dr.text((bx - tw / 2, by + 5), tag, fill=(255, 255, 255), font=fM)

    title = f"{mlabel(d.get('market') or d.get('symbol'))}  |  {'SHORT' if short else 'LONG'}  |  Sweep {tf_en(d.get('tf'))}"
    dr.text((24, 22), title, fill=(20, 20, 20), font=fT)
    dr.text((24, 60), "Schematic candles, real levels", fill=(150, 150, 150), font=fS)

    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# ============================================================ DELIVERY / ROUTING
async def deliver(uid, d, png):
    bot = tg_app.bot
    text = build_sweep_text(d, with_note=bool(png))
    plain = html.unescape(re.sub(r"<[^>]+>", "", text))
    try:
        if png:
            if len(plain) <= 1000:
                await tg_retry(lambda: bot.send_photo(chat_id=uid, photo=png, caption=text, parse_mode=ParseMode.HTML))
                return True
            await tg_retry(lambda: bot.send_photo(chat_id=uid, photo=png))
        await tg_retry(lambda: bot.send_message(chat_id=uid, text=text, parse_mode=ParseMode.HTML,
                                                link_preview_options=LinkPreviewOptions(is_disabled=True)))
        return True
    except Exception as e:
        log.warning("deliver %s: %s", uid, e)
        try:
            await tg_retry(lambda: bot.send_message(chat_id=uid, text=build_sweep_text(d, with_note=False),
                                                    parse_mode=ParseMode.HTML,
                                                    link_preview_options=LinkPreviewOptions(is_disabled=True)))
            return True
        except Exception as e2:
            log.warning("deliver failed %s: %s", uid, e2)
            return False


def receivers(want):
    out = []
    for k, u in users.items():
        if u.get("status") != "active":
            continue
        if is_admin(int(k)) and not u.get("as_user"):
            continue
        p = P(k)
        if p["notify"] and want(p):
            out.append(int(k))
    return out


async def route(d):
    mk = d.get("market") or d["symbol"]
    targets = receivers(lambda p: mk in p["markets"] and d["tf"] in p["tfs"])
    if not targets:
        return
    png = await asyncio.to_thread(draw_sweep, d) if cfg("send_image") == "1" else None
    ok = 0
    for t in targets:
        ok += bool(await deliver(t, d, png))
        await asyncio.sleep(0.04)
    log.info("signal %s %s %s: delivered %d/%d", mk, d["tf"], d["dir"], ok, len(targets))


async def process(d):
    try:
        base = {k: v for k, v in d.items() if k != "events"}
        items = d["events"] if isinstance(d.get("events"), list) else [d]
        for it in items:
            if not isinstance(it, dict):
                continue
            x = {**base, **it}
            if not all(k in x for k in ("symbol", "tf", "dir", "entry", "sl")):
                continue
            x["tf"] = norm_tf(x["tf"])
            x["dir"] = str(x["dir"]).upper()
            x["symbol"] = str(x["symbol"]).split(":")[-1].upper()
            x["market"] = market_key(x["symbol"], x.get("tickerid"))
            # Қайталанудан қорғау кілті сигналдың өзінен құралады, alert уақыты (time) кірмейді:
            # TradingView бір сигналды келесі свечада ескі деңгейлермен қайта жіберсе, ол өтпеуі керек.
            ident = [x["market"], x["tf"], x["dir"]] + [fp(x.get(k)) for k in ("entry", "sl", "tp1", "tp2", "sweep")]
            key = hashlib.sha1("|".join(ident).encode()).hexdigest()
            if key in seen:
                log.info("duplicate signal skipped: %s", " ".join(ident))
                continue
            seen[key] = True
            while len(seen) > 3000:
                seen.popitem(last=False)
            await route(x)
    except Exception:
        log.exception("process failed")


# ============================================================ CALLBACKS
async def on_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    bot = context.bot
    parts = q.data.split(":")
    cmd = parts[0]
    ud = context.user_data

    if cmd == "noop":
        await q.answer()
        return

    if cmd == "x":
        ud.clear()
        await q.answer("Бас тартылды")
        if is_admin(uid) and admin_mode(uid):
            await edit(q, admin_title(uid), admin_kb(uid))
        elif U(uid) and U(uid)["status"] == "active":
            await show_menu(bot, uid, q)
        return

    ADMIN_CMDS = ("ap", "rj", "ok", "bad", "uc", "udc", "ud", "ur", "ua", "uo", "uoy", "uod", "uody",
                  "ln", "a", "ed", "eds", "edr", "bcy")
    if cmd in ADMIN_CMDS:
        if not is_admin(uid):
            await q.answer("Рұқсат жоқ", show_alert=True)
            return
        owner_only = cmd in ("ua", "uo", "uoy", "uod", "uody", "ed", "eds", "edr") or \
            (cmd == "a" and parts[1] in ("cfg", "img", "admins"))
        if owner_only and not is_owner(uid):
            await q.answer("Тек бас админ", show_alert=True)
            return
        await q.answer()

        if cmd in ("ap", "rj", "ok", "bad"):
            tid = int(parts[1])
            fn = {"ap": do_approve, "rj": do_reject, "ok": do_granted, "bad": do_bad_tv}[cmd]
            res = await fn(bot, tid)
            await edit(q, (q.message.text or "") + "\n\n" + res, None, html_mode=False)
        elif cmd == "uc":
            tid = int(parts[1])
            if U(tid):
                await edit(q, card(tid), card_kb(uid, tid))
        elif cmd == "udc":
            tid = int(parts[1])
            await edit(q, f"🗑 <b>{esc(U(tid)['name'])}</b> өшірілсін бе?\nСигнал алуды тоқтатады.",
                       kb([[("✅ Иә, өшіру", f"ud:{tid}"), ("↩️ Жоқ", f"uc:{tid}")]]))
        elif cmd == "ud":
            tid = int(parts[1])
            res = await do_remove(bot, tid, uid)
            await edit(q, res + "\n\n" + card(tid), card_kb(uid, tid))
        elif cmd == "ur":
            tid = int(parts[1])
            u = U(tid)
            u["status"] = "active" if u.get("tv") else "pending"
            save_users()
            await edit(q, card(tid), card_kb(uid, tid))
        elif cmd == "ua":
            tid = int(parts[1])
            u = U(tid)
            u["admin"] = not u.get("admin")
            if u["admin"]:
                u["status"] = "active"
            save_users()
            await edit(q, card(tid), card_kb(uid, tid))
        elif cmd == "uo":
            tid = int(parts[1])
            await edit(q, f"👑 <b>{esc(U(tid)['name'])}</b> бас админ болсын ба?\n"
                          "Бас админ барлық баптауды өзгерте алады және басқаларды админ ете алады.",
                       kb([[("✅ Иә", f"uoy:{tid}"), ("↩️ Жоқ", f"uc:{tid}")]]))
        elif cmd == "uoy":
            tid = int(parts[1])
            u = U(tid)
            u["admin"] = True
            u["status"] = "active"
            save_users()
            set_owners(owner_ids() | {tid})
            await edit(q, f"👑 Енді бас админ: {esc(u['name'])}", kb([[("⬅️ Тізім", "a:users:0")]]))
        elif cmd == "uod":
            tid = int(parts[1])
            await edit(q, f"👑 <b>{esc(U(tid)['name'])}</b> бас админдіктен алынсын ба?\nОл қарапайым админ болып қалады.",
                       kb([[("✅ Иә", f"uody:{tid}"), ("↩️ Жоқ", f"uc:{tid}")]]))
        elif cmd == "uody":
            tid = int(parts[1])
            rest = owner_ids() - {tid}
            if tid == uid or not rest:
                await edit(q, "⚠️ Болмайды: өзіңізді немесе соңғы бас админді алуға болмайды.",
                           kb([[("⬅️ Тізім", "a:users:0")]]), html_mode=False)
            else:
                set_owners(rest)
                await edit(q, card(tid), card_kb(uid, tid))
        elif cmd == "ln":
            tid = int(parts[1])
            ok = await send(bot, tid, "🔗 Сізге жаңа бір реттік сілтеме:\n" + make_link(tid), protect_content=True)
            await edit(q, ("✅ Жіберілді (ескісі жарамсыз)\n\n" if ok else "⚠️ Жіберілмеді\n\n") + card(tid),
                       card_kb(uid, tid))
        elif cmd == "bcy":
            text = ud.pop("bc_text", None)
            if not text:
                await edit(q, "⚠️ Мәтін табылмады.", kb([[("⬅️ Панель", "a:home")]]), html_mode=False)
                return
            n = 0
            for k, u in list(users.items()):
                if u.get("status") == "active":
                    if await send(bot, int(k), text):
                        n += 1
                    await asyncio.sleep(0.05)
            await edit(q, f"📣 Жіберілді: {n}", kb([[("⬅️ Панель", "a:home")]]), html_mode=False)
        elif cmd == "a":
            act = parts[1]
            if act == "home":
                await edit(q, admin_title(uid), admin_kb(uid))
            elif act in ("users", "pend"):
                t, k = users_view(int(parts[2]) if len(parts) > 2 else 0, act == "pend")
                await edit(q, t, k)
            elif act == "stats":
                a = sum(1 for u in users.values() if u["status"] == "active")
                pen = sum(1 for u in users.values() if u["status"] in ("pending", "approved", "awaiting_tv"))
                ad = len(admin_ids())
                rec = len(receivers(lambda p: True))
                await edit(q, f"📊 Белсенді: {a}\nКүтуде: {pen}\nАдмин: {ad}\nСигнал алып отырғандар: {rec}",
                           kb([[("⬅️ Панель", "a:home")]]), html_mode=False)
            elif act == "cfg":
                rows = [[(LABELS[k], f"ed:{k}")] for k in LABELS if k != "indicator_link"] + [[("⬅️ Панель", "a:home")]]
                await edit(q, "✉️ Қай мәтінді өзгертеміз?", kb(rows), html_mode=False)
            elif act == "img":
                settings["send_image"] = "0" if cfg("send_image") == "1" else "1"
                save_settings()
                await edit(q, admin_title(uid), admin_kb(uid))
            elif act == "admins":
                rows = [[(("👑 " if is_owner(int(k)) else "🛡 ") + (u.get("name") or "—")[:24], f"uc:{k}")]
                        for k, u in users.items() if u.get("admin") or is_owner(int(k))]
                rows.append([("⬅️ Панель", "a:home")])
                await edit(q, "🛡 Админдер (жаңа админ ету: «Қолданушылар» → адамды таңдаңыз)", kb(rows), html_mode=False)
            elif act == "bc":
                ud["bc"] = True
                await edit(q, "📣 Барлық белсенді қолданушыларға жіберілетін хабар мәтінін жазып жіберіңіз:",
                           CANCEL_KB(), html_mode=False)
            elif act == "asuser":
                u = U(uid)
                if u:
                    u["as_user"] = True
                    save_users()
                await show_menu(bot, uid, q)
        elif cmd == "ed":
            key = parts[1]
            back = "a:home" if key == "indicator_link" else "a:cfg"
            await edit(q, f"{LABELS[key]}\n\nҚазіргі мәні:\n{cfg(key) or '— (қойылмаған)'}",
                       kb([[("✏️ Өзгерту", f"eds:{key}"), ("↩️ Әдепкіге", f"edr:{key}")], [("⬅️ Артқа", back)]]),
                       html_mode=False)
        elif cmd == "eds":
            ud["edit_key"] = parts[1]
            await edit(q, f"{LABELS[parts[1]]}\n\nЖаңа мәтінді (сілтемені) бір хабармен жіберіңіз.",
                       CANCEL_KB(), html_mode=False)
        elif cmd == "edr":
            settings.pop(parts[1], None)
            save_settings()
            await edit(q, "↩️ Әдепкі мәнге қайтарылды.", kb([[("⬅️ Панель", "a:home")]]), html_mode=False)
        return

    # ---------- қолданушы баптауы ----------
    u = U(uid)
    if not u or u["status"] != "active":
        await q.answer("Доступ жоқ", show_alert=True)
        return
    await q.answer()
    p = P(uid)

    if cmd == "m":
        act = parts[1]
        if act == "home":
            await show_menu(bot, uid, q)
        elif act == "mk":
            await edit(q, "📊 Нарықтарды таңдаңыз:\n<i>Белгісі жоқтары FOREXCOM дерегі, (OANDA) деп тұрғандары OANDA дерегі.</i>", kb(market_rows(p["markets"])))
        elif act == "tf":
            await edit(q, "🕒 Таймфреймдерді таңдаңыз:", kb(toggle_rows(TFS, p["tfs"], "tt", "m:home", tfn)))
        elif act == "nt":
            p["notify"] = not p["notify"]
            save_prefs()
            await show_menu(bot, uid, q)
        elif act == "test":
            png = await asyncio.to_thread(draw_sweep, SWEEP_TEST) if cfg("send_image") == "1" else None
            await deliver(uid, SWEEP_TEST, png)
    elif cmd == "mt":
        v = parts[1]
        if v == "*":
            p["markets"] = list(MARKETS)
        elif v == "-":
            p["markets"] = []
        elif v in MARKETS:
            p["markets"] = ordered(set(p["markets"]) ^ {v}, MARKETS)
        save_prefs()
        await edit(q, "📊 Нарықтарды таңдаңыз:\n<i>Белгісі жоқтары FOREXCOM дерегі, (OANDA) деп тұрғандары OANDA дерегі.</i>", kb(market_rows(p["markets"])))
    elif cmd == "tt":
        if parts[1] in TFS:
            p["tfs"] = ordered(set(p["tfs"]) ^ {parts[1]}, TFS)
            save_prefs()
        await edit(q, "🕒 Таймфреймдерді таңдаңыз:", kb(toggle_rows(TFS, p["tfs"], "tt", "m:home", tfn)))


# ============================================================ WEB
def client_ip(request: web.Request) -> str:
    """Railway прокси нақты IP-ді X-Real-IP-ге жазады. Болмаса X-Forwarded-For-дың соңғы жазбасы алынады."""
    xri = request.headers.get("X-Real-IP", "").strip()
    if xri:
        return xri
    xff = [s.strip() for s in request.headers.get("X-Forwarded-For", "").split(",") if s.strip()]
    if xff:
        return xff[-1]
    return request.remote or ""


async def h_webhook(request: web.Request):
    key = request.match_info.get("key", "")
    ip = client_ip(request)
    allowed = WEBHOOK_OPEN or (key == "sweep" and ip in TV_IPS) or (bool(WEBHOOK_SECRET) and key == WEBHOOK_SECRET)
    if not allowed:
        log.warning("webhook rejected: key=%s ip=%s", "sweep" if key == "sweep" else "?", ip)
        return web.json_response({"error": "forbidden", "ip": ip}, status=403)
    try:
        d = json.loads((await request.text()).strip())
    except Exception:
        return web.json_response({"error": "bad json"}, status=400)
    if not isinstance(d, dict) or d.get("src") != "SWEEP":
        return web.json_response({"status": "ignored"})
    t = asyncio.create_task(process(d))
    bg_tasks.add(t)
    t.add_done_callback(bg_tasks.discard)
    return web.json_response({"status": "accepted"})


def page(msg, status=200, button=False):
    form = ('<form method="post"><button style="font-size:18px;padding:14px 28px;border:0;border-radius:10px;'
            'background:#111;color:#fff;cursor:pointer">Индикаторды ашу</button></form>' if button else "")
    body = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>GENESIS SWEEP</title><body style='font-family:system-ui,sans-serif;text-align:center;padding:64px 20px'>"
            f"<h2>GENESIS SWEEP</h2><p>{msg}</p>{form}</body>")
    return web.Response(text=body, status=status, content_type="text/html",
                        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


async def h_link_get(request: web.Request):
    e = tokens.get(request.match_info.get("token", ""))
    if not e:
        return page("⚠️ Сілтеме табылмады немесе өшірілген.", 404)
    if e["used"]:
        return page("❌ Бұл сілтеме бұрын қолданылған.", 410)
    if not cfg("indicator_link"):
        return page("⏳ Индикатор сілтемесі әлі дайын емес. Сәл кейін қайта ашыңыз немесе админге жазыңыз.", 503)
    return page("Бұл сілтеме тек бір рет жұмыс істейді.", button=True)


async def h_link_post(request: web.Request):
    e = tokens.get(request.match_info.get("token", ""))
    if not e:
        return page("⚠️ Сілтеме табылмады немесе өшірілген.", 404)
    if e["used"]:
        return page("❌ Бұл сілтеме бұрын қолданылған.", 410)
    if not cfg("indicator_link"):
        return page("⏳ Индикатор сілтемесі әлі дайын емес. Сәл кейін қайта ашыңыз немесе админге жазыңыз.", 503)
    e["used"] = True
    e["used_at"] = now_str()
    save_tokens()
    raise web.HTTPSeeOther(location=cfg("indicator_link"))


async def h_health(request: web.Request):
    return web.json_response({"status": "alive"})


def build_web_app():
    web_app = web.Application()
    web_app.router.add_post("/webhook/{key}", h_webhook)
    web_app.router.add_get("/link/{token}", h_link_get)
    web_app.router.add_post("/link/{token}", h_link_post)
    web_app.router.add_get("/health", h_health)
    web_app.router.add_get("/", h_health)
    return web_app


async def post_init(app: Application):
    users.update(rj("users.json", {}))
    prefs.update(rj("prefs.json", {}))
    settings.update(rj("settings.json", {}))
    tokens.update(rj("tokens.json", {}))
    if "owners" not in settings and OWNER_IDS:
        set_owners(OWNER_IDS)
    seed_admins()
    ensure_owner_records()
    runner = web.AppRunner(build_web_app())
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    app.bot_data["runner"] = runner
    await app.bot.set_my_commands([BotCommand("start", "Бастау"), BotCommand("admin", "Админ панелі")])
    log.info("Сервер іске қосылды: порт %s, бас админдер: %s", PORT, len(owner_ids()))


async def post_shutdown(app: Application):
    r = app.bot_data.get("runner")
    if r:
        await r.cleanup()


async def on_error(update, context):
    log.error("handler error", exc_info=context.error)


def main():
    global tg_app
    if not BOT_TOKEN:
        sys.exit("BOT_TOKEN айнымалысы қойылмаған.")
    if not OWNER_IDS:
        log.warning("OWNER_IDS бос: бас админ жоқ, settings.json-дағы owners қолданылады.")
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    tg_app = Application.builder().token(BOT_TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    tg_app.add_handler(CommandHandler("start", cmd_start))
    tg_app.add_handler(CommandHandler("admin", cmd_admin))
    tg_app.add_handler(CallbackQueryHandler(on_cb))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    tg_app.add_error_handler(on_error)
    log.info("Bot іске қосылды.")
    tg_app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
