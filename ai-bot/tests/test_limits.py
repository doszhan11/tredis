from datetime import timedelta

import pytest

from tredis import tiers
from tests.conftest import NOW
from tests.fakes import text_resp

LIM = tiers.limits_table(3)


def user(tier="none", days=None, trial_days=None, lang="ru"):
    u = {"tg_id": 1, "tier": tier, "lang": lang, "paid_until": None, "lifetime_trial_until": None}
    if days is not None:
        u["paid_until"] = (NOW + timedelta(days=days)).isoformat()
    if trial_days is not None:
        u["lifetime_trial_until"] = (NOW + timedelta(days=trial_days)).isoformat()
    return u


# ---------------------------------------------------------------- pure limit logic
@pytest.mark.parametrize("tier,expected", [("start", 3), ("pro", 30), ("vip", 100)])
def test_daily_message_limits(tier, expected):
    lim = LIM[tier]
    for used in range(expected):
        assert tiers.check(lim, {"msgs_day": used, "code_month": 0}).ok
    c = tiers.check(lim, {"msgs_day": expected, "code_month": 0})
    assert not c.ok and c.reason == "msgs" and c.msgs_left == 0


@pytest.mark.parametrize("tier,expected", [("pro", 10), ("vip", 50)])
def test_monthly_code_limits(tier, expected):
    lim = LIM[tier]
    assert tiers.check(lim, {"msgs_day": 0, "code_month": expected - 1}, is_code=True).ok
    c = tiers.check(lim, {"msgs_day": 0, "code_month": expected}, is_code=True)
    assert not c.ok and c.reason == "code"


@pytest.mark.parametrize("tier", ["none", "start"])
def test_no_pine_without_pro(tier):
    c = tiers.check(LIM[tier], {"msgs_day": 0, "code_month": 0}, is_code=True)
    assert not c.ok and c.reason == "code_locked"


def test_free_messages_are_configurable():
    assert tiers.limits_table(0)["none"].msgs_day == 0
    assert not tiers.check(tiers.limits_table(0)["none"], {"msgs_day": 0}).ok


# ---------------------------------------------------------------- service-level metering
async def test_footer_counts_and_rpc(env):
    env.client.responses = [text_resp("Sweep деген...")]
    r = await env.svc.ask(1, "Sweep деген не?")
    assert "Бүгін қалды: 2" in r.text
    row = env.db.ai_usage[(1, env.db.today)]
    assert row == {"msgs": 1, "code_requests": 0, "tokens_in": 100, "tokens_out": 50}
    log = env.db.logs[0]
    assert log["intent"] == "question" and log["model"] == "claude-haiku-5-5"
    assert log["tokens_in"] == 100 and log["tokens_out"] == 50


async def test_log_text_only_with_consent(env):
    await env.svc.ask(1, "secret question")
    assert env.db.logs[0]["message"] == "" and env.db.logs[0]["answer"] is None
    env.db.users[1]["consent_ai_log"] = True
    await env.svc.ask(1, "open question")
    assert env.db.logs[1]["message"] == "open question" and env.db.logs[1]["answer"] == "ok"


async def test_usage_day_is_utc(env):
    # 03:00 Almaty on the 16th is still the 15th in UTC, which is the day add_ai_usage() writes.
    from datetime import datetime
    env.clock.now = datetime(2026, 11, 16, 3, 0, tzinfo=NOW.tzinfo)
    assert env.svc.usage_day().isoformat() == "2026-11-15"


async def test_russian_footer(env):
    env.db.users[1] = user("none")
    r = await env.svc.ask(1, "Что такое MSS?")
    assert "Осталось сегодня: 2" in r.text


