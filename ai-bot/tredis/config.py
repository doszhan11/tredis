"""All settings come from environment variables. No secrets live in code."""
import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo


def _ids(raw: str) -> frozenset:
    return frozenset(int(x) for x in raw.replace(" ", "").split(",") if x.strip().lstrip("-").isdigit())


@dataclass(frozen=True)
class Config:
    bot_token: str = ""
    anthropic_key: str = ""
    supabase_url: str = ""
    supabase_key: str = ""
    admin_ids: frozenset = field(default_factory=frozenset)
    payment_contact: str = "@tredis_admin"
    model_chat: str = "claude-haiku-5-5"
    model_code: str = "claude-sonnet-5-5"
    max_tokens_chat: int = 1500
    max_tokens_code: int = 6000
    monthly_budget_usd: float = 50.0
    budget_alert_ratio: float = 0.8
    free_msgs_day: int = 3          # AI messages a day for users without a valid tier (tier = none)
    test_mode: bool = False         # hide prices, payment contact and the «Перейти на Pro AI» button
    tz: ZoneInfo = ZoneInfo("Asia/Almaty")

    @classmethod
    def from_env(cls) -> "Config":
        e = os.environ.get
        return cls(
            bot_token=e("AI_BOT_TOKEN", "").strip(),
            anthropic_key=e("ANTHROPIC_API_KEY", "").strip(),
            supabase_url=e("SUPABASE_URL", "").strip().rstrip("/"),
            supabase_key=e("SUPABASE_KEY", "").strip(),
            admin_ids=_ids(e("ADMIN_IDS", "")),
            payment_contact=e("PAYMENT_CONTACT", "@tredis_admin").strip(),
            model_chat=e("MODEL_CHAT", "claude-haiku-5-5").strip(),
            model_code=e("MODEL_CODE", "claude-sonnet-5-5").strip(),
            max_tokens_chat=int(e("MAX_TOKENS_CHAT", "1500")),
            max_tokens_code=int(e("MAX_TOKENS_CODE", "6000")),
            monthly_budget_usd=float(e("MONTHLY_BUDGET_USD", "50")),
            budget_alert_ratio=float(e("BUDGET_ALERT_RATIO", "0.8")),
            free_msgs_day=int(e("FREE_MSGS_DAY", "3")),
            test_mode=e("TEST_MODE", "").strip().lower() in ("1", "true", "yes"),
            tz=ZoneInfo(e("TZ_NAME", "Asia/Almaty")),
        )

    def missing(self) -> list:
        need = {"AI_BOT_TOKEN": self.bot_token, "ANTHROPIC_API_KEY": self.anthropic_key,
                "SUPABASE_URL": self.supabase_url, "SUPABASE_KEY": self.supabase_key}
        out = [k for k, v in need.items() if not v]
        if not self.admin_ids:
            out.append("ADMIN_IDS")
        return out
