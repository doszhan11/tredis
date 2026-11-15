"""Anthropic calls: lesson Q&A, alert explanation, Pine code, text → settings (tool use), budget."""
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable, Optional

from . import prompts
from .config import Config

log = logging.getLogger("tredis.ai")

# Same values as the CHECK constraints on public.user_markets.
MARKETS = ["XAUUSD", "XAUEUR", "BTCUSD", "XAGUSD", "GBPUSD", "EURUSD", "GER40", "AUDUSD", "USDJPY", "CADJPY"]
TFS = ["1", "3", "5", "15", "30", "60", "240"]
DIRECTIONS = ["LONG", "SHORT", "BOTH"]

# USD per 1M tokens (input, output). ai_log keeps only tokens_in/tokens_out, so cached input is
# billed here at the full input price: the estimate errs on the high side.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-5-5": (4.00, 20.00),
}
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SETTINGS_TOOL = {
    "name": "save_alert_settings",
    "description": ("Record the student's alert preferences parsed from their message: market symbol, "
                    "sweep timeframe, MSS timeframe and trade direction. Use NONE for anything not stated."),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "market": {"type": "string", "enum": MARKETS + ["NONE"]},
            "sweep_tf": {"type": "string", "enum": TFS + ["NONE"]},
            "mss_tf": {"type": "string", "enum": TFS + ["NONE"]},
            "direction": {"type": "string", "enum": DIRECTIONS + ["NONE"]},
        },
        "required": ["market", "sweep_tf", "mss_tf", "direction"],
        "additionalProperties": False,
    },
}


@dataclass
class Result:
    text: str
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    refused: bool = False
    truncated: bool = False
    slots: Optional[dict] = None


def _u(usage, k) -> int:
    return int(getattr(usage, k, 0) or 0)


def tokens_in_out(usage):
    tin = _u(usage, "input_tokens") + _u(usage, "cache_creation_input_tokens") + _u(usage, "cache_read_input_tokens")
    return tin, _u(usage, "output_tokens")


def cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    pin, pout = PRICES.get(model or "", PRICES["claude-sonnet-5-5"])
    return (tokens_in * pin + tokens_out * pout) / 1_000_000


def text_of(resp) -> str:
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()


def validate_settings(raw) -> Optional[dict]:
    """Keep only values the user_markets constraints accept. A market is required (it is the key)."""
    if not isinstance(raw, dict):
        return None
    allowed = {"market": MARKETS, "sweep_tf": TFS, "mss_tf": TFS, "direction": DIRECTIONS}
    out = {}
    for k, opts in allowed.items():
        v = raw.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            v = str(int(v))
        if isinstance(v, str):
            v = v.strip().upper() if k in ("market", "direction") else v.strip()
        out[k] = v if v in opts else None
    if out["market"] is None:
        return None
    out["direction"] = out["direction"] or "BOTH"
    return out


