# TREDIS AI боты

TREDIS курсының AI көмекшісі. Бұл бөлек Telegram бот: GENESIS ORDER FLOW (@tradingkzl_bot) және GENESIS SWEEP (@genesis_sweep_bot) алерт боттарынан бөлек жұмыс істейді.

- Railway: жоба `tredis-ai-bot` (42932b13-7867-4188-806d-b2fd795c13c6), сервис `tredis-ai`, ортасы `production`.
- База: ортақ TREDIS Supabase жобасы (`wiyrgilgxupqhwpsvssu`). Схема бұл репода жасалмайды, қараңыз: `migrations/README.md`.
- Стек: Python 3.12, python-telegram-bot 21, Anthropic SDK, Supabase PostgREST.

## Не істейді

| Команда | Не болады | Модель |
|---|---|---|
| жай мәтін | Сабақ бойынша сұрақ. `lessons_kb` кестесінен ең жақын 5 бөлік табылады, жауап солардан құралып, сабақ атымен сілтеме беріледі | `claude-haiku-5-5` |
| `/start alert_<id>` | `alerts` кестесіндегі алертті сол жолдағы сандармен ғана түсіндіреді | `claude-haiku-5-5` |
| `/pine <сипаттама>` | Pine Script v6 код жазады (Pro AI / VIP) | `claude-sonnet-5-5` |
| `/setup <мәтін>` | Мәтінді tool use арқылы `{market, sweep_tf, mss_tf, direction}` баптауына айналдырады. Баптауды көрсетеді, «Иә/Да/Yes» басылғанда ғана `user_markets` кестесіне сақтайды | `claude-haiku-5-5` |
| `/tiers` | Тарифтер (`products` кестесіндегі бағамен) және төлем байланысы | — |
| `/lang` | Интерфейс тілі: KZ / RU / EN | — |
| `/settier <tg_id> <tier> <days>` | Тек `ADMIN_IDS`. Қолмен төлемді тексергеннен кейін тариф қояды | — |

`/start` (payload-сыз): жарамды тариф болса, тариф пен мерзімін көрсетеді. Болмаса, тарифтер, бағалар және төлем байланысы шығады.

### Тарифтер мен лимиттер

| `users.tier` | Хабарлама / күн | Pine код / ай |
|---|---|---|
| none (тарифсіз немесе мерзімі өткен) | `FREE_MSGS_DAY` (әдепкі 3; 0 = тек төленген) | — |
| start | 3 | — |
| pro | 30 | 10 |
| vip | 100 | 50 |
| lifetime | `lifetime_trial_until` дейін pro сияқты, кейін start сияқты | сол сияқты |

- start / pro / vip тарифтері `paid_until` мерзімі өткенше жарамды, кейін none болып есептеледі.
- `/settier 123 pro 30`: `paid_until = қазір + 30 күн`.
- `/settier 123 lifetime 0`: `lifetime_trial_until = қазір + 7 күн`.
- `/settier 123 none 0`: доступты алып тастайды.
- Әр AI жауаптан кейін «Осталось сегодня: N» көрсетіледі (kk: «Бүгін қалды», en: «Left today»). Лимит біткенде «Перейти на Pro AI» батырмасы шығады.
- Санау `add_ai_usage` RPC арқылы жүреді: бір жауап = 1 хабарлама, Pine код болса +1 код. Айлық Pine код саны `ai_usage_month` view-інен алынады.
- Күн Postgres `current_date` бойынша (UTC) есептеледі. Сондықтан күндік лимит Алматы уақытымен 05:00-де жаңарады. Бұл базадағы `add_ai_usage` функциясының мінезі.
- AI қатесі шықса, лимит жұмсалмайды.

### Лог және жеке деректер

`ai_log` кестесіне әр жауап жазылады: intent (`question | explain_alert | settings | code`), model, tokens_in/out, latency_ms, `/setup` үшін slots. Хабарлама мен жауаптың мәтіні тек `users.consent_ai_log = true` болғанда сақталады, қалған жағдайда `message = ''`, `answer = null` жазылады.

### Модельдер, кэш, бюджет

