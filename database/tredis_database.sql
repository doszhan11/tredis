-- TREDIS: run this whole file once in Supabase → SQL Editor (schema + seed data)

-- TREDIS database schema (Supabase / PostgreSQL)
-- Shared by: alert bot, AI bot, admin tools. Access only from servers with the service_role key (RLS on, no public policies).

-- ---------- users and access
create table public.users (
  tg_id                 bigint primary key,
  username              text,
  full_name             text,
  tv_username           text,
  lang                  text not null default 'kk' check (lang in ('kk','ru','en')),
  tier                  text not null default 'none' check (tier in ('none','start','pro','vip','lifetime')),
  paid_until            timestamptz,
  lifetime_trial_until  timestamptz,
  consent_ai_log        boolean not null default false,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);
comment on table public.users is 'Telegram users of both bots. tier + paid_until decide access to signals and AI.';

create table public.products (
  code          text primary key,
  kind          text not null check (kind in ('subscription','lifetime','custom')),
  name          text not null,
  price_kzt     integer not null check (price_kzt >= 0),
  period_days   integer,
  description   text,
  active        boolean not null default true
);
comment on table public.products is 'Tariffs and one-time products. Lifetime prices start from 50 000 KZT and depend on the indicator.';

create table public.payments (
  id            bigint generated always as identity primary key,
  tg_id         bigint not null references public.users(tg_id),
  product_code  text not null references public.products(code),
  amount_kzt    integer not null check (amount_kzt >= 0),
  method        text not null default 'manual' check (method in ('manual','paybox','kaspi')),
  status        text not null default 'pending' check (status in ('pending','confirmed','refunded','failed')),
  external_id   text,
  confirmed_by  bigint,
  created_at    timestamptz not null default now(),
  confirmed_at  timestamptz
);
create index payments_tg_id_idx on public.payments (tg_id);

-- ---------- signals
create table public.user_markets (
  tg_id      bigint not null references public.users(tg_id) on delete cascade,
  market     text not null check (market in ('XAUUSD','XAUEUR','BTCUSD','XAGUSD','GBPUSD','EURUSD','GER40','AUDUSD','USDJPY','CADJPY')),
  sweep_tf   text check (sweep_tf in ('1','3','5','15','30','60','240')),
  mss_tf     text check (mss_tf in ('1','3','5','15','30','60','240')),
  direction  text not null default 'BOTH' check (direction in ('LONG','SHORT','BOTH')),
  enabled    boolean not null default true,
  created_at timestamptz not null default now(),
  primary key (tg_id, market)
);

create table public.alerts (
  id           bigint generated always as identity primary key,
  src          text,
  event        text check (event in ('SWEEP','RAID','MSS')),
  kind         text check (kind in ('Sweep','Raid')),
  symbol       text,
  sweep_tf     text,
  mss_tf       text,
  dir          text check (dir in ('LONG','SHORT')),
  level        numeric,
  stop         numeric,
  entry        numeric,
  tp1          numeric,
  tp2          numeric,
  tp3          numeric,
  tp4          numeric,
  mss_level    numeric,
  alert_time   text,
  raw          jsonb not null,
  outcome      text not null default 'open' check (outcome in ('open','stop','tp1','tp2','tp3','tp4','cancelled')),
  outcome_at   timestamptz,
  received_at  timestamptz not null default now()
);
comment on table public.alerts is 'Every TradingView alert JSON (GENESIS ORDER FLOW) with its outcome. Source for statistics, backtests and AI explanations.';
create index alerts_symbol_received_idx on public.alerts (symbol, received_at desc);

create table public.alert_deliveries (
  alert_id  bigint not null references public.alerts(id) on delete cascade,
  tg_id     bigint not null references public.users(tg_id) on delete cascade,
  sent_at   timestamptz not null default now(),
  primary key (alert_id, tg_id)
);
create index alert_deliveries_tg_id_idx on public.alert_deliveries (tg_id);

-- ---------- AI assistant
create table public.ai_usage (
  tg_id          bigint not null references public.users(tg_id) on delete cascade,
  day            date not null default current_date,
  msgs           integer not null default 0,
  code_requests  integer not null default 0,
  tokens_in      integer not null default 0,
  tokens_out     integer not null default 0,
  primary key (tg_id, day)
);

create table public.ai_log (
  id          bigint generated always as identity primary key,
  tg_id       bigint not null references public.users(tg_id) on delete cascade,
  message     text not null,
  intent      text check (intent in ('question','explain_alert','settings','code','strategy','other')),
  slots       jsonb,
  answer      text,
  model       text,
  tokens_in   integer,
  tokens_out  integer,
  latency_ms  integer,
  rating      smallint check (rating in (-1,0,1)),
  created_at  timestamptz not null default now()
);
comment on table public.ai_log is 'AI messages. Store message text only for users with consent_ai_log = true; used for NLP evaluation.';
create index ai_log_tg_id_created_idx on public.ai_log (tg_id, created_at desc);

