import asyncio, hashlib, html, io, json, logging, os, re, secrets
from collections import OrderedDict
from datetime import datetime
from typing import Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

from aiohttp import web
from telegram import (BotCommand, InlineKeyboardButton, InlineKeyboardMarkup,
                      LinkPreviewOptions, Update)
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

# ============================================================ CONFIG
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")  # secrets come only from Railway variables
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://web-production-53529.up.railway.app").rstrip("/")
DATA_DIR = os.environ.get("DATA_DIR", ".")
PORT = int(os.environ.get("PORT", "5001"))

MARKETS = ["XAUUSD", "XAUEUR", "BTCUSD", "XAGUSD", "GBPUSD", "EURUSD", "GER40", "AUDUSD", "USDJPY", "CADJPY"]
TFS = ["3", "15", "30", "60"]
EVENTS = {"MSS": "Тек MSS", "SWEEP": "Тек Sweep / Raid", "BOTH": "Екеуі де"}
EV_ORDER = ["MSS", "SWEEP", "BOTH"]
TZ = ZoneInfo("Asia/Almaty")
PAGE = 8

DEFAULTS = {
    "indicator_link": "https://ru.tradingview.com/script/d8vYA675-genesis-order-flow/",
    "send_image": "1",
    "txt_welcome": "Сәлеметсіз бе! GENESIS ORDER FLOW ботына қош келдіңіз.\n\nӨтініш жіберу үшін аты-жөніңізді жазыңыз:",
    "txt_approved": ("🎉 GENESIS ORDER FLOW курсына қош келдіңіз, {name}!\n\n"
                     "GENESIS ORDER FLOW — ликвидность жиналатын сәттерді (Sweep, Raid) және құрылымның "
                     "ауысуын (MSS) автоматты түрде көрсететін индикатор.\n\n"
                     "📎 Индикатор сілтемесі (БІР РЕТ жұмыс істейді):\n{link}\n\n"
                     "Доступ ашу үшін TradingView юзернейміңізді осы чатқа жазыңыз.\n"
                     "Табу жолы: TradingView → оң жақ жоғарыдағы профиль суреті → профиль бетіндегі @-тан кейінгі ат."),
    "txt_granted": "🎉 Құттықтаймыз, {name}! TradingView-де индикаторға доступ ашылды.\nЕнді баптауды жасаңыз.",
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
log = logging.getLogger("genesis")
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
def owner_id(): return int(settings.get("owner", OWNER_ID))
def now_str(): return datetime.now(TZ).strftime("%d.%m.%Y %H:%M")
def esc(x): return html.escape(str(x)) if x not in (None, "") else "—"


def fill(t, **kw):
    for k, v in kw.items():
        t = t.replace("{" + k + "}", str(v))
    return t


def tfn(tf):
    tf = str(tf)
    if tf.isdigit():
        n = int(tf)
        return f"{n // 60}Ч" if n >= 60 and n % 60 == 0 else f"{n}м"
    return tf


def tf_en(tf):
    tf = str(tf)
    if tf.isdigit():
        n = int(tf)
        return f"{n // 60}H" if n >= 60 and n % 60 == 0 else f"{n}m"
    return tf


def U(uid): return users.get(str(uid))
def is_owner(uid): return int(uid) == owner_id()


def is_admin(uid):
    u = U(uid)
    return is_owner(uid) or bool(u and u.get("admin") and u.get("status") == "active")


def admin_mode(uid):
    u = U(uid)
    return is_admin(uid) and not (u or {}).get("as_user")


def admin_ids():
    s = {owner_id()}
    s.update(int(k) for k, u in users.items() if u.get("admin") and u.get("status") == "active")
    return s


def P(uid):
    p = prefs.setdefault(str(uid), {})
    p.setdefault("markets", ["XAUUSD"])
    p.setdefault("sw", ["3"])
    p.setdefault("ms", ["3"])
    p.setdefault("events", "MSS")
    p.setdefault("notify", True)
    p.setdefault("per", {})
    return p


def ordered(items, universe):
    return [x for x in universe if x in set(items)]


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


async def send(bot, uid, text, markup=None, **kw):
    try:
        await bot.send_message(chat_id=uid, text=text, reply_markup=markup,
                               parse_mode=kw.pop("parse_mode", None),
                               link_preview_options=LinkPreviewOptions(is_disabled=True), **kw)
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
def menu_text(uid):
    p = P(uid)
    warn = "" if (p["markets"] and p["sw"] and p["ms"]) else "\n⚠️ Нарық немесе таймфрейм таңдалмаған — хабар келмейді."
    per = ""
    if p["per"]:
        per = "\nЖеке баптау: " + ", ".join(p["per"].keys())
    return ("⚙️ <b>Баптау</b>\n"
            f"Нарықтар: {', '.join(p['markets']) or '—'}\n"
            f"Sweep TF: {', '.join(tfn(t) for t in p['sw']) or '—'}\n"
            f"MSS TF: {', '.join(tfn(t) for t in p['ms']) or '—'}\n"
            f"Оқиғалар: {EVENTS[p['events']]}\n"
            f"Хабар: {'қосулы' if p['notify'] else 'өшірулі'}{per}{warn}")


def menu_kb(uid):
    p = P(uid)
    return kb([
        [("📊 Нарықтар", "m:mk"), ("🕒 Sweep TF", "m:sw"), ("🕒 MSS TF", "m:ms")],
        [("🔔 Оқиғалар: " + EVENTS[p["events"]], "m:ev")],
        [("⚙️ Нарыққа жеке TF", "m:pm")],
        [("🔕 Хабарды өшіру" if p["notify"] else "🔔 Хабарды қосу", "m:nt")],
        [("🧪 Тест хабар", "m:test")],
    ])


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
        rows += [[("🔗 Индикатор сілтемесі", "ed:indicator_link")],
                 [("✉️ Хабарлама мәтіндері", "a:cfg")],
                 [("🖼 Сурет: " + ("қосулы" if cfg("send_image") == "1" else "өшірулі"), "a:img")],
                 [("🛡 Админдер", "a:admins")]]
    rows.append([("👤 Қолданушы ретінде кіру", "a:asuser")])
    return kb(rows)


ADMIN_TITLE = ("🛠 <b>Админ панелі</b>\n\nҚолданушы режимінен қайту үшін /admin жазыңыз.")


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
    if is_owner(viewer) and not is_owner(uid):
        rows.append([("🛡 Админдіктен алу" if u.get("admin") else "🛡 Админ ету", f"ua:{uid}")])
        if u["status"] == "active":
            rows.append([("👑 Бас админ ету", f"uo:{uid}")])
    rows.append([("⬅️ Тізім", "a:users:0")])
    return kb(rows)


# ============================================================ ACCESS FLOW
async def show_home(bot, uid, q=None):
    if admin_mode(uid):
        if q:
            await edit(q, ADMIN_TITLE, admin_kb(uid))
        else:
            await send(bot, uid, ADMIN_TITLE, admin_kb(uid), parse_mode=ParseMode.HTML)
    else:
        await show_menu(bot, uid, q)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    context.user_data.clear()
    u = U(uid)
    if is_owner(uid) and not u:
        users[str(uid)] = {"name": update.effective_user.full_name, "tg": update.effective_user.username,
                           "tv": None, "status": "active", "admin": True}
        save_users()
        u = U(uid)
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
    u = U(uid)
    if u:
        u["as_user"] = False
        save_users()
    await update.message.reply_text(ADMIN_TITLE, reply_markup=admin_kb(uid), parse_mode=ParseMode.HTML)


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
    return "✅ Қабылданды" + ("" if ok else " (⚠️ хабар жіберілмеді)")


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


# ============================================================ SIGNAL TEXT
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


def build_text(d, with_note):
    sym = esc(d.get("symbol"))
    ev = d.get("event")
    kind = "Raid" if str(d.get("kind")) == "Raid" else "Sweep"
    short = d.get("dir") == "SHORT"
    swtf, mstf = tfn(d.get("sweep_tf")), tfn(d.get("mss_tf"))
    liq = "жоғарғы" if short else "төменгі"
    move = "төмен" if short else "жоғары"
    dir_line = "🔴 Бағыт: <b>SHORT</b> (баға төмен қарай күтіледі)" if short else "🟢 Бағыт: <b>LONG</b> (баға жоғары қарай күтіледі)"
    lvl = fp(d.get("level"))
    if kind == "Raid":
        what = (f"{sym} нарығында <b>{swtf}</b> таймфреймде {liq} ликвидностьте <b>Raid</b> болды: "
                f"баға {lvl} деңгейін денемен бұзып, келесі свечада кері жабылды.")
    else:
        what = (f"{sym} нарығында <b>{swtf}</b> таймфреймде {liq} ликвидностьте <b>Sweep</b> болды: "
                f"баға {lvl} деңгейін фитильмен алып, свеча деңгейдің ішінде жабылды.")
    if ev == "MSS":
        head = f"🐘 <b>MSS расталды · {sym}</b>"
        what += (f"\nСодан кейін <b>{mstf}</b> таймфреймде <b>MSS</b> расталды: баға {fp(d.get('mss_level'))} "
                 f"деңгейін денемен бұзды, сондықтан {move} қарай қозғалыс күтіледі.")
    else:
        head = f"{'🎯' if kind == 'Raid' else '💧'} <b>{kind} болды · {sym}</b>"
        what += "\nMSS әлі расталған жоқ, расталса бөлек хабар келеді."

    items = [("Stop", num(d, "stop")), (f"{kind} деңгейі", num(d, "level"))]
    if ev == "MSS":
        items += [("MSS деңгейі", num(d, "mss_level")), ("Entry", num(d, "entry")),
                  ("TP 1", num(d, "tp1")), ("TP 2", num(d, "tp2")), ("TP 3", num(d, "tp3")), ("TP 4", num(d, "tp4"))]
    items = [(n, v) for n, v in items if v is not None]
    items.sort(key=lambda x: -x[1])
    lines = "\n".join(f"{n}: <code>{fp(v)}</code>" for n, v in items)

    tid = d.get("tickerid") or d.get("symbol")
    url = f"https://www.tradingview.com/chart/?symbol={quote(str(tid))}&interval={quote(str(d.get('mss_tf')))}"
    link = f'📈 <a href="{html.escape(url)}">{sym} графигін ашу ({mstf})</a>'

    parts = [head, dir_line, "", what, "", "Деңгейлер (жоғарыдан төмен):", lines, "", link]
    if with_note:
        parts += ["", "<i>Суреттегі деңгейлер тек мысал ретінде көрсетілген (схема), нақты бағаға дәл келмеуі мүмкін. "
                      "Нақты сандар жоғарыдағы тізімде.</i>"]
    parts.append(esc(d.get("time")))
    return "\n".join(parts)


# ============================================================ SIGNAL IMAGE (Pillow, TradingView стилі)
def draw_card(d):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    try:
        return _draw(d, Image, ImageDraw, ImageFont)
    except Exception:
        log.exception("draw failed")
        return None


def _draw(d, Image, ImageDraw, ImageFont):
    ev = d.get("event")
    kind = "Raid" if str(d.get("kind")) == "Raid" else "Sweep"
    short = d.get("dir") == "SHORT"
    s = 1 if short else -1
    L, S = num(d, "level"), num(d, "stop")
    if L is None or S is None:
        return None
    has_mss = ev == "MSS" and all(num(d, k) is not None for k in ("entry", "tp1", "tp2", "tp3", "tp4", "mss_level"))

    # a-кеңістік: a = s*(баға - L). Оң жағы = Stop жағы, теріс жағы = қозғалыс бағыты
    st = s * (S - L)
    if st <= 0:
        st = max(abs(S - L), abs(L) * 1e-4, 1e-6)
    if has_mss:
        m = s * (num(d, "mss_level") - L)
        if m >= 0:
            m = -max(abs(m), st * 2)
        e = s * (num(d, "entry") - L)
        if e >= m:
            e = m - abs(m) * 0.15
        ta = [s * (num(d, k) - L) for k in ("tp1", "tp2", "tp3", "tp4")]
    else:
        m = -st * 4
        e = None
        ta = []
    u = abs(m)

    def A(f):
        return -f * u

    # (open, close, hi, lo) a-кеңістікте
    cs = [
        (A(.50), A(.20), A(.10), A(.60)),   # 0
        (A(.25), A(.35), A(.15), A(.45)),   # 1
        (A(.15), A(.40), 0.0,    A(.50)),   # 2 деңгей фракталы (hi = level)
        (A(.40), A(.25), A(.15), A(.55)),   # 3
        (A(.30), A(.70), A(.20), A(1.0)),   # 4 MSS фракталы (lo = MSS деңгейі)
        (A(.75), A(.35), A(.30), A(.85)),   # 5
    ]
    if kind == "Raid":
        cs.append((A(.30), 0.35 * st, 0.75 * st, A(.35)))       # 6 жасыл, деңгейден жоғары жабылады
        cs.append((0.30 * st, A(.40), st, A(.45)))              # 7 қызыл, деңгейден төмен жабылады
    else:
        cs.append((A(.35), A(.15), A(.05), A(.45)))             # 6
        cs.append((A(.15), A(.45), st, A(.50)))                 # 7 Sweep свечасы (hi = Stop)
    SWI = 7
    MI = None
    if has_mss:
        lo8 = e - max(abs(e - m) * 0.2, u * 0.05)
        cs.append((A(.60), e, A(.50), lo8))                     # 8 MSS свечасы, жабылу = Entry
        MI = 8
        target = ta[2] if ta[2] < e else e - u
        n = 7
        base = [e + (target - e) * k / n for k in range(n + 1)]
        for k in range(n):
            step = base[k + 1] - base[k]
            sa = abs(step)
            if k in (1, 4):
                c_ = base[k] + sa * 0.5
                cs.append((base[k], c_, c_ + sa * 0.2, base[k] - sa * 0.2))
            else:
                cs.append((base[k], base[k + 1], base[k] + sa * 0.15, base[k + 1] - sa * 0.2))
    else:
        cs.append((A(.45), A(.70), A(.40), A(.80)))
        cs.append((A(.70), A(.55), A(.50), A(.85)))

    def price(a): return L + s * a

    cp = []
    for (o, c_, h_, l_) in cs:
        p1, p2 = price(h_), price(l_)
        cp.append((price(o), price(c_), max(p1, p2), min(p1, p2)))

    allp = [x for c in cp for x in c] + [S, L]
    if has_mss:
        allp += [price(e), price(m)] + [price(t) for t in ta]
    hi, lo = max(allp), min(allp)
    pad = (hi - lo) * 0.06 or 1.0
    hi += pad
    lo -= pad

    W, H, T, B = 980, 680, 100, 30
    img = Image.new("RGB", (W, H), (255, 255, 255))
    dr = ImageDraw.Draw(img)

    def font(sz):
        try:
            return ImageFont.load_default(size=sz)
        except TypeError:
            return ImageFont.load_default()
    fT, fM, fS, fL = font(26), font(17), font(14), font(18)

    def y(p): return T + (hi - p) / (hi - lo) * (H - T - B)
    def x(i): return 50 + i * 46

    GRN, RED = (66, 157, 133), (224, 75, 84)
    ZR, ZG, ZY = (247, 223, 223), (228, 240, 228), (247, 222, 150)
    LRED, LGRN = (225, 90, 90), (86, 160, 90)
    DARK, ORG, GRAYT = (40, 40, 52), (240, 110, 40), (95, 95, 105)
    stop_dir = -1 if short else 1          # экранда Stop жағы: қысқада жоғары (-y), ұзында төмен (+y)

    def txt_center(cx, ty, text, color, f):
        w = dr.textlength(text, font=f)
        dr.text((cx - w / 2, ty), text, fill=color, font=f)

    # ---------------- ФИБО ----------------
    xl = x(SWI)
    if has_mss:
        xr = x(MI + 3)
        pS, pE = S, price(e)
        pT = [price(t) for t in ta]
        dr.rectangle([xl, min(y(pS), y(pE)), xr, max(y(pS), y(pE))], fill=ZR)
        dr.rectangle([xl, min(y(pE), y(pT[3])), xr, max(y(pE), y(pT[3]))], fill=ZG)
        p05, p618 = pS + (pE - pS) * 0.5, pS + (pE - pS) * 0.618
        dr.rectangle([xl, min(y(p05), y(p618)), xr, max(y(p05), y(p618))], fill=ZY)
        fib_lines = [(pS, "Stop", LRED), (pE, "Entry", LRED)] + [(pT[i], f"TP {i + 1}", LGRN) for i in range(4)]
        for p, name, col in fib_lines:
            dr.line([xl, y(p), xr, y(p)], fill=col, width=1)
            dr.text((xl + 8, y(p) + 1), name, fill=col, font=fM)
    else:
        xr = x(SWI + 3)
        dr.line([xl, y(S), xr, y(S)], fill=LRED, width=1)
        dr.text((xl + 8, y(S) + 1), "Stop", fill=LRED, font=fM)

    # ---------------- СВЕЧАЛАР ----------------
    for i, (po, pc, ph, pl) in enumerate(cp):
        cx = x(i)
        col = GRN if pc >= po else RED
        dr.line([cx, y(ph), cx, y(pl)], fill=col, width=2)
        top, bot = y(max(po, pc)), y(min(po, pc))
        if bot - top < 3:
            bot = top + 3
        dr.rectangle([cx - 13, top, cx + 13, bot], fill=col)

    # ---------------- ДЕҢГЕЙ / MSS СЫЗЫҚТАРЫ ----------------
    dr.line([x(2), y(L), x(SWI), y(L)], fill=DARK, width=3)
    mid = (x(2) + x(SWI)) / 2
    if kind == "Raid":
        ty = y(L) + (6 if stop_dir == -1 else -26)
    else:
        ty = y(L) + (-26 if stop_dir == -1 else 6)
    txt_center(mid, ty, kind, GRAYT, fL)

    if has_mss:
        pm = price(m)
        dr.line([x(4), y(pm), x(MI), y(pm)], fill=DARK, width=3)
        ty = y(pm) + (-26 if stop_dir == -1 else 6)
        txt_center((x(4) + x(MI)) / 2 + 20, ty, "MSS", GRAYT, fL)

    # ---------------- ФРАКТАЛ ҮШБҰРЫШТАРЫ, НҮКТЕЛЕР ----------------
    def tri(cx, p, above_red):
        yy = y(p)
        if above_red:
            dr.polygon([(cx - 8, yy - 20), (cx + 8, yy - 20), (cx, yy - 8)], fill=RED)
        else:
            dr.polygon([(cx - 8, yy + 20), (cx + 8, yy + 20), (cx, yy + 8)], fill=GRN)

    def mark(i, a_val, side):
        p = price(a_val)
        price_high = (side == "hi") == (s == 1)
        tri(x(i), p, price_high)

    def dot(cx, p, r=5, ring=False):
        yy = y(p)
        if ring:
            dr.ellipse([cx - r, yy - r, cx + r, yy + r], outline=GRAYT, fill=(255, 255, 255), width=2)
        else:
            dr.ellipse([cx - r, yy - r, cx + r, yy + r], fill=ORG)

    mark(2, 0.0, "hi")
    dot(x(2), L, ring=True)
    mark(SWI, st, "hi")
    dot(x(SWI), S)
    if has_mss:
        mark(4, m, "lo")
        dot(x(4), price(m))
        dot(x(MI), price(e))

    # ---------------- ТАҚЫРЫП ----------------
    title = f"{d.get('symbol')}  |  {'SHORT' if short else 'LONG'}  |  {kind} {tf_en(d.get('sweep_tf'))}"
    if has_mss:
        title += f"  ->  MSS {tf_en(d.get('mss_tf'))}"
    dr.text((24, 22), title, fill=(20, 20, 20), font=fT)
    dr.text((24, 60), "Schematic example, not real candles", fill=(150, 150, 150), font=fS)

    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# ============================================================ DELIVERY / ROUTING
async def deliver(uid, d, png):
    bot = tg_app.bot
    text = build_text(d, with_note=bool(png))
    plain = html.unescape(re.sub(r"<[^>]+>", "", text))
    try:
        if png:
            if len(plain) <= 1000:
                await bot.send_photo(chat_id=uid, photo=png, caption=text, parse_mode=ParseMode.HTML)
                return
            await bot.send_photo(chat_id=uid, photo=png)
        await bot.send_message(chat_id=uid, text=text, parse_mode=ParseMode.HTML,
                               link_preview_options=LinkPreviewOptions(is_disabled=True))
    except Exception as e:
        log.warning("deliver %s: %s", uid, e)
        try:
            await bot.send_message(chat_id=uid, text=build_text(d, with_note=False), parse_mode=ParseMode.HTML,
                                   link_preview_options=LinkPreviewOptions(is_disabled=True))
        except Exception:
            pass


async def route(d):
    sym, ev = d["symbol"], d["event"]
    targets = []
    for k, u in users.items():
        if u.get("status") != "active":
            continue
        if is_admin(int(k)) and not u.get("as_user"):
            continue
        p = P(k)
        if not p["notify"] or sym not in p["markets"]:
            continue
        if p["events"] == "MSS" and ev != "MSS":
            continue
        if p["events"] == "SWEEP" and ev == "MSS":
            continue
        o = p["per"].get(sym)
        sw, ms = (o["sw"], o["ms"]) if o else (p["sw"], p["ms"])
        if d["sweep_tf"] in sw and d["mss_tf"] in ms:
            targets.append(int(k))
    if not targets:
        return
    png = None
    if cfg("send_image") == "1":
        png = await asyncio.to_thread(draw_card, d)
    for t in targets:
        await deliver(t, d, png)
        await asyncio.sleep(0.04)


async def process(d):
    try:
        base = {k: v for k, v in d.items() if k != "events"}
        items = d["events"] if isinstance(d.get("events"), list) else [d]
        for it in items:
            if not isinstance(it, dict):
                continue
            x = {**base, **it}
            if not all(k in x for k in ("symbol", "event", "sweep_tf", "mss_tf")):
                continue
            x["symbol"] = str(x["symbol"]).split(":")[-1].upper()
            x["event"] = str(x["event"]).upper()
            x["sweep_tf"], x["mss_tf"] = str(x["sweep_tf"]), str(x["mss_tf"])
            key = hashlib.sha1(json.dumps(x, sort_keys=True).encode()).hexdigest()
            if key in seen:
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
            await edit(q, ADMIN_TITLE, admin_kb(uid))
        elif U(uid) and U(uid)["status"] == "active":
            await show_menu(bot, uid, q)
        return

    ADMIN_CMDS = ("ap", "rj", "ok", "bad", "uc", "udc", "ud", "ur", "ua", "uo", "uoy",
                  "ln", "a", "ed", "eds", "edr", "bcy")
    if cmd in ADMIN_CMDS:
        if not is_admin(uid):
            await q.answer("Рұқсат жоқ", show_alert=True)
            return
        owner_only = cmd in ("ua", "uo", "uoy", "ed", "eds", "edr") or \
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
            await edit(q, f"👑 <b>{esc(U(tid)['name'])}</b> бас админ болсын ба?\nСіз қарапайым админ боласыз.",
                       kb([[("✅ Иә", f"uoy:{tid}"), ("↩️ Жоқ", f"uc:{tid}")]]))
        elif cmd == "uoy":
            tid = int(parts[1])
            u = U(tid)
            u["admin"] = True
            u["status"] = "active"
            settings["owner"] = tid
            save_settings()
            save_users()
            await edit(q, f"👑 Бас админ енді: {esc(u['name'])}", None)
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
                await edit(q, ADMIN_TITLE, admin_kb(uid))
            elif act in ("users", "pend"):
                t, k = users_view(int(parts[2]) if len(parts) > 2 else 0, act == "pend")
                await edit(q, t, k)
            elif act == "stats":
                a = sum(1 for u in users.values() if u["status"] == "active")
                pen = sum(1 for u in users.values() if u["status"] in ("pending", "approved", "awaiting_tv"))
                ad = len(admin_ids())
                await edit(q, f"📊 Белсенді: {a}\nКүтуде: {pen}\nАдмин: {ad}", kb([[("⬅️ Панель", "a:home")]]),
                           html_mode=False)
            elif act == "cfg":
                rows = [[(LABELS[k], f"ed:{k}")] for k in LABELS if k != "indicator_link"] + [[("⬅️ Панель", "a:home")]]
                await edit(q, "✉️ Қай мәтінді өзгертеміз?", kb(rows), html_mode=False)
            elif act == "img":
                settings["send_image"] = "0" if cfg("send_image") == "1" else "1"
                save_settings()
                await edit(q, ADMIN_TITLE, admin_kb(uid))
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
            await edit(q, f"{LABELS[key]}\n\nҚазіргі мәні:\n{cfg(key)}",
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
            await edit(q, "📊 Нарықтарды таңдаңыз:", kb(toggle_rows(MARKETS, p["markets"], "mt", "m:home")))
        elif act in ("sw", "ms"):
            title = "🕒 Sweep таймфреймдері:" if act == "sw" else "🕒 MSS таймфреймдері:"
            await edit(q, title, kb(toggle_rows(TFS, p[act], f"tt:{act}", "m:home", tfn)))
        elif act == "ev":
            p["events"] = EV_ORDER[(EV_ORDER.index(p["events"]) + 1) % 3]
            save_prefs()
            await show_menu(bot, uid, q)
        elif act == "nt":
            p["notify"] = not p["notify"]
            save_prefs()
            await show_menu(bot, uid, q)
        elif act == "pm":
            rows = [[(m_, f"pv:{m_}") for m_ in MARKETS[i:i + 2]] for i in range(0, len(MARKETS), 2)]
            rows.append([("⬅️ Артқа", "m:home")])
            await edit(q, "⚙️ Нарықты таңдаңыз (жеке TF баптау):", kb(rows), html_mode=False)
        elif act == "test":
            d = {"src": "GENESIS", "event": "MSS", "kind": "Raid", "symbol": "XAUUSD", "sweep_tf": "15", "mss_tf": "3",
                 "dir": "SHORT", "level": 4182.0, "stop": 4183.5, "entry": 4175.0, "tp1": 4161.2, "tp2": 4152.5,
                 "tp3": 4143.8, "tp4": 4135.1, "mss_level": 4176.5, "time": "тест"}
            png = await asyncio.to_thread(draw_card, d) if cfg("send_image") == "1" else None
            await deliver(uid, d, png)
    elif cmd == "mt":
        s_ = set(p["markets"]) ^ {parts[1]}
        p["markets"] = ordered(s_, MARKETS)
        save_prefs()
        await edit(q, "📊 Нарықтарды таңдаңыз:", kb(toggle_rows(MARKETS, p["markets"], "mt", "m:home")))
    elif cmd == "tt":
        s_ = set(p[parts[1]]) ^ {parts[2]}
        p[parts[1]] = ordered(s_, TFS)
        save_prefs()
        title = "🕒 Sweep таймфреймдері:" if parts[1] == "sw" else "🕒 MSS таймфреймдері:"
        await edit(q, title, kb(toggle_rows(TFS, p[parts[1]], f"tt:{parts[1]}", "m:home", tfn)))
    elif cmd in ("pv", "pt", "pr"):
        sym = parts[1] if cmd != "pt" else parts[2]
        if sym not in MARKETS:
            return
        if cmd == "pt":
            o = p["per"].setdefault(sym, {"sw": list(p["sw"]), "ms": list(p["ms"])})
            s_ = set(o[parts[1]]) ^ {parts[3]}
            o[parts[1]] = ordered(s_, TFS)
            save_prefs()
        elif cmd == "pr":
            p["per"].pop(sym, None)
            save_prefs()
        o = p["per"].get(sym)
        sw, ms = (o["sw"], o["ms"]) if o else ([], [])
        rows = [[("Sweep TF:", "noop")],
                [(("✅ " if t in sw else "▫️ ") + tfn(t), f"pt:sw:{sym}:{t}") for t in TFS],
                [("MSS TF:", "noop")],
                [(("✅ " if t in ms else "▫️ ") + tfn(t), f"pt:ms:{sym}:{t}") for t in TFS],
                [("🗑 Жеке баптауды алып тастау", f"pr:{sym}")], [("⬅️ Артқа", "m:pm")]]
        await edit(q, f"⚙️ {sym}: жеке таймфреймдер" + ("" if o else "\n(қазір ортақ баптау қолданылады)"),
                   kb(rows), html_mode=False)


# ============================================================ WEB
async def h_webhook(request: web.Request):
    if request.match_info.get("secret") != WEBHOOK_SECRET:
        return web.json_response({"error": "forbidden"}, status=403)
    try:
        d = json.loads((await request.text()).strip())
    except Exception:
        return web.json_response({"error": "bad json"}, status=400)
    if not isinstance(d, dict) or d.get("src") != "GENESIS":
        return web.json_response({"status": "ignored"})
    t = asyncio.create_task(process(d))
    bg_tasks.add(t)
    t.add_done_callback(bg_tasks.discard)
    return web.json_response({"status": "accepted"})


def page(msg, status=200, button=False):
    form = ('<form method="post"><button style="font-size:18px;padding:14px 28px;border:0;border-radius:10px;'
            'background:#111;color:#fff;cursor:pointer">Индикаторды ашу</button></form>' if button else "")
    body = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>GENESIS ORDER FLOW</title><body style='font-family:system-ui,sans-serif;text-align:center;padding:64px 20px'>"
            f"<h2>GENESIS ORDER FLOW</h2><p>{msg}</p>{form}</body>")
    return web.Response(text=body, status=status, content_type="text/html",
                        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})


