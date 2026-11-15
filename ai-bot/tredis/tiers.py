"""Tiers and limits. Pure functions so they are easy to test.

Tier values come from the shared TREDIS database: users.tier in (none, start, pro, vip, lifetime).
start/pro/vip are paid subscriptions valid while paid_until is in the future; lifetime gets Pro AI
limits until lifetime_trial_until (set to +7 days by /settier), then Start limits.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

TIERS = ("none", "start", "pro", "vip", "lifetime")


@dataclass(frozen=True)
class Limits:
    msgs_day: int
    code_month: int   # 0 = Pine codes not available


def limits_table(free_msgs_day: int = 3) -> dict:
    return {
        "none": Limits(msgs_day=free_msgs_day, code_month=0),
        "start": Limits(msgs_day=3, code_month=0),
        "pro": Limits(msgs_day=30, code_month=10),
        "vip": Limits(msgs_day=100, code_month=50),
    }


def parse_ts(v) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def effective_tier(user: Optional[dict], now: datetime) -> str:
    """Which limit row applies right now: none, start, pro or vip."""
    if not user:
        return "none"
    tier = user.get("tier") or "none"
    if tier in ("start", "pro", "vip"):
        until = parse_ts(user.get("paid_until"))
        return tier if until and until > now else "none"
    if tier == "lifetime":
        trial = parse_ts(user.get("lifetime_trial_until"))
        return "pro" if trial and now < trial else "start"
    return "none"


def has_paid_tier(user: Optional[dict], now: datetime) -> bool:
    if not user:
        return False
    if user.get("tier") == "lifetime":
        return True
    return effective_tier(user, now) in ("start", "pro", "vip")


@dataclass(frozen=True)
class Check:
    ok: bool
    reason: str          # "" | "msgs" | "code_locked" | "code"
    msgs_left: int
    code_left: int


def check(lim: Limits, usage: dict, is_code: bool = False) -> Check:
    """usage = {"msgs_day": today's messages, "code_month": this month's Pine requests}."""
    msgs_left = max(0, lim.msgs_day - int(usage.get("msgs_day") or 0))
    code_left = max(0, lim.code_month - int(usage.get("code_month") or 0))
    if msgs_left <= 0:
        return Check(False, "msgs", msgs_left, code_left)
    if is_code and lim.code_month == 0:
        return Check(False, "code_locked", msgs_left, code_left)
    if is_code and code_left <= 0:
        return Check(False, "code", msgs_left, code_left)
    return Check(True, "", msgs_left, code_left)