create table public.glossary (
  term   text primary key,
  kk     text,
  ru     text,
  en     text
);

create table public.lessons_kb (
  id           bigint generated always as identity primary key,
  course       text,
  lesson       text not null,
  chunk_index  integer not null default 0,
  lang         text check (lang in ('kk','ru','en')),
  content      text not null,
  source_url   text,
  content_tsv  tsvector generated always as (to_tsvector('simple', coalesce(lesson,'') || ' ' || content)) stored,
  created_at   timestamptz not null default now()
);
comment on table public.lessons_kb is 'Lesson text and transcripts split into chunks for retrieval (RAG). Full-text search now; vectors can be added later.';
create index lessons_kb_tsv_idx on public.lessons_kb using gin (content_tsv);

-- ---------- indicators, strategies, backtests
create table public.indicators (
  id            bigint generated always as identity primary key,
  name          text not null unique,
  platform      text not null default 'TradingView',
  access        text not null default 'invite-only',
  url           text,
  published_at  date,
  description   text
);

create table public.strategies (
  id           bigint generated always as identity primary key,
  name         text not null unique,
  indicator_id bigint references public.indicators(id),
  rules        jsonb,
  status       text not null default 'testing' check (status in ('testing','demo','live','paused')),
  description  text,
  created_at   timestamptz not null default now()
);

create table public.backtests (
  id             bigint generated always as identity primary key,
  strategy_id    bigint not null references public.strategies(id) on delete cascade,
  market         text,
  timeframe      text,
  period_start   date,
  period_end     date,
  trades         integer,
  win_rate       numeric,
  profit_factor  numeric,
  max_drawdown   numeric,
  net_return     numeric,
  notes          text,
  created_at     timestamptz not null default now()
);
create index backtests_strategy_id_idx on public.backtests (strategy_id);
create index strategies_indicator_id_idx on public.strategies (indicator_id);
create index payments_product_code_idx on public.payments (product_code);

-- ---------- helpers
create or replace function public.set_updated_at() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.updated_at = now();
  return new;
end $$;
create trigger users_set_updated_at before update on public.users
for each row execute function public.set_updated_at();

create or replace function public.add_ai_usage(p_tg_id bigint, p_msgs int, p_code int, p_in int, p_out int)
returns public.ai_usage language sql set search_path = '' as $$
  insert into public.ai_usage as u (tg_id, day, msgs, code_requests, tokens_in, tokens_out)
  values (p_tg_id, current_date, p_msgs, p_code, p_in, p_out)
  on conflict (tg_id, day) do update set
    msgs = u.msgs + excluded.msgs,
    code_requests = u.code_requests + excluded.code_requests,
    tokens_in = u.tokens_in + excluded.tokens_in,
    tokens_out = u.tokens_out + excluded.tokens_out
  returning *;
$$;

create view public.ai_usage_month with (security_invoker = true) as
  select tg_id, date_trunc('month', day)::date as month,
         sum(msgs) as msgs, sum(code_requests) as code_requests,
         sum(tokens_in) as tokens_in, sum(tokens_out) as tokens_out
  from public.ai_usage group by tg_id, date_trunc('month', day);

-- ---------- security: RLS on everything, no public policies (servers use service_role)
alter table public.users            enable row level security;
alter table public.products         enable row level security;
alter table public.payments         enable row level security;
alter table public.user_markets     enable row level security;
alter table public.alerts           enable row level security;
alter table public.alert_deliveries enable row level security;
alter table public.ai_usage         enable row level security;
alter table public.ai_log           enable row level security;
alter table public.glossary         enable row level security;
alter table public.lessons_kb       enable row level security;
alter table public.indicators       enable row level security;
alter table public.strategies       enable row level security;
alter table public.backtests        enable row level security;
revoke execute on function public.add_ai_usage(bigint,int,int,int,int) from anon, authenticated, public;

-- TREDIS seed data: tariffs, indicators, strategy, backtest result, glossary.
-- Facts come from the team; prices are the current TREDIS tariffs.

insert into public.products (code, kind, name, price_kzt, period_days, description) values
 ('start',    'subscription', 'Start',               30000, 30,   'Индикатор и сигналы в Telegram'),
 ('pro',      'subscription', 'Pro AI',              50000, 30,   'Всё из Start и AI-ассистент'),
 ('vip',      'subscription', 'VIP',                100000, 30,   'Всё без лимитов и менторство'),
 ('lifetime', 'lifetime',     'Пожизненный доступ',  50000, null, 'Доступ навсегда к индикатору или стратегии; цена от 50 000 ₸ и зависит от продукта (точная сумма — в payments.amount_kzt)'),
 ('custom',   'custom',       'Разработка под заказ', 250000, null, 'Индикатор или стратегия под заказ; первый клиент заплатил 250 000 ₸');

