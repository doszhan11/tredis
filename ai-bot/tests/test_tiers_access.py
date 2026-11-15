from datetime import timedelta

from tredis import tiers
from tests.conftest import NOW
from tests.fakes import text_resp


def test_effective_tier_paid_and_expired():
    assert tiers.effective_tier({"tier": "pro", "paid_until": (NOW + timedelta(days=1)).isoformat()}, NOW) == "pro"
    assert tiers.effective_tier({"tier": "start", "paid_until": (NOW + timedelta(days=1)).isoformat()}, NOW) == "start"
    assert tiers.effective_tier({"tier": "vip", "paid_until": (NOW - timedelta(seconds=1)).isoformat()}, NOW) == "none"
    assert tiers.effective_tier({"tier": "pro"}, NOW) == "none"          # no paid_until
    assert tiers.effective_tier({"tier": "none"}, NOW) == "none"
    assert tiers.effective_tier(None, NOW) == "none"


def test_lifetime_is_pro_until_trial_end_then_start():
    u = {"tier": "lifetime", "lifetime_trial_until": (NOW + timedelta(days=7)).isoformat()}
    assert tiers.effective_tier(u, NOW + timedelta(days=6, hours=23)) == "pro"
    assert tiers.effective_tier(u, NOW + timedelta(days=7)) == "start"
    assert tiers.effective_tier({"tier": "lifetime"}, NOW) == "start"
    assert tiers.has_paid_tier(u, NOW + timedelta(days=400))


async def test_start_without_paid_tier_shows_tiers_with_prices(env):
    replies = await env.svc.start(5, "", "ru", "bob", "Bob B")
    assert len(replies) == 1
    r = replies[0]
    assert "Тарифы" in r.text and "@tredis_pay" in r.text
    assert "Pro AI — 50 000 ₸ / 30 дн.: 30 сообщений в день, 10 Pine-кодов в месяц" in r.text
    assert "Пожизненный доступ — 50 000 ₸: первые 7 дней как Pro AI" in r.text
    assert "3 бесплатных вопроса" in r.text
    assert r.buttons[0][0][0] == "Перейти на Pro AI"
    assert env.db.users[5]["lang"] == "ru" and env.db.users[5]["full_name"] == "Bob B"


async def test_kazakh_default_language(env):
    r = (await env.svc.start(6, "", "kk", None, "Айгүл"))[0]
    assert env.db.users[6]["lang"] == "kk" and "Тарифтер" in r.text


async def test_start_with_paid_tier_shows_plan(env):
    env.db.users[5] = {"tg_id": 5, "tier": "vip", "lang": "kk",
                       "paid_until": (NOW + timedelta(days=30)).isoformat()}
    r = (await env.svc.start(5, "", None, None, "Айгүл"))[0]
    assert "VIP" in r.text and "15.12.2026 дейін" in r.text and "Тарифтер" not in r.text


async def test_start_expired_tier_shows_tiers(env):
    env.db.users[5] = {"tg_id": 5, "tier": "pro", "lang": "en",
                       "paid_until": (NOW - timedelta(days=1)).isoformat()}
    r = (await env.svc.start(5, "", None, None, "Al"))[0]
    assert "Plans" in r.text


ALERT_ROW = {"src": "GENESIS", "event": "MSS", "kind": "Sweep", "symbol": "XAUUSD", "sweep_tf": "60",
             "mss_tf": "5", "dir": "SHORT", "level": 4182.1, "stop": 4185.3, "entry": 4176.4,
             "tp1": 4171.95, "tp2": 4165.2, "tp3": None, "tp4": None, "mss_level": 4177.0,
             "alert_time": "1763200000", "raw": {"symbol": "XAUUSD", "entry": "4176.40"},
             "outcome": "open", "outcome_at": None, "received_at": "2026-11-15T07:00:00+00:00"}