- `max_tokens` шектелген: чат 1500, код 6000 (`MAX_TOKENS_CHAT`, `MAX_TOKENS_CODE`).
- System prompt іске қосылғанда бір рет құрастырылады: глоссарий `glossary` кестесінен (kk/ru/en) алынады. Prompt өзгермейтін бір мәтін және `cache_control: ephemeral` белгісімен жіберіледі, сондықтан prompt caching қолданылады. Глоссарийді өзгерткен соң ботты қайта іске қосу керек.
- Effort: чатқа `low`, Pine кодқа `medium`.
- Sonnet сұрауларына server-side refusal fallback (`fallbacks: "default"`) қосылған. Бас тарту болса, пайдаланушыға «жауап бере алмаймын» деп жазылады.
- Бюджет: айлық шығын `ai_log`-тағы model × tokens бойынша бағаланады. Бот іске қосылғанда бір рет есептеледі, кейін жадта жалғасады. Шығын `MONTHLY_BUDGET_USD × BUDGET_ALERT_RATIO` деңгейіне жеткенде, `ADMIN_IDS` тізіміндегі админдерге айына бір рет ескерту келеді. Кэштелген токендер толық бағамен есептеледі, сондықтан бағалау шындықтан сәл жоғары шығады. Нақты шотты Anthropic Console көрсетеді.

### System prompt ережелері

Рөлі: TREDIS көмекшісі. Глоссарий: базадағы `glossary` (Sweep, Raid, MSS, OB, FVG, Stop, Entry, TP, …). Ережелер: инвестициялық кеңес бермейді; сандарды тек берілген деректерден алады; пайдаланушы жазған тілде (KZ/RU/EN) жауап береді. Мәтіні: `tredis/prompts.py`.

Алерт түсіндіргенде RR мен пунктпен қашықтық кодта есептеліп (`derive_alert`), модельге дайын беріледі.

### Retrieval: Postgres full-text search

`lessons_kb.content_tsv` (generated, `simple` конфигурациясы) бойынша PostgREST `fts(simple)` сүзгісі қолданылады:
1. Сұрақтағы сөздер кіші әріпке келтіріледі, 6 әріпке дейін қысқартылады және prefix match (`сөз:*`) арқылы OR-мен біріктіріледі. Қазақ тілінің жалғаулары үшін бұл қарапайым «стеммер» рөлін атқарады.
2. «деген, қандай, что, такое, what…» сияқты сұрақ сөздері алынып тасталады.
3. Табылған 60 бөліктің ішінен Python-да сөз сәйкестігі бойынша (сабақ атындағы сәйкестік екі есе салмақты) ең жақсы 5 бөлік таңдалады.

pgvector таңдалмады. Себептері: Anthropic embedding API бермейді, сондықтан тағы бір провайдер мен кілт керек болар еді. Терминдер нақты (Sweep, MSS, FVG), ал материал көлемі шағын. Кейінгі жақсартулар: `migrations/README.md`.

Сабақтарды жүктеу: әр сабақ — бір `.md`/`.txt` файл, бірінші жолы — сабақ аты.
```bash
SUPABASE_URL=... SUPABASE_KEY=... LESSON_LANG=kk COURSE=GENESIS .venv/bin/python scripts/load_lessons.py lessons/
```

## Айнымалылар (Railway → Variables)

| Аты | Міндетті | Мәні |
|---|---|---|
| `AI_BOT_TOKEN` | иә | TREDIS AI ботының токені (@BotFather) |
| `ANTHROPIC_API_KEY` | иә | console.anthropic.com → API keys |
| `SUPABASE_URL` | иә | `https://wiyrgilgxupqhwpsvssu.supabase.co` |
| `SUPABASE_KEY` | иә | Supabase Secret key (`sb_secret_…`) немесе legacy `service_role` (`eyJ…`) |
| `ADMIN_IDS` | иә | админдердің Telegram ID-лері, үтірмен: `111111111,222222222` |
| `PAYMENT_CONTACT` | жоқ | `@username` немесе `https://…` (әдепкі `@tredis_admin`) |
| `TEST_MODE` | жоқ | `1` = тест кезеңі: бағалар, төлем байланысы және «Перейти на Pro AI» батырмасы жасырылады, лимиттер сақталады |
| `FREE_MSGS_DAY` | жоқ | тарифсіз пайдаланушыға күндік тегін сұрақ саны (әдепкі 3) |
| `MONTHLY_BUDGET_USD` | жоқ | айлық бюджет, $ (әдепкі 50) |
| `BUDGET_ALERT_RATIO` | жоқ | ескерту шегі (әдепкі 0.8) |
| `MODEL_CHAT` / `MODEL_CODE` | жоқ | `claude-haiku-5-5` / `claude-sonnet-5-5` |
| `MAX_TOKENS_CHAT` / `MAX_TOKENS_CODE` | жоқ | 1500 / 6000 |
| `TZ_NAME` | жоқ | `Asia/Almaty`: пайдаланушыға көрсетілетін күндер үшін |