def _f(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _derive_one(dir_, entry, stop, tps: dict, extra: dict) -> dict:
    e, sl = _f(entry), _f(stop)
    short = str(dir_ or "").upper() == "SHORT"
    d = dict(extra, dir=dir_)
    if e is None or sl is None:
        return d
    risk = (sl - e) if short else (e - sl)
    d["risk_points"] = round(risk, 5)
    for name, tp in tps.items():
        tp = _f(tp)
        if tp is None or risk <= 0:
            continue
        gain = (e - tp) if short else (tp - e)
        if gain > 0:
            d[f"{name}_points"] = round(gain, 5)
            d[f"{name}_rr"] = f"1:{gain / risk:.1f}"
    return d


def derive_alert(alert: dict) -> list:
    """RR and distances computed in code so the model never does arithmetic.

    Works for the alerts table row (entry/stop/tp1..tp4 columns) and for the Genesis Sweep
    JSON (events:[{entry, sl, tp1, tp2}])."""
    if alert.get("entry") is not None:
        tps = {f"tp{i}": alert.get(f"tp{i}") for i in range(1, 5)}
        return [_derive_one(alert.get("dir"), alert.get("entry"), alert.get("stop"), tps,
                            {"sweep_tf": alert.get("sweep_tf"), "mss_tf": alert.get("mss_tf")})]
    return [_derive_one(ev.get("dir"), ev.get("entry"), ev.get("sl"),
                        {"tp1": ev.get("tp1"), "tp2": ev.get("tp2")}, {"tf": ev.get("tf")})
            for ev in alert.get("events") or []]


def alert_payload(row: dict) -> dict:
    """What the model sees: non-empty columns of the alerts row plus the raw TradingView JSON."""
    cols = {k: v for k, v in row.items() if k != "raw" and v not in (None, "")}
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else None
    return {"fields": cols, "raw": raw} if raw else {"fields": cols}


class AI:
    def __init__(self, client, cfg: Config, db, notify_admins: Callable[[str], Awaitable[None]]):
        self.client = client      # anthropic.AsyncAnthropic (or a fake in tests)
        self.cfg = cfg
        self.db = db
        self.notify_admins = notify_admins
        self.system_prompt = prompts.SYSTEM_PROMPT
        self._month = None        # "YYYY-MM" the running spend belongs to
        self._spent = 0.0
        self._alerted = False

    async def load_glossary(self):
        try:
            rows = await self.db.get_glossary()
            if rows:
                self.system_prompt = prompts.build_system_prompt(rows)
                log.info("glossary loaded: %d terms", len(rows))
        except Exception:
            log.exception("glossary load failed; using built-in glossary")

    @property
    def _system(self):
        return [{"type": "text", "text": self.system_prompt, "cache_control": {"type": "ephemeral"}}]

    async def _call(self, *, code: bool, user_text: str, tools=None) -> tuple:
        kw = dict(
            model=self.cfg.model_code if code else self.cfg.model_chat,
            max_tokens=self.cfg.max_tokens_code if code else self.cfg.max_tokens_chat,
            system=self._system,
            messages=[{"role": "user", "content": user_text}],
            output_config={"effort": "medium" if code else "low"},
        )
        if tools:
            kw["tools"] = tools
            kw["tool_choice"] = {"type": "auto"}
        t0 = time.monotonic()
        if code:  # server-side refusal fallback is available for Sonnet 5.5, not for Haiku
            kw["betas"] = [FALLBACK_BETA]
            kw["fallbacks"] = "default"
            resp = await self.client.beta.messages.create(**kw)
        else:
            resp = await self.client.messages.create(**kw)
        latency = int((time.monotonic() - t0) * 1000)
        await self._track_budget(resp)
        return resp, latency

    # ------------------------------------------------------------ budget (from ai_log, kept in memory)
    async def _track_budget(self, resp):
        try:
            now = datetime.now(self.cfg.tz)
            month = now.strftime("%Y-%m")
            threshold = self.cfg.monthly_budget_usd * self.cfg.budget_alert_ratio
            if self._month != month:
                start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                rows = await self.db.month_spend_rows(start.isoformat())
                self._spent = sum(cost_usd(r.get("model"), int(r.get("tokens_in") or 0),
                                           int(r.get("tokens_out") or 0)) for r in rows)
                self._month = month
                self._alerted = self._spent >= threshold   # already past it before a restart: do not repeat
            tin, tout = tokens_in_out(resp.usage)
            self._spent += cost_usd(getattr(resp, "model", ""), tin, tout)
            if not self._alerted and self._spent >= threshold:
                self._alerted = True
                limit = self.cfg.monthly_budget_usd
                await self.notify_admins(
                    f"⚠️ TREDIS AI: бұл айдың Anthropic бюджетінің {self._spent / limit:.0%} жұмсалды "
                    f"(≈${self._spent:.2f} / ${limit:.2f}).")
        except Exception:
            log.exception("budget tracking failed")

    def _result(self, resp, latency: int) -> Result:
        tin, tout = tokens_in_out(resp.usage)
        r = Result("", getattr(resp, "model", ""), tin, tout, latency)
        if resp.stop_reason == "refusal":
            r.refused = True
        else:
            r.text = text_of(resp)
            r.truncated = resp.stop_reason == "max_tokens"
        return r

    async def answer_lesson(self, question: str, chunks: list) -> Result:
        ex = "\n".join(f'<excerpt lesson="{c.get("lesson", "")}">{c.get("content", "")}</excerpt>'
                       for c in chunks) or "(no matching excerpts)"
        return self._result(*await self._call(
            code=False, user_text=prompts.LESSON_TASK.format(excerpts=ex, question=question)))

    async def explain_alert(self, row: dict, lang: str) -> Result:
        raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
        derived = derive_alert(row) if row.get("entry") is not None else derive_alert(raw)
        text = prompts.ALERT_TASK.format(
            lang_name=prompts.LANG_NAME.get(lang, "Kazakh"),
            alert=json.dumps(alert_payload(row), ensure_ascii=False, sort_keys=True, default=str),
            derived=json.dumps(derived, ensure_ascii=False, sort_keys=True))
        return self._result(*await self._call(code=False, user_text=text))

    async def write_pine(self, request: str) -> Result:
        return self._result(*await self._call(code=True, user_text=prompts.PINE_TASK.format(request=request)))

    async def parse_settings(self, text: str) -> Result:
        """Result.slots holds the validated settings (or None if nothing usable was parsed)."""
        resp, latency = await self._call(code=False, user_text=prompts.SETTINGS_TASK.format(text=text),
                                         tools=[SETTINGS_TOOL])
        r = self._result(resp, latency)
        for b in resp.content:
            if getattr(b, "type", "") == "tool_use" and b.name == SETTINGS_TOOL["name"]:
                raw = b.input if isinstance(b.input, dict) else json.loads(b.input)
                r.slots = validate_settings(raw)
                break
        return r
