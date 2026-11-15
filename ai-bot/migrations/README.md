# Схема

Бот **ортақ TREDIS базасын** қолданады (Supabase жобасы `wiyrgilgxupqhwpsvssu`, ұйым TREDIS).
Толық схема: `../../database/tredis_database.sql`. Бот кесте жасамайды; схема тек сол файл арқылы өзгереді.

Бот қолданатын объектілер:

| Объект | Не үшін |
|---|---|
| `users` (tg_id, tier none/start/pro/vip/lifetime, paid_until, lifetime_trial_until, lang kk/ru/en, consent_ai_log, username, full_name) | тариф, тіл |
| `rpc add_ai_usage(p_tg_id, p_msgs, p_code, p_in, p_out)` | лимит есебі (күн = Postgres `current_date`, UTC) |
| `ai_usage` (tg_id, day) + view `ai_usage_month` | бүгінгі хабарлама саны, айлық Pine код саны |
| `ai_log` (message, intent question/explain_alert/settings/code, slots, answer, model, tokens_in/out, latency_ms) | лог; мәтін тек `consent_ai_log = true` болса жазылады; айлық бюджет бағасы да осыдан |
| `alerts` (бағандар + raw jsonb + outcome) | `/start alert_<id>` |
| `lessons_kb` (lesson, content, content_tsv `simple`) | RAG, PostgREST `fts(simple)` |
| `glossary` (term, kk, ru, en) | system prompt-тағы глоссарий (іске қосылғанда бір рет оқылады) |
| `products` | тарифтер тізіміндегі баға |
| `user_markets` (tg_id, market, sweep_tf, mss_tf, direction) | `/setup` баптаулары |

## Кейінгі жақсартулар

Іздеу сапасын арттыру үшін кейін `ts_rank` бойынша сұрыптайтын және `pg_trgm` арқылы қате жазылған сөздерді табатын RPC қосуға болады. Қазір ранжирлеу Python-да (`tredis/db.py: rank_chunks`) жасалады.
