from tredis.ai import MARKETS, SETTINGS_TOOL, TFS, validate_settings
from tests.fakes import text_resp, tool_resp


def test_tool_schema_is_strict_and_matches_db_constraints():
    s = SETTINGS_TOOL["input_schema"]
    assert SETTINGS_TOOL["strict"] is True
    assert s["additionalProperties"] is False
    assert set(s["required"]) == {"market", "sweep_tf", "mss_tf", "direction"}
    # user_markets CHECK constraints in the shared TREDIS database
    assert TFS == ["1", "3", "5", "15", "30", "60", "240"]
    assert set(MARKETS) == {"XAUUSD", "XAUEUR", "BTCUSD", "XAGUSD", "GBPUSD", "EURUSD", "GER40", "AUDUSD",
                            "USDJPY", "CADJPY"}


def test_validate_settings_normalizes_and_drops_bad_values():
    assert validate_settings({"market": "xauusd", "sweep_tf": "15", "mss_tf": 1, "direction": "short"}) == \
        {"market": "XAUUSD", "sweep_tf": "15", "mss_tf": "1", "direction": "SHORT"}
    assert validate_settings({"market": "BTCUSD", "sweep_tf": "D", "mss_tf": "NONE", "direction": "NONE"}) == \
        {"market": "BTCUSD", "sweep_tf": None, "mss_tf": None, "direction": "BOTH"}
    assert validate_settings({"market": "DOGE", "sweep_tf": "15", "mss_tf": "1", "direction": "LONG"}) is None
    assert validate_settings({"market": "NONE", "sweep_tf": "15", "mss_tf": "1", "direction": "LONG"}) is None
    assert validate_settings("garbage") is None


async def test_setup_parses_and_waits_for_yes(env):
    env.db.users[1] = {"tg_id": 1, "tier": "none", "lang": "ru"}
    env.client.responses = [tool_resp({"market": "XAUUSD", "sweep_tf": "15", "mss_tf": "1", "direction": "SHORT"})]
    r = await env.svc.setup(1, "золото, свип 15м, MSS 1м, только шорт")
    call = env.client.calls[0]
    assert call["tools"][0]["name"] == "save_alert_settings"
    assert call["tool_choice"] == {"type": "auto"}                # forced tool_choice is rejected on 5.5 models
    assert r.pending_settings == {"market": "XAUUSD", "sweep_tf": "15", "mss_tf": "1", "direction": "SHORT"}
    assert "Рынок: XAUUSD" in r.text and "Сохранить?" in r.text
    assert [b[1] for b in r.buttons[0]] == ["set:yes", "set:no"] and r.buttons[0][0][0] == "Да"
    assert env.db.markets == {}                                   # nothing saved before «Да»
    assert env.db.ai_usage[(1, env.db.today)]["msgs"] == 1
    assert env.db.logs[0]["intent"] == "settings" and env.db.logs[0]["slots"]["market"] == "XAUUSD"

    saved = await env.svc.confirm_settings(1, r.pending_settings, yes=True)
    assert env.db.markets[(1, "XAUUSD")]["direction"] == "SHORT"
    assert "Сохранено" in saved.text


async def test_setup_no_does_not_save(env):
    env.client.responses = [tool_resp({"market": "BTCUSD", "sweep_tf": "60", "mss_tf": "5", "direction": "LONG"})]
    r = await env.svc.setup(1, "btc 1h long")
    await env.svc.confirm_settings(1, r.pending_settings, yes=False)
    assert env.db.markets == {}


async def test_setup_without_tool_call(env):
    env.client.responses = [text_resp("I am not sure.")]
    r = await env.svc.setup(1, "hello")
    assert r.pending_settings is None and "түсіне алмадым" in r.text


async def test_setup_without_market_is_rejected(env):
    env.client.responses = [tool_resp({"market": "NONE", "sweep_tf": "15", "mss_tf": "1", "direction": "LONG"})]
    r = await env.svc.setup(1, "15m sweep 1m mss long")
    assert r.pending_settings is None


async def test_setup_tool_input_as_json_string(env):
    env.client.responses = [tool_resp('{"market": "GER40", "sweep_tf": "240", "mss_tf": "15", "direction": "BOTH"}')]
    r = await env.svc.setup(1, "dax 4h")
    assert r.pending_settings["market"] == "GER40"


async def test_expired_pending_settings(env):
    r = await env.svc.confirm_settings(1, None, yes=True)
    assert "/setup" in r.text