Үлгі: `.env.example`. Кодта ешқандай кілт жоқ. `httpx` логы WARNING деңгейінде, сондықтан токен URL арқылы логқа түспейді. Міндетті айнымалының бірі жоқ болса, бот іске қосылмайды және қайсысы жоқ екенін жазады.

## Railway-ге деплой

Бот polling режимінде жұмыс істейді, сондықтан домен, порт немесе том керек емес. Бұл worker сервисі.

```bash
cd ai-bot
railway service link tredis-ai
# Құпияларды stdin арқылы беріңіз (shell history-ге түспейді):
read -rs "v?SUPABASE_KEY: "; echo; printf %s "$v" | railway variable set SUPABASE_KEY --stdin --service tredis-ai --skip-deploys
railway variable set SUPABASE_URL=https://wiyrgilgxupqhwpsvssu.supabase.co --service tredis-ai --skip-deploys
railway up --service tredis-ai --detach
railway logs --service tredis-ai           # күтілетін жол: "TREDIS AI started; admins configured: 2"
```

Құрылым: `railway.json` (Nixpacks, `python bot.py`, ON_FAILURE restart), `.python-version` (3.12), `Procfile`.

Маңызды:
- Бір токенмен тек **бір** данасы жұмыс істеуі керек, әйтпесе Telegram polling `Conflict` қатесін береді. Ботты жергілікті компьютерде нақты токенмен іске қоспаңыз.
- Командаларды `ai-bot` папкасынан, `--service tredis-ai` арқылы іске қосыңыз.

## Алерт боттарымен байланыс (кейін)

Қазіргі алерт боттары өзгертілген жоқ. `alerts` кестесінде бағандар бар (src, event, kind, symbol, sweep_tf, mss_tf, dir, level, stop, entry, tp1–tp4, mss_level, alert_time) және бастапқы JSON-ға арналған `raw jsonb` бар. Алерт боты әр алертті сол кестеге жазып (`Prefer: return=representation` арқылы `id` алады), хабарламаға батырма қоса алады:

```python
InlineKeyboardButton("🤖 AI түсіндірсін", url=f"https://t.me/<TREDIS_AI_BOT_USERNAME>?start=alert_{alert_id}")
```

TREDIS AI бағандарды да, `raw`-ды да оқиды. Genesis Sweep форматындағы `raw.events[]` да қолдау табады. Алерт боты пайдаланушы баптауын `user_markets` кестесінен оқи алады.

## Тесттер

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

Anthropic пен Supabase mock-талған (`tests/fakes.py`, `httpx.MockTransport`). Тесттер мыналарды тексереді:
- лимиттер мен тарифке қол жеткізу (none/start/pro/vip/lifetime);
- `/settier`;
- tool-use арқылы баптауды талдау және «Да» басылғанға дейін сақтамау;
- алертті түсіндіру;
- RAG top-5;
- consent бойынша лог;
- бюджеттің 80% ескертуі;
- PostgREST сұрауларының пішімі.

## v1-де жоқ (кейін)

- Paybox/Kaspi арқылы автоматты төлем. Қазір `/settier` қолмен қойылады, `payments` кестесіне жазылмайды.
- `/settier`-ден кейін пайдаланушыға автоматты хабарлама жіберілмейді.
- `consent_ai_log` келісімін беретін команда жоқ.
- Диалог тарихы жоқ: әр сұрақ бөлек жауап алады.
- `/setup`-тағы күтудегі баптау жадта сақталады. Бот қайта іске қосылса, «Да» батырмасы «қайта жіберіңіз» дейді.