async def test_limit_reached_shows_pro_button_and_skips_ai(env):
    env.db.users[1] = user("none")
    for _ in range(3):
        r = await env.svc.ask(1, "q")
    assert "Осталось сегодня: 0" in r.text
    assert any(b[0] == "Перейти на Pro AI" for row in r.buttons for b in row)
    calls = len(env.client.calls)
    r = await env.svc.ask(1, "q")
    assert len(env.client.calls) == calls                                     # no AI call
    assert "Лимит" in r.text
    btn = r.buttons[0][0]
    assert btn[0] == "Перейти на Pro AI" and btn[2] == "https://t.me/tredis_pay"


async def test_no_free_messages(make_env):
    env = make_env(free=0)
    r = await env.svc.ask(1, "q")
    assert env.client.calls == [] and r.buttons


async def test_ai_error_does_not_consume_limit(make_env):
    env = make_env(error=RuntimeError("boom"))
    r = await env.svc.ask(1, "q")
    assert "Лимит жұмсалмады" in r.text
    assert env.db.ai_usage == {} and env.db.logs == []


async def test_pine_counts_code_and_uses_sonnet(env):
    env.db.users[1] = user("pro", days=5)
    env.client.responses = [text_resp("```pine\n//@version=6\nindicator('x')\n```", model="claude-sonnet-5-5")]
    r = await env.svc.pine(1, "FVG indicator")
    call = env.client.calls[-1]
    assert call["model"] == "claude-sonnet-5-5" and call["max_tokens"] == env.cfg.max_tokens_code
    assert call["fallbacks"] == "default"
    row = env.db.ai_usage[(1, env.db.today)]
    assert row["code_requests"] == 1 and row["msgs"] == 1
    assert env.db.logs[0]["intent"] == "code"
    assert "<pre><code>//@version=6" in r.text
    assert "Pine-кодов в этом месяце: 9" in r.text


async def test_monthly_code_counts_earlier_days(env):
    env.db.users[1] = user("pro", days=5)
    await env.db.add_usage(1, 1, 10, 0, 0, day=env.db.today - timedelta(days=3))
    r = await env.svc.pine(1, "x")
    assert env.client.calls == [] and "Лимит Pine" in r.text


async def test_start_and_none_cannot_pine(env):
    for u in (user("none"), user("start", days=5)):
        env.db.users[1] = u
        r = await env.svc.pine(1, "x")
        assert env.client.calls == [] and "Pro AI" in r.text


async def test_refusal_message(env):
    env.client.responses = [text_resp("", stop="refusal")]
    r = await env.svc.ask(1, "q")
    assert "жауап бере алмаймын" in r.text


# ---------------------------------------------------------------- models / caching / budget / glossary
async def test_chat_uses_haiku_with_cached_system_prompt(env):
    await env.svc.ask(1, "Sweep?")
    call = env.client.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert call["max_tokens"] == env.cfg.max_tokens_chat
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "fallbacks" not in call


async def test_glossary_from_db_goes_into_system_prompt(env):
    env.db.glossary = [{"term": "entry", "kk": "MSS свечасы денесінің шеті.", "ru": "Край тела свечи MSS.", "en": None}]
    await env.ai.load_glossary()
    await env.svc.ask(1, "Entry?")
    system = env.client.calls[0]["system"][0]["text"]
    assert "- entry: kk: MSS свечасы денесінің шеті. | ru: Край тела свечи MSS." in system
    assert "Sweep: price wicks" not in system


async def test_budget_alert_at_80_percent_once(make_env):
    from tests.fakes import usage as U
    # Each Sonnet call: 100k in ($0.20) + 20k out ($0.20) = $0.40. Budget $1 → 80% at the 2nd call.
    big = lambda: text_resp("```pine\n//@version=6\n```", model="claude-sonnet-5-5", u=U(100_000, 20_000))  # noqa: E731
    env = make_env(big(), big(), big(), budget=1.0)
    env.db.users[1] = user("vip", days=5)
    await env.svc.pine(1, "a")
    assert env.notified == []
    await env.svc.pine(1, "b")
    assert len(env.notified) == 1 and "80%" in env.notified[0]
    await env.svc.pine(1, "c")
    assert len(env.notified) == 1