async def h_link_get(request: web.Request):
    e = tokens.get(request.match_info.get("token", ""))
    if not e:
        return page("⚠️ Сілтеме табылмады немесе өшірілген.", 404)
    if e["used"]:
        return page("❌ Бұл сілтеме бұрын қолданылған.", 410)
    return page("Бұл сілтеме тек бір рет жұмыс істейді.", button=True)


async def h_link_post(request: web.Request):
    e = tokens.get(request.match_info.get("token", ""))
    if not e:
        return page("⚠️ Сілтеме табылмады немесе өшірілген.", 404)
    if e["used"]:
        return page("❌ Бұл сілтеме бұрын қолданылған.", 410)
    e["used"] = True
    e["used_at"] = now_str()
    save_tokens()
    raise web.HTTPSeeOther(location=cfg("indicator_link"))


async def h_health(request: web.Request):
    return web.json_response({"status": "alive"})


async def post_init(app: Application):
    users.update(rj("users.json", {}))
    prefs.update(rj("prefs.json", {}))
    settings.update(rj("settings.json", {}))
    tokens.update(rj("tokens.json", {}))
    if str(OWNER_ID) not in users:
        users[str(OWNER_ID)] = {"name": "Owner", "tg": None, "tv": None, "status": "active", "admin": True}
        save_users()
    web_app = web.Application()
    web_app.router.add_post("/webhook/{secret}", h_webhook)
    web_app.router.add_get("/link/{token}", h_link_get)
    web_app.router.add_post("/link/{token}", h_link_post)
    web_app.router.add_get("/health", h_health)
    web_app.router.add_get("/", h_health)
    runner = web.AppRunner(web_app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    app.bot_data["runner"] = runner
    await app.bot.set_my_commands([BotCommand("start", "Бастау"), BotCommand("admin", "Админ панелі")])
    log.info("Сервер іске қосылды: порт %s", PORT)


async def post_shutdown(app: Application):
    r = app.bot_data.get("runner")
    if r:
        await r.cleanup()


async def on_error(update, context):
    log.error("handler error", exc_info=context.error)


def main():
    global tg_app
    missing = [n for n, v in (("BOT_TOKEN", BOT_TOKEN), ("WEBHOOK_SECRET", WEBHOOK_SECRET), ("OWNER_ID", OWNER_ID)) if not v]
    if missing:
        raise SystemExit("Set these Railway variables first: " + ", ".join(missing))
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