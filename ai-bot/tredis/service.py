"""Bot logic without Telegram: every method returns a Reply that bot.py sends."""
import html
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import tiers
from .texts import TIER_NAME, lang_from_tg, t

log = logging.getLogger("tredis.service")

LIFETIME_PRO_DAYS = 7
INTENTS = {"question": "question", "alert": "explain_alert", "settings": "settings", "pine": "code"}


@dataclass
class Reply:
    text: str
    buttons: list = field(default_factory=list)   # rows of (label, callback_data) or (label, None, url)
    pending_settings: Optional[dict] = None


_FENCE = re.compile(r"```[a-zA-Z0-9_+-]*\n?(.*?)```", re.S)


def to_html(s: str) -> str:
    """Escape model output for Telegram HTML; ``` blocks become <pre><code>."""
    out, pos = [], 0
    for m in _FENCE.finditer(s):
        out.append(html.escape(s[pos:m.start()]))
        out.append("<pre><code>" + html.escape(m.group(1).rstrip()) + "</code></pre>")
        pos = m.end()
    out.append(html.escape(s[pos:]))
    return "".join(out).strip()


class Service:
    def __init__(self, db, ai, cfg):
        self.db, self.ai, self.cfg = db, ai, cfg
        self.limits = tiers.limits_table(cfg.free_msgs_day)

    def now(self) -> datetime:
        return datetime.now(self.cfg.tz)

    def usage_day(self):
        """add_ai_usage() stamps rows with Postgres current_date (UTC), so read the same day."""
        return self.now().astimezone(timezone.utc).date()

    # ------------------------------------------------------------ users
    async def ensure_user(self, tg_id: int, tg_lang=None, username=None, full_name=None) -> dict:
        user = await self.db.get_user(tg_id)
        if user is None:
            user = {"tg_id": tg_id, "lang": lang_from_tg(tg_lang), "username": username, "full_name": full_name}
            await self.db.upsert_user(user)
            user["tier"] = "none"
        return user

    def lang(self, user: Optional[dict]) -> str:
        return (user or {}).get("lang") or "kk"

    def contact(self) -> str:
        return html.escape(self.cfg.payment_contact)

    def pro_button(self, lang: str) -> list:
        if self.cfg.test_mode:
            return []
        c = self.cfg.payment_contact
        if c.startswith("@"):
            return [[(t("btn_pro", lang), None, f"https://t.me/{c[1:]}")]]
        if c.startswith("http"):
            return [[(t("btn_pro", lang), None, c)]]
        return [[(t("btn_pro", lang), "tiers")]]

    def free_line(self, lang: str) -> str:
        n = self.limits["none"].msgs_day
        return t("free_on", lang, n=n) if n > 0 else t("free_off", lang)

    async def tiers_text(self, lang: str) -> str:
        try:
            products = {p["code"]: p for p in await self.db.get_products()}
        except Exception:
            log.exception("products load failed")
            products = {}
        lines = [t("tiers_head", lang)]
        for code in ("start", "pro", "vip", "lifetime"):
            p = {} if self.cfg.test_mode else products.get(code, {})
            name = html.escape(products.get(code, {}).get("name") or TIER_NAME[code])
            price = f" — {int(p['price_kzt']):,} ₸".replace(",", " ") if p.get("price_kzt") else ""
            if price and p.get("period_days"):
                price += t("per_days", lang, n=p["period_days"])
            if code == "lifetime":
                lim = t("lim_lifetime", lang)
            else:
                lt = self.limits[code]
                lim = t("lim_msgs", lang, n=lt.msgs_day) + (", " + t("lim_code", lang, n=lt.code_month)
                                                             if lt.code_month else "")
            lines.append(f"• {name}{price}: {lim}")
        lines += ["", t("test_note", lang) if self.cfg.test_mode else t("tiers_foot", lang, contact=self.contact())]
        return "\n".join(lines)

    async def tiers_reply(self, user) -> Reply:
        lang = self.lang(user)
        return Reply(await self.tiers_text(lang), self.pro_button(lang))

    # ------------------------------------------------------------ /start
    async def start(self, tg_id: int, payload: str = "", tg_lang=None, username=None, full_name=None) -> list:
        user = await self.ensure_user(tg_id, tg_lang, username, full_name)
        lang, now = self.lang(user), self.now()
        name = html.escape(full_name or user.get("full_name") or "")
        m = re.fullmatch(r"alert_(\d+)", (payload or "").strip())
        if m:
            return [await self.explain_alert(tg_id, int(m.group(1)))]
        if tiers.has_paid_tier(user, now):
            until = tiers.parse_ts(user.get("paid_until"))
            until_s = t("until", lang, date=until.astimezone(self.cfg.tz).strftime("%d.%m.%Y")) \
                if until and user.get("tier") != "lifetime" else ""
            return [Reply(t("welcome_paid", lang, name=name, tier=TIER_NAME[user["tier"]],
                            until=until_s, help=t("help", lang)))]
        return [Reply(t("welcome_free", lang, name=name, free=self.free_line(lang),
                        tiers=await self.tiers_text(lang), help=t("help", lang)), self.pro_button(lang))]

    # ------------------------------------------------------------ metered AI actions
    async def _metered(self, tg_id: int, kind: str, text: str, run, is_code=False) -> Reply:
        user = await self.ensure_user(tg_id)
        lang, now = self.lang(user), self.now()
        lim = self.limits[tiers.effective_tier(user, now)]
        usage = await self.db.get_usage(tg_id, self.usage_day())
        chk = tiers.check(lim, usage, is_code=is_code)
        if not chk.ok:
            msg = {"msgs": t("limit_msgs", lang, limit=lim.msgs_day),
                   "code_locked": t("limit_code_locked", lang),
                   "code": t("limit_code", lang, limit=lim.code_month)}[chk.reason]
            return Reply(msg, self.pro_button(lang))
        try:
            res, reply = await run(user, lang)
        except Exception:
            log.exception("AI call failed (%s)", kind)
            return Reply(t("ai_error", lang))
        if reply is None:
            if res.refused:
                body = t("refused", lang)
            else:
                body = to_html(res.text) + ("\n" + t("truncated", lang) if res.truncated else "")
            reply = Reply(body)
        try:
            await self.db.add_usage(tg_id, 1, 1 if is_code else 0, res.tokens_in, res.tokens_out)
        except Exception:
            log.exception("add_ai_usage failed")
        consent = bool(user.get("consent_ai_log"))
        try:
            await self.db.log({"tg_id": tg_id, "message": text if consent else "", "intent": INTENTS[kind],
                               "slots": res.slots, "answer": res.text if consent else None, "model": res.model,
                               "tokens_in": res.tokens_in, "tokens_out": res.tokens_out,
                               "latency_ms": res.latency_ms})
        except Exception:
            log.exception("ai_log insert failed")
        left = max(0, lim.msgs_day - usage["msgs_day"] - 1)
        footer = "\n\n<i>" + t("left_today", lang, n=left)
        if is_code:
            footer += " · " + t("code_left", lang, n=max(0, lim.code_month - usage["code_month"] - 1))
        reply.text += footer + "</i>"
        if left == 0:
            reply.buttons = reply.buttons + self.pro_button(lang)
        return reply

    async def ask(self, tg_id: int, question: str) -> Reply:
        async def run(user, lang):
            chunks = await self.db.search_lessons(question, 5)
            return await self.ai.answer_lesson(question, chunks), None
        return await self._metered(tg_id, "question", question, run)

    async def explain_alert(self, tg_id: int, alert_id: int) -> Reply:
        alert = await self.db.get_alert(alert_id)
        if not alert:
            user = await self.ensure_user(tg_id)
            return Reply(t("alert_missing", self.lang(user), id=alert_id))

        async def run(user, lang):
            return await self.ai.explain_alert(alert, lang), None
        return await self._metered(tg_id, "alert", f"alert_{alert_id}", run)

    async def pine(self, tg_id: int, request: str) -> Reply:
        async def run(user, lang):
            return await self.ai.write_pine(request), None
        return await self._metered(tg_id, "pine", request, run, is_code=True)

    async def setup(self, tg_id: int, text: str) -> Reply:
        async def run(user, lang):
            res = await self.ai.parse_settings(text)
            if not res.slots:
                return res, Reply(t("setup_failed", lang))
            return res, Reply(t("setup_confirm", lang, s=self.settings_text(res.slots, lang)),
                              [[(t("btn_yes", lang), "set:yes"), (t("btn_no", lang), "set:no")]],
                              pending_settings=res.slots)
        return await self._metered(tg_id, "settings", text, run)

    def settings_text(self, s: dict, lang: str) -> str:
        shown = {k: html.escape(str(s.get(k) or "—")) for k in ("market", "sweep_tf", "mss_tf", "direction")}
        return t("setup_fields", lang, **shown)

    async def confirm_settings(self, tg_id: int, settings: Optional[dict], yes: bool) -> Reply:
        user = await self.ensure_user(tg_id)
        lang = self.lang(user)
        if not yes:
            return Reply(t("setup_cancel", lang))
        if not settings or not settings.get("market"):
            return Reply(t("setup_expired", lang))
        await self.db.save_market(tg_id, settings)
        return Reply(t("setup_saved", lang) + "\n" + self.settings_text(settings, lang))

    async def set_lang(self, tg_id: int, lang: str) -> Reply:
        await self.ensure_user(tg_id)
        await self.db.upsert_user({"tg_id": tg_id, "lang": lang})
        return Reply(t("lang_set", lang))

    # ------------------------------------------------------------ admin
    async def set_tier(self, admin_id: int, args: list) -> Reply:
        if admin_id not in self.cfg.admin_ids:
            return Reply(t("not_admin", "kk"))
        usage = "Қолданылуы: /settier &lt;tg_id&gt; &lt;none|start|pro|vip|lifetime&gt; &lt;күн&gt;"
        if len(args) != 3 or not args[0].isdigit() or args[1].lower() not in tiers.TIERS or not args[2].isdigit():
            return Reply(usage)
        tg_id, tier, days = int(args[0]), args[1].lower(), int(args[2])
        if tier in ("start", "pro", "vip") and days <= 0:
            return Reply(usage)
        now = self.now()
        row = {"tg_id": tg_id, "tier": tier, "paid_until": None}
        if tier in ("start", "pro", "vip"):
            row["paid_until"] = (now + timedelta(days=days)).isoformat()
        if tier == "lifetime":
            row["lifetime_trial_until"] = (now + timedelta(days=LIFETIME_PRO_DAYS)).isoformat()
        await self.db.upsert_user(row)
        until = f", {(now + timedelta(days=days)).strftime('%d.%m.%Y')} дейін" if row["paid_until"] else ""
        note = f" (Pro AI {(now + timedelta(days=LIFETIME_PRO_DAYS)).strftime('%d.%m.%Y')} дейін, кейін Start)" \
            if tier == "lifetime" else ""
        return Reply(f"✅ {tg_id}: <b>{TIER_NAME[tier]}</b>{until}{note}")
