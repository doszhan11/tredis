# GENESIS ORDER FLOW alert bot (@tradingkzl_bot)

Telegram bot that receives GENESIS ORDER FLOW alerts from TradingView and sends them to subscribers of each market, with a picture and the levels in Kazakh.

- Code: `main.py` (Python, python-telegram-bot, aiohttp, Pillow).
- Flow: TradingView alert (JSON) → `POST /webhook/<WEBHOOK_SECRET>` → text from a Kazakh template + schematic picture → users who chose this market.
- Data: `users.json`, `prefs.json`, `settings.json` in `DATA_DIR` (Railway volume `/data`). These files are user data and are never committed.
- Railway: project `zoological-reverence`, service `web`. The live service still deploys from the older repo `doszhan11/trd_bot`; this folder is the copy kept in the TREDIS monorepo.
- Variables: see `.env.example`.

The indicator code is in `../indicators/genesis_order_flow.pine`.
