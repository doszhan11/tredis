import json
from datetime import date

import httpx

from tredis.db import DB, auth_headers, query_terms, rank_chunks
from tredis.service import to_html


def make_db(handler):
    client = httpx.AsyncClient(base_url="https://x.supabase.co/rest/v1", transport=httpx.MockTransport(handler))
    return DB("https://x.supabase.co", "k", client=client)


async def test_rest_calls_match_shared_schema():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        p = req.url.path
        if p.endswith("/ai_usage"):
            return httpx.Response(200, json=[{"msgs": 2, "code_requests": 1}])
        if p.endswith("/ai_usage_month"):
            return httpx.Response(200, json=[{"code_requests": 4}])
        if p.endswith("/lessons_kb"):
            return httpx.Response(200, json=[{"id": 1, "lesson": "L1", "content": "mss mss"},
                                             {"id": 2, "lesson": "MSS сабағы", "content": "mss"}])
        if req.method == "GET":
            return httpx.Response(200, json=[{"tg_id": 5, "tier": "pro"}])
        return httpx.Response(201)

    db = make_db(handler)
    assert (await db.get_user(5))["tier"] == "pro"
    assert seen[-1].url.params["tg_id"] == "eq.5"

    u = await db.get_usage(5, date(2026, 11, 15))
    assert u == {"msgs_day": 2, "code_month": 4}
    assert seen[-2].url.params["day"] == "eq.2026-11-15"
    assert seen[-1].url.params["month"] == "eq.2026-11-01"

    await db.add_usage(5, 1, 0, 120, 40)
    assert seen[-1].url.path.endswith("/rpc/add_ai_usage")
    assert json.loads(seen[-1].content) == {"p_tg_id": 5, "p_msgs": 1, "p_code": 0, "p_in": 120, "p_out": 40}

    rows = await db.search_lessons("MSS деген не?", 5)
    assert seen[-1].url.params["content_tsv"] == "fts(simple).mss:*"
    assert [r["id"] for r in rows] == [2, 1]                      # title hit ranks first

    await db.save_market(5, {"market": "XAUUSD", "sweep_tf": "15", "mss_tf": "1", "direction": "SHORT"})
    assert seen[-1].url.params["on_conflict"] == "tg_id,market"
    assert "merge-duplicates" in seen[-1].headers["Prefer"]
    await db.close()


def test_query_terms():
    assert query_terms("Что такое Order Block и FVG?") == ["order", "block", "fvg"]
    assert query_terms("ликвидность қалай жиналады") == ["ликвид", "жинала"]
    assert query_terms("не?") == []


def test_rank_chunks_prefers_more_hits():
    rows = [{"lesson": "a", "content": "x"}, {"lesson": "b", "content": "sweep sweep"}]
    assert rank_chunks(rows, ["sweep"], 1)[0]["lesson"] == "b"


def test_to_html_escapes_and_formats_code():
    s = to_html("a <b> & c\n```pine\nif x < 1\n```\nend")
    assert "&lt;b&gt; &amp; c" in s
    assert "<pre><code>if x &lt; 1</code></pre>" in s


def test_auth_headers_new_and_legacy_keys():
    assert "Authorization" not in auth_headers("sb_secret_abc")
    assert auth_headers("eyJhbGciOi.x.y")["Authorization"] == "Bearer eyJhbGciOi.x.y"
