"""TREDIS AI Telegram bot: thin Telegram layer over tredis.service."""
import html
import logging
import re
import sys

from anthropic import AsyncAnthropic
from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import TelegramError
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

from tredis.ai import AI
from tredis.config import Config
from tredis.db import DB
from tredis.service import Reply, Service
from tredis.texts import t

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)    # otherwise the bot token shows up in request URLs
logging.getLogger("httpx2").setLevel(logging.WARNING)
log = logging.getLogger("tredis")

TG_LIMIT = 4000


def markup(rows):
    if not rows:
        return None
    out = []
    for row in rows:
        btns = []
        for b in row:
            if len(b) == 3 and b[2]:
                btns.append(InlineKeyboardButton(b[0], url=b[2]))
            else:
                btns.append(InlineKeyboardButton(b[0], callback_data=b[1]))
        out.append(btns)
    return InlineKeyboardMarkup(out)


async def send_reply(bot, chat_id: int, r: Reply):
    kb = markup(r.buttons)
    if len(r.text) <= TG_LIMIT:
        await bot.send_message(chat_id, r.text, parse_mode=ParseMode.HTML, reply_markup=kb,
                               disable_web_page_preview=True)
        return
    plain = html.unescape(re.sub(r"<[^>]+>", "", r.text))   # long answers: plain text in chunks
    parts = [plain[i:i + TG_LIMIT] for i in range(0, len(plain), TG_LIMIT)]
    for i, p in enumerate(parts):
        await bot.send_message(chat_id, p, reply_markup=kb if i == len(parts) - 1 else None)


def svc(ctx: ContextTypes.DEFAULT_TYPE) -> Service:
    return ctx.application.bot_data["service"]


async def typing(update: Update, ctx):
    try:
        await ctx.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    except TelegramError:
        pass


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    payload = ctx.args[0] if ctx.args else ""
    if payload:
        await typing(update, ctx)
    for r in await svc(ctx).start(u.id, payload, u.language_code, u.username, u.full_name):
        await send_reply(ctx.bot, update.effective_chat.id, r)


async def cmd_pine(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s, uid = svc(ctx), update.effective_user.id
    req = " ".join(ctx.args).strip()
    if not req:
        user = await s.ensure_user(uid, update.effective_user.language_code)
        return await update.message.reply_text(t("pine_usage", s.lang(user)))
    await typing(update, ctx)
    await send_reply(ctx.bot, update.effective_chat.id, await s.pine(uid, req))


async def cmd_setup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s, uid = svc(ctx), update.effective_user.id
    text = " ".join(ctx.args).strip()
    if not text:
        user = await s.ensure_user(uid, update.effective_user.language_code)
        return await update.message.reply_text(t("setup_usage", s.lang(user)))
    await typing(update, ctx)
    r = await s.setup(uid, text)
    if r.pending_settings:
        ctx.user_data["pending_settings"] = r.pending_settings
    await send_reply(ctx.bot, update.effective_chat.id, r)


async def cmd_settier(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    r = await svc(ctx).set_tier(update.effective_user.id, ctx.args or [])
    await send_reply(ctx.bot, update.effective_chat.id, r)


async def cmd_tiers(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = svc(ctx)
    user = await s.ensure_user(update.effective_user.id, update.effective_user.language_code)
    await send_reply(ctx.bot, update.effective_chat.id, await s.tiers_reply(user))


async def cmd_lang(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = svc(ctx)
    user = await s.ensure_user(update.effective_user.id, update.effective_user.language_code)
    kb = [[("Қазақша", "lang:kz"), ("Русский", "lang:ru"), ("English", "lang:en")]]
    await send_reply(ctx.bot, update.effective_chat.id, Reply(t("lang_pick", s.lang(user)), kb))


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return
    await typing(update, ctx)
    await send_reply(ctx.bot, update.effective_chat.id, await svc(ctx).ask(update.effective_user.id, text[:2000]))


async def on_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    s, uid, data = svc(ctx), q.from_user.id, q.data or ""
    await q.answer()
    if data in ("set:yes", "set:no"):
        settings = ctx.user_data.pop("pending_settings", None)
        r = await s.confirm_settings(uid, settings, data == "set:yes")
        try:
            await q.edit_message_reply_markup(None)
        except TelegramError:
            pass
    elif data.startswith("lang:") and data[5:] in ("kz", "ru", "en"):
        r = await s.set_lang(uid, data[5:])
    elif data == "tiers":
        r = await s.tiers_reply(await s.ensure_user(uid))
    else:
        return
    await send_reply(ctx.bot, q.message.chat.id, r)


async def on_error(update, ctx):
    log.error("handler error", exc_info=ctx.error)


def build(cfg: Config) -> Application:
    app = Application.builder().token(cfg.bot_token).build()
    db = DB(cfg.supabase_url, cfg.supabase_key)

    async def notify_admins(text: str):
        for aid in cfg.admin_ids:
            try:
                await app.bot.send_message(aid, text)
            except TelegramError as e:
                log.warning("admin notify %s failed: %s", aid, e)

    ai = AI(AsyncAnthropic(api_key=cfg.anthropic_key), cfg, db, notify_admins)
    app.bot_data["service"] = Service(db, ai, cfg)

    async def post_init(a: Application):
        await ai.load_glossary()
        await a.bot.set_my_commands([
            BotCommand("start", "Бастау / Начать"),
            BotCommand("pine", "Pine Script код"),
            BotCommand("setup", "Алерт баптауы / Настройки алертов"),
            BotCommand("tiers", "Тарифтер / Тарифы"),
            BotCommand("lang", "Тіл / Язык / Language"),
        ])
        log.info("TREDIS AI started; admins configured: %d", len(cfg.admin_ids))

    async def post_shutdown(a: Application):
        await db.close()

    app.post_init = post_init
    app.post_shutdown = post_shutdown
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("pine", cmd_pine))
    app.add_handler(CommandHandler("setup", cmd_setup))
    app.add_handler(CommandHandler("settier", cmd_settier))
    app.add_handler(CommandHandler("tiers", cmd_tiers))
    app.add_handler(CommandHandler("lang", cmd_lang))
    app.add_handler(CallbackQueryHandler(on_cb))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    return app


def main():
    cfg = Config.from_env()
    missing = cfg.missing()
    if missing:
        sys.exit("Missing env vars: " + ", ".join(missing))
    build(cfg).run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
