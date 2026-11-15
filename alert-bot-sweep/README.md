# GENESIS SWEEP боты

GENESIS ORDER FLOW ботынан бөлек Telegram бот: тек Genesis Sweep сигналдары.

- Railway: жоба `genesis-sweep-bot`, сервис `sweep-bot`, том `/data`.
- Айнымалылар: `BOT_TOKEN`, `OWNER_IDS` (бас админдер, үтірмен), `ADMIN_IDS` (бастапқы админдер, тек бірінші іске қосуда), `DATA_DIR=/data`, `PUBLIC_BASE_URL`, `INDICATOR_LINK` (бас админ ботта өзгертсе, сол басым).
- Қосымша: `WEBHOOK_SECRET` (қаласаңыз `/webhook/<secret>` те қабылданады), `TV_IPS` (TradingView IP тізімі).
- Деплой: `railway up -p d3289cca-2929-42af-98fc-e9139d5efff3 -s 31ab0bc0-47bd-4853-93aa-850c666dbe82 -e c78673a7-7ce1-4523-a878-7b51906438fe`
- Alert нұсқаулығы: `pine/SWEEP_ALERTS.md`.

## Индикатор

- Оқушыларға: **Genesis Sweep** (private, invite-only): https://ru.tradingview.com/script/ABj0Xpp4-Genesis-Sweep/
  Коды: `pine/genesis_sweep_student.pine` (TradingView-де «Genesis Sweep KZ» деп сақталған). Доступ: скрипт беті → Manage access.
- Бот alert-тары үшін: `pine/genesis_sweep.pine` (TradingView-де «Genesis Sweep BOT», жеке).
