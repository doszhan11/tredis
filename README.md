# TREDIS

Trading signals, indicators, an AI assistant and a learning platform for traders. Telegram bots send alerts from our TradingView indicators; the AI assistant explains them, answers questions from our lessons and turns a trader's text into settings or Pine Script.

Team: Dosjan Tuimebayev (CEO, product), Daniel Eradilov (co-founder, bot and AI), Nurbol Kalen (co-founder, TradingView: indicators, strategies, auto-trading).

## What is in this repository

| Folder | What it is | Runs on |
| --- | --- | --- |
| [`ai-bot/`](ai-bot) | TREDIS AI assistant: Telegram bot on Claude (questions from lessons, alert explanations, text → settings, Pine Script), tariffs and limits | Railway `tredis-ai-bot` |
| [`alert-bot-genesis/`](alert-bot-genesis) | `@tradingkzl_bot`: GENESIS ORDER FLOW alerts → Telegram | Railway `zoological-reverence` |
| [`alert-bot-sweep/`](alert-bot-sweep) | `@genesis_sweep_bot`: Genesis Sweep alerts → Telegram, with its Pine code | Railway `genesis-sweep-bot` |
| [`indicators/`](indicators) | Pine Script of GENESIS ORDER FLOW and MAX block, list of all indicators | TradingView (invite-only) |
| [`database/`](database) | Supabase schema and seed data shared by the bots | Supabase project `wiyrgilgxupqhwpsvssu` |
| [`platform/`](platform) | Learning platform tradeacademy.world (code still to be added) | Railway `trading-academy` |
| [`landing/`](landing) | Landing page RU/EN for the startup course (SIS1) | static |
| [`nlp/`](nlp) | NLP prototype: text → alert settings and alert JSON → text in KZ/RU/EN, with evaluation | local |
| [`docs/`](docs) | Interactive concept demo of the AI assistant | static |
| [`business/`](business) | Pitch decks, unit economics, P&L, Agile Scrum backlog, CustDev, competitors, team | — |

## How the parts connect

```
TradingView indicator ──alert JSON──▶ alert bot (Railway) ──▶ Telegram subscribers
                                            │
                                            └─(planned) save every alert ──▶ Supabase: alerts
Trader ──text──▶ AI bot (Railway) ──▶ Claude API
                     │ reads/writes
                     └──────────────▶ Supabase: users, tariffs, limits, lessons, glossary
Students ──▶ tradeacademy.world (Railway, SQLite on a volume)
```

## Rules for this repository

- **Private only.** Indicators are sold invite-only; their code must not be public.
- **No secrets in code.** Tokens and keys live only in Railway variables; each service has a `.env.example` with the names.
- **No user data.** Bot JSON files, SQLite databases and lesson videos stay on Railway volumes.
- Each service is deployed from its own folder (Railway → service → Settings → Root Directory).

## Status (November 2026)

- A new indicator is selling (9 buyers); payments are checked by hand, Paybox and Kaspi are planned.
- AI assistant is live in test mode.
- GENESIS ORDER FLOW auto-trading backtest: −17%; MSS and Entry fixes come first.