insert into public.indicators (name, platform, access, url, published_at, description) values
 ('MAX block', 'TradingView', 'invite-only', 'https://ru.tradingview.com/script/hNzhhqDt-max-block/', '2026-09-28',
  'Рисует Order Blocks и Fair Value Gaps и убирает их после митигации. Алертов не отправляет.'),
 ('GENESIS ORDER FLOW', 'TradingView', 'invite-only', 'https://ru.tradingview.com/script/d8vYA675-genesis-order-flow/', '2026-10-02',
  'Находит Sweep и Raid на старшем таймфрейме, ждёт MSS на таймфрейме графика, рисует Stop, Entry, TP 1–4 и отправляет алерт в JSON.');

insert into public.strategies (name, indicator_id, rules, status, description)
select 'GENESIS Sweep → MSS', id,
 '{"entry":"Sweep или Raid на sweep_tf, затем MSS на mss_tf","stop":"экстремум свечи свипа","entry_price":"край тела свечи MSS","targets":"TP_k = Stop + f_k × (Entry − Stop), f = 1.618, 2.618, 3.618, 4.618"}'::jsonb,
 'testing', 'Стратегия для автоторговли; подключение не завершено.'
from public.indicators where name = 'GENESIS ORDER FLOW';

insert into public.backtests (strategy_id, net_return, notes)
select id, -0.17, 'Бэктест с автоторговлей на исторических данных: −17% (данные команды). Рынок, период и число сделок не записаны. План: исправить MSS (дальний фрактал) и Entry на 15m, затем повторить.'
from public.strategies where name = 'GENESIS Sweep → MSS';

insert into public.glossary (term, kk, ru, en) values
 ('fractal', 'Екі жағындағы N свечадан максимумы (минимумы) жоғары (төмен) свеча. N — «фрактал күші», әдепкі 1.', 'Свеча, у которой максимум (минимум) выше (ниже), чем у N свечей с каждой стороны. N — сила фрактала, по умолчанию 1.', 'A candle whose high (low) is above (below) the N candles on each side. N is the fractal strength, default 1.'),
 ('liquidity', 'Көп стоп-ордер күтілетін баға деңгейлері: фракталдардың максимумдары мен минимумдары.', 'Уровни цены, где ожидается много стоп-ордеров: максимумы и минимумы фракталов.', 'Price levels where many stop orders are expected: the highs and lows of fractals.'),
 ('sweep', 'Жоғары таймфреймдегі свеча ликвидность деңгейін фитильмен алады, ал денесі деңгейдің бастапқы жағында қалады.', 'Свеча старшего таймфрейма забирает уровень ликвидности тенью, а её тело остаётся по прежнюю сторону уровня.', 'A higher-timeframe candle takes a liquidity level with its wick while its body stays on the original side of the level.'),
 ('raid', 'Свеча деңгейден денесімен өтіп жабылады, келесі свеча кері қайтып жабылады: ликвидностьті жинаған жалған бұзу.', 'Свеча закрывается телом за уровнем, следующая разворачивается и закрывается обратно: ложный пробой, собравший ликвидность.', 'A candle closes with its body beyond a level and the next candle reverses and closes back: a false breakout that took liquidity.'),
 ('mss', 'Свип немесе Raid-тан кейін график таймфреймінде қарама-қарсы фракталды жабылу бұзады: бағыттың өзгергенін растайды.', 'После Sweep или Raid закрытие на таймфрейме графика за ближайшим противоположным фракталом: подтверждает смену направления.', 'After a Sweep or Raid, a close on the chart timeframe beyond the nearest opposite fractal: it confirms the change of direction.'),
 ('stop', 'Свип свечасының экстремумы.', 'Экстремум свечи свипа.', 'The extreme of the sweep candle.'),
 ('entry', 'MSS свечасы денесінің шеті.', 'Край тела свечи MSS.', 'The body edge of the MSS candle.'),
 ('tp', 'Stop–Entry қашықтығының Фибоначчи кеңеюі (1.618, 2.618, 3.618, 4.618), Stop-тан есептеледі.', 'Фибоначчи-расширения расстояния Stop–Entry (1.618, 2.618, 3.618, 4.618), откладываются от Stop.', 'Fibonacci extensions of the Stop–Entry distance (1.618, 2.618, 3.618, 4.618), measured from the Stop.'),
 ('order_block', 'Гэп қалдырған импульстен бұрынғы свеча: максимумынан минимумына дейінгі қорап.', 'Свеча перед импульсом, оставившим гэп: прямоугольник от максимума до минимума.', 'The candle before an impulsive move that left a gap: a box from its high to its low.'),
 ('fvg', '1-ші және 3-ші свеча арасындағы, 2-ші свеча жаппаған саңылау.', 'Разрыв между 1-й и 3-й свечой, который 2-я свеча не закрыла.', 'A gap between candle 1 and candle 3 that candle 2 did not fill.');
