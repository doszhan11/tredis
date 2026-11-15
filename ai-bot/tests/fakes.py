"""In-memory stand-ins for Supabase (DB) and the Anthropic client."""
from types import SimpleNamespace


class FakeDB:
    """Mimics the shared TREDIS schema: users, ai_usage (+ add_ai_usage, ai_usage_month), ai_log,
    alerts, lessons_kb, glossary, products, user_markets."""

    def __init__(self):
        self.users, self.ai_usage, self.alerts, self.logs = {}, {}, {}, []
        self.lessons, self.markets, self.searches = [], {}, []
        self.glossary = []
        self.products = [
            {"code": "start", "kind": "subscription", "name": "Start", "price_kzt": 30000, "period_days": 30},
            {"code": "pro", "kind": "subscription", "name": "Pro AI", "price_kzt": 50000, "period_days": 30},
            {"code": "vip", "kind": "subscription", "name": "VIP", "price_kzt": 100000, "period_days": 30},
            {"code": "lifetime", "kind": "lifetime", "name": "Пожизненный доступ", "price_kzt": 50000,
             "period_days": None},
        ]

    async def get_user(self, tg_id):
        u = self.users.get(tg_id)
        return dict(u) if u else None

    async def upsert_user(self, row):
        base = {"tier": "none", "lang": "kk", "paid_until": None, "lifetime_trial_until": None,
                "consent_ai_log": False}
        self.users.setdefault(row["tg_id"], base).update(row)

    async def get_usage(self, tg_id, day):
        today = self.ai_usage.get((tg_id, day))
        month = sum(r["code_requests"] for (tid, d), r in self.ai_usage.items()
                    if tid == tg_id and (d.year, d.month) == (day.year, day.month))
        return {"msgs_day": today["msgs"] if today else 0, "code_month": month}

    async def add_usage(self, tg_id, msgs, code, tokens_in, tokens_out, day=None):
        day = day or self.today
        r = self.ai_usage.setdefault((tg_id, day), {"msgs": 0, "code_requests": 0, "tokens_in": 0, "tokens_out": 0})
        r["msgs"] += msgs
        r["code_requests"] += code
        r["tokens_in"] += tokens_in
        r["tokens_out"] += tokens_out

    async def log(self, row):
        self.logs.append(dict(row))

    async def month_spend_rows(self, since_iso):
        return [{"model": r["model"], "tokens_in": r["tokens_in"], "tokens_out": r["tokens_out"]} for r in self.logs]

    async def get_alert(self, alert_id):
        a = self.alerts.get(alert_id)
        return dict(a, id=alert_id) if a else None

    async def search_lessons(self, q, k=5):
        self.searches.append((q, k))
        return self.lessons[:k]

    async def get_glossary(self):
        return self.glossary

    async def get_products(self):
        return self.products

    async def save_market(self, tg_id, s):
        self.markets[(tg_id, s["market"])] = dict(s)


def usage(inp=100, out=50, cw=0, cr=0):
    return SimpleNamespace(input_tokens=inp, output_tokens=out,
                           cache_creation_input_tokens=cw, cache_read_input_tokens=cr)


def text_resp(text, model="claude-haiku-5-5", stop="end_turn", u=None):
    return SimpleNamespace(model=model, stop_reason=stop, usage=u or usage(),
                           content=[SimpleNamespace(type="thinking", thinking=""),
                                    SimpleNamespace(type="text", text=text)])


def tool_resp(inp, name="save_alert_settings"):
    return SimpleNamespace(model="claude-haiku-5-5", stop_reason="tool_use", usage=usage(),
                           content=[SimpleNamespace(type="text", text="Parsing."),
                                    SimpleNamespace(type="tool_use", id="tu_1", name=name, input=inp)])


class _Messages:
    def __init__(self, owner):
        self.owner = owner

    async def create(self, **kw):
        self.owner.calls.append(kw)
        if self.owner.error:
            raise self.owner.error
        r = self.owner.responses.pop(0) if self.owner.responses else text_resp("ok")
        return r


class FakeAnthropic:
    def __init__(self, *responses, error=None):
        self.responses = list(responses)
        self.calls = []
        self.error = error
        self.messages = _Messages(self)
        self.beta = SimpleNamespace(messages=_Messages(self))
