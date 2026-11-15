"""Thin async wrapper over Supabase PostgREST for the shared TREDIS schema (no schema changes here)."""
import logging
import re
from datetime import date
from typing import Optional

import httpx

log = logging.getLogger("tredis.db")

STOPWORDS = {
    "деген", "дегеніміз", "қандай", "қалай", "неге", "неліктен", "қайда", "қашан", "және", "мен", "бұл",
    "что", "такое", "как", "это", "где", "почему", "зачем", "когда", "или", "для",
    "what", "how", "why", "where", "when", "the", "and", "does", "is",
}


def auth_headers(key: str) -> dict:
    """New Supabase secret keys (sb_secret_...) go only in `apikey`; legacy JWT keys also in Authorization."""
    h = {"apikey": key, "Content-Type": "application/json"}
    if key.startswith("eyJ"):
        h["Authorization"] = f"Bearer {key}"
    return h


def query_terms(q: str) -> list:
    """Lower-case words of 3+ letters, cut to 6 letters (a cheap stemmer for Kazakh suffixes), no question words."""
    out = []
    for w in re.findall(r"[^\W_]+", (q or "").lower()):
        if len(w) >= 3 and w not in STOPWORDS:
            w = w[:6]
            if w not in out:
                out.append(w)
    return out[:12]


def rank_chunks(rows: list, terms: list, k: int) -> list:
    """Order full-text matches by how many query terms they contain (title hits count double)."""
    def score(r):
        body = (r.get("content") or "").lower()
        title = (r.get("lesson") or "").lower()
        return sum(body.count(t) + 2 * title.count(t) for t in terms)
    return sorted(rows, key=score, reverse=True)[:k]


class DB:
    def __init__(self, url: str, key: str, client: Optional[httpx.AsyncClient] = None):
        self._c = client or httpx.AsyncClient(base_url=f"{url}/rest/v1", headers=auth_headers(key), timeout=15.0)

    async def close(self):
        await self._c.aclose()

    async def _get(self, table: str, params: dict) -> list:
        r = await self._c.get(f"/{table}", params=params)
        r.raise_for_status()
        return r.json()

    async def _upsert(self, table: str, row: dict, on: str):
        r = await self._c.post(f"/{table}", params={"on_conflict": on}, json=row,
                               headers={"Prefer": "resolution=merge-duplicates,return=minimal"})
        r.raise_for_status()

    # ---- users
    async def get_user(self, tg_id: int) -> Optional[dict]:
        rows = await self._get("users", {"tg_id": f"eq.{tg_id}", "limit": "1"})
        return rows[0] if rows else None

    async def upsert_user(self, row: dict):
        await self._upsert("users", row, "tg_id")

    # ---- usage: ai_usage (per UTC day, filled by add_ai_usage) + ai_usage_month view
    async def get_usage(self, tg_id: int, day: date) -> dict:
        today = await self._get("ai_usage", {"tg_id": f"eq.{tg_id}", "day": f"eq.{day.isoformat()}",
                                             "select": "msgs,code_requests"})
        month = await self._get("ai_usage_month", {"tg_id": f"eq.{tg_id}",
                                                   "month": f"eq.{day.replace(day=1).isoformat()}",
                                                   "select": "code_requests"})
        return {"msgs_day": int(today[0]["msgs"]) if today else 0,
                "code_month": int(month[0]["code_requests"] or 0) if month else 0}

    async def add_usage(self, tg_id: int, msgs: int, code: int, tokens_in: int, tokens_out: int):
        r = await self._c.post("/rpc/add_ai_usage", json={"p_tg_id": tg_id, "p_msgs": msgs, "p_code": code,
                                                          "p_in": tokens_in, "p_out": tokens_out})
        r.raise_for_status()

    # ---- ai_log
    async def log(self, row: dict):
        r = await self._c.post("/ai_log", json=row, headers={"Prefer": "return=minimal"})
        r.raise_for_status()

    async def month_spend_rows(self, since_iso: str) -> list:
        rows, off = [], 0
        while True:
            page = await self._get("ai_log", {"select": "model,tokens_in,tokens_out",
                                              "created_at": f"gte.{since_iso}", "order": "id",
                                              "limit": "1000", "offset": str(off)})
            rows += page
            if len(page) < 1000:
                return rows
            off += 1000

    # ---- alerts / lessons / glossary / products
    async def get_alert(self, alert_id: int) -> Optional[dict]:
        rows = await self._get("alerts", {"id": f"eq.{alert_id}", "limit": "1"})
        return rows[0] if rows else None

    async def search_lessons(self, q: str, k: int = 5) -> list:
        terms = query_terms(q)
        if not terms:
            return []
        tsq = " | ".join(f"{t}:*" for t in terms)
        rows = await self._get("lessons_kb", {"select": "id,lesson,content",
                                              "content_tsv": f"fts(simple).{tsq}", "limit": "60"})
        return rank_chunks(rows, terms, k)

    async def get_glossary(self) -> list:
        return await self._get("glossary", {"select": "term,kk,ru,en", "order": "term"})

    async def get_products(self) -> list:
        return await self._get("products", {"select": "code,kind,name,price_kzt,period_days",
                                            "active": "eq.true"})

    # ---- user_markets (alert preferences)
    async def save_market(self, tg_id: int, s: dict):
        await self._upsert("user_markets", {"tg_id": tg_id, "market": s["market"], "sweep_tf": s.get("sweep_tf"),
                                            "mss_tf": s.get("mss_tf"), "direction": s.get("direction") or "BOTH",
                                            "enabled": True}, "tg_id,market")
