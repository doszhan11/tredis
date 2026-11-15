# TradingView indicators (Pine Script v6)

All indicators are published on TradingView as **invite-only**. Their code is private: keep this repository private.

| Indicator | File | TradingView | What it does |
| --- | --- | --- | --- |
| GENESIS ORDER FLOW | `genesis_order_flow.pine` | [script](https://ru.tradingview.com/script/d8vYA675-genesis-order-flow/), published 2 Oct 2026 | Finds Sweep and Raid on a higher timeframe, waits for MSS on the chart timeframe, draws Stop, Entry, TP 1–4 and sends a JSON alert to `@tradingkzl_bot` |
| MAX block | `max_block.pine` | [script](https://ru.tradingview.com/script/hNzhhqDt-max-block/), published 28 Sep 2026 | Draws Order Blocks and Fair Value Gaps and removes them after mitigation. No alerts |
| Genesis Sweep (for students) | `../alert-bot-sweep/pine/genesis_sweep_student.pine` | [script](https://ru.tradingview.com/script/ABj0Xpp4-Genesis-Sweep/) | Version that students get access to |
| Genesis Sweep BOT | `../alert-bot-sweep/pine/genesis_sweep.pine` | private | Sends alerts to `@genesis_sweep_bot`; setup in `../alert-bot-sweep/pine/SWEEP_ALERTS.md` |

## Alert JSON (GENESIS ORDER FLOW)

```json
{"src":"GENESIS","event":"MSS","kind":"Sweep","symbol":"BTCUSD","sweep_tf":"3","mss_tf":"3","dir":"LONG",
 "level":83691.23,"stop":83690.67,"entry":84078.01,"tp1":84317.38612,"tp2":84704.72612,"tp3":85092.06612,"tp4":85479.40612,
 "mss_level":83914.53,"time":"2026-10-11 22:33"}
```

Targets: `TP_k = Stop + f_k × (Entry − Stop)`, `f = 1.618, 2.618, 3.618, 4.618`.

## Known issue

With a 60-minute Sweep and MSS on 3 or 15 minutes, MSS is sometimes taken from a farther fractal instead of the nearest left fractal of the sweep candle, and on 15 minutes the Entry is placed after the higher-timeframe candle closes instead of on the MSS candle. The auto-trading backtest of this strategy showed −17%; the fix is planned before the next backtest.

MAX block is based on "SMC VP clone v1.4"; check that script's license before selling access.
