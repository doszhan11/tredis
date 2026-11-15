# Database (Supabase, PostgreSQL)

One shared database for the AI bot, the alert bots and admin tools.

- Supabase organization **TREDIS**, project ref `wiyrgilgxupqhwpsvssu`, URL `https://wiyrgilgxupqhwpsvssu.supabase.co`.
- `tredis_database.sql` is the full schema plus seed data (tariffs, indicators, strategy, backtest, glossary). It is already applied; run it only on a new, empty project.
- Row Level Security is on for every table and there are no public policies: only servers with the secret key (`SUPABASE_KEY`, kept in Railway variables) can read or write.

| Block | Tables |
| --- | --- |
| Users and payments | `users`, `products`, `payments` |
| Signals | `user_markets`, `alerts`, `alert_deliveries` |
| AI assistant | `ai_usage`, `ai_log`, `glossary`, `lessons_kb`, function `add_ai_usage`, view `ai_usage_month` |
| Product | `indicators`, `strategies`, `backtests` |

Not connected yet: the alert bots still keep their data in JSON files on Railway volumes, and the learning platform uses SQLite on its volume. Moving them here is a separate step, done with a backup first.