async def test_start_alert_deeplink_explains_alert_row(env):
    env.db.alerts[42] = ALERT_ROW
    env.client.responses = [text_resp("XAUUSD 1H SHORT ... Entry 4176.4")]
    r = (await env.svc.start(7, "alert_42", "ru", None, "X"))[0]
    prompt = env.client.calls[0]["messages"][0]["content"]
    assert '"entry": 4176.4' in prompt and '"raw": {' in prompt and "Russian" in prompt
    assert '"tp3"' not in prompt                               # empty columns are dropped
    assert '"tp2_rr": "1:1.3"' in prompt                       # derived in code, not by the model
    assert "Entry 4176.4" in r.text and "Осталось сегодня: 2" in r.text
    assert env.db.logs[0]["intent"] == "explain_alert"


async def test_alert_with_only_raw_sweep_json(env):
    env.db.alerts[43] = {"raw": {"events": [{"tf": "60", "dir": "SHORT", "entry": "4176.40", "sl": "4185.30",
                                             "tp1": "4171.95", "tp2": "4165.20"}]}}
    await env.svc.explain_alert(7, 43)
    assert '"tp2_rr": "1:1.3"' in env.client.calls[0]["messages"][0]["content"]


async def test_start_unknown_alert(env):
    r = (await env.svc.start(7, "alert_999", "en", None, "X"))[0]
    assert "#999" in r.text and env.client.calls == []


# ---------------------------------------------------------------- /settier
async def test_settier_requires_admin(env):
    r = await env.svc.set_tier(222, ["5", "pro", "30"])
    assert "админ" in r.text and 5 not in env.db.users


async def test_settier_pro_sets_paid_until(env):
    r = await env.svc.set_tier(111, ["5", "pro", "30"])
    u = env.db.users[5]
    assert u["tier"] == "pro" and tiers.parse_ts(u["paid_until"]) == NOW + timedelta(days=30)
    assert "Pro AI" in r.text and tiers.effective_tier(u, NOW) == "pro"


async def test_settier_lifetime_sets_7_day_trial(env):
    await env.svc.set_tier(111, ["5", "lifetime", "0"])
    u = env.db.users[5]
    assert u["paid_until"] is None
    assert tiers.parse_ts(u["lifetime_trial_until"]) == NOW + timedelta(days=7)
    assert tiers.effective_tier(u, NOW) == "pro"
    assert tiers.effective_tier(u, NOW + timedelta(days=8)) == "start"


async def test_settier_none_removes_access(env):
    await env.svc.set_tier(111, ["5", "vip", "30"])
    await env.svc.set_tier(111, ["5", "none", "0"])
    u = env.db.users[5]
    assert u["tier"] == "none" and u["paid_until"] is None


async def test_settier_bad_args(env):
    for args in ([], ["x", "pro", "1"], ["5", "gold", "1"], ["5", "pro", "0"], ["5", "pro"]):
        r = await env.svc.set_tier(111, args)
        assert "/settier" in r.text
    assert env.db.users == {}


async def test_lesson_qa_uses_top5_chunks_and_cites(env):
    env.db.lessons = [{"lesson": f"Сабақ {i}", "content": f"chunk {i}"} for i in range(1, 8)]
    env.client.responses = [text_resp("Жауап.\n📚 Сабақ 1")]
    r = await env.svc.ask(1, "MSS деген не?")
    assert env.db.searches == [("MSS деген не?", 5)]
    prompt = env.client.calls[0]["messages"][0]["content"]
    assert '<excerpt lesson="Сабақ 5">chunk 5</excerpt>' in prompt and "Сабақ 6" not in prompt
    assert "📚 Сабақ 1" in r.text


async def test_test_mode_hides_payment(make_env):
    env = make_env(test_mode=True)
    r = (await env.svc.start(5, "", "ru", None, "Bob"))[0]
    assert "₸" not in r.text and "@tredis_pay" not in r.text and "Тестовый режим" in r.text
    assert "Pro AI: 30 сообщений в день" in r.text
    assert r.buttons == []
    for _ in range(3):
        r = await env.svc.ask(5, "q")
    assert r.buttons == []                                    # no «Перейти на Pro AI» at the limit
    r = await env.svc.ask(5, "q")
    assert "Лимит" in r.text and r.buttons == []
