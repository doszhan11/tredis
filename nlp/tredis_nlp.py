# -*- coding: utf-8 -*-
"""TREDIS NLP prototype: (1) text -> alert settings (NLU), (2) alert JSON -> text explanation (NLG).
No external dependencies. Run:  python tredis_nlp.py
"""
import re, json, difflib

# ----------------------------------------------------------------- shared helpers
SUFFIXES = sorted(["ом","ем","ой","ей","ий","ый","ами","ях","ах","ов","ев","ам","ям","ую","ою","ию",
    "ға","ге","қа","ке","да","де","та","те","дан","ден","тан","тен","ның","нің","дың","дің","тың","тің",
    "мен","пен","бен","ды","ді","ты","ті","лық","лік","дық","дік","тық","тік","ына","іне","ын","ін","ның","не",
    "у","ю","а","я","ы","и","о","е","s"], key=len, reverse=True)
STOP = {"в","к","и","на","по","для","с","of","in","to","the","a","an","on","for","when","me","i","want",
        "мен","пен","бен","бойынша","үшін","керек","тек","только","only","then","with","and","is","are","be"}

def norm(text):
    t = text.lower().replace("ё", "е")
    t = re.sub(r"[-–—/]", " ", t)
    t = re.sub(r"(\d)([^\W\d_])", r"\1 \2", t)
    t = re.sub(r"[^\w\s]", " ", t)
    return t.split()

def stem(tok, min_len=3):
    for _ in range(3):
        for suf in SUFFIXES:
            if tok.endswith(suf) and len(tok) - len(suf) >= min_len:
                tok = tok[: -len(suf)]
                break
        else:
            break
    return tok

# ----------------------------------------------------------------- gazetteers
MARKETS = {
 "XAUUSD": ["xauusd","xau","gold","золото","алтын"],
 "XAUEUR": ["xaueur","gold euro","золото евро","алтын еуро"],
 "BTCUSD": ["btcusd","btc","bitcoin","биткоин","биткойн","бтс","бтц"],
 "XAGUSD": ["xagusd","xag","silver","серебро","күміс"],
 "GBPUSD": ["gbpusd","gbp","pound","фунт","фунт доллар","cable"],
 "EURUSD": ["eurusd","eur usd","euro","евро","еуро","евро доллар","еуро доллар"],
 "GER40":  ["ger40","dax","дакс","german index","немецкий индекс","germany 40","германия 40"],
 "AUDUSD": ["audusd","aud","австралийский доллар","австралия доллар"],
 "USDJPY": ["usdjpy","jpy","доллар йена"],
 "CADJPY": ["cadjpy","cad","канадский доллар йена","канада доллар йена"],
}
NUMWORDS = {"один":1,"одна":1,"три":3,"трех":3,"четыре":4,"четырех":4,"пять":5,"пяти":5,"пятнадцать":15,"пятнадцати":15,
    "тридцать":30,"тридцати":30,"шестьдесят":60,"бір":1,"үш":3,"төрт":4,"бес":5,"отыз":30,"алпыс":60,
    "one":1,"three":3,"four":4,"five":5,"fifteen":15,"thirty":30,"sixty":60}
ALLOWED_TF = {1,3,5,15,30,60,240}
SWEEP_WORDS = ["sweep","свип","свеп"]
MSS_WORDS   = ["mss","мсс","слом","слон"]
LONG_W  = {stem(w) for w in ("long","лонг","buy","покупк","покупат","купит","купл")}
SHORT_W = {stem(w) for w in ("short","шорт","sell","продаж","продат","сату")}
BOTH_W  = {stem(w) for w in ("обе","оба","both","either","любую","екі","any","two")}

def _alias_table():
    table = []
    for market, aliases in MARKETS.items():
        for a in aliases:
            toks = [stem(t) for t in norm(a) if t not in STOP]
            table.append((tuple(toks), market))
    table.sort(key=lambda x: -len(x[0]))
    return table
ALIASES = _alias_table()

# ----------------------------------------------------------------- baseline parser (naive)
def parse_baseline(text):
    toks = re.findall(r"[a-zа-яәіңғүұқөһ0-9]+", text.lower())
    market = None
    plain = {"xauusd","btcusd","xagusd","gbpusd","eurusd","ger40","audusd","usdjpy","cadjpy","xaueur"}
    words = {"gold":"XAUUSD","silver":"XAGUSD","bitcoin":"BTCUSD","btc":"BTCUSD","золото":"XAUUSD","серебро":"XAGUSD","биткоин":"BTCUSD"}
    for t in toks:
        if t in plain: market = t.upper(); break
        if t in words: market = words[t]; break
    tfs = []
    for m in re.finditer(r"(\d+)\s*(m|min|mins|minutes?|h|hours?)\b", text.lower()):
        v = int(m.group(1)); tfs.append(str(v * 60 if m.group(2).startswith("h") else v))
    sweep = tfs[0] if len(tfs) > 0 else None
    mss = tfs[1] if len(tfs) > 1 else None
    longw = any(t in {"long","buy","лонг","покупка"} for t in toks)
    shortw = any(t in {"short","sell","шорт","продажа"} for t in toks)
    both = any(t in {"both","обе","оба"} for t in toks)
    direction = "BOTH" if (both or (longw == shortw)) else ("LONG" if longw else "SHORT")
    return {"market": market, "sweep_tf": sweep, "mss_tf": mss, "direction": direction}

# ----------------------------------------------------------------- improved parser
def _is_minute(t): return t.startswith(("мин", "min")) or t in ("м", "m")
def _is_hour(t):   return t.startswith(("час", "hour", "сағат")) or t in ("ч", "h")

def _fuzzy_role(tok, words, thr=0.75):
    if len(tok) < 3: return False
    return any(tok == w or difflib.SequenceMatcher(None, tok, w).ratio() >= thr for w in words)

def parse_improved(text):
    raw = norm(text)
    toks = [stem(t) if not t.isdigit() and t not in NUMWORDS else t for t in raw]
    # --- market: longest alias n-gram over stop-word-free stems, then fuzzy single tokens
    clean = [t for t in toks if t not in {stem(s) for s in STOP}]
    market, best = None, 0
    for alias, m in ALIASES:
        n = len(alias)
        if n == 0 or n <= best: continue
        for i in range(len(clean) - n + 1):
            if tuple(clean[i:i+n]) == alias:
                market, best = m, n; break
    if market is None:
        for t in clean:
            if len(t) < 5: continue
            for alias, m in ALIASES:
                if len(alias) == 1 and len(alias[0]) >= 5 and difflib.SequenceMatcher(None, t, alias[0]).ratio() >= 0.85:
                    market = m; break
            if market: break
    # --- roles
    roles = []   # (index, role)
    for i, t in enumerate(toks):
        if _fuzzy_role(t, SWEEP_WORDS): roles.append((i, "sweep"))
        elif t in MSS_WORDS: roles.append((i, "mss"))
        elif t == "market" and toks[i+1:i+3] == ["structure", "shift"]: roles.append((i, "mss"))
    # --- timeframes
    cands = []   # (index, minutes)
    i = 0
    while i < len(toks):
        t, val, span = toks[i], None, 1
        if t.isdigit(): val = int(t)
        elif t == "он" and i + 1 < len(toks) and toks[i+1] == "бес": val, span = 15, 2
        elif t in NUMWORDS: val = NUMWORDS[t]
        nxt = toks[i + span] if i + span < len(toks) else ""
        if val is not None and _is_minute(nxt): cands.append((i, val)); i += span + 1; continue
        if val is not None and _is_hour(nxt):   cands.append((i, val * 60)); i += span + 1; continue
        if val is not None and t.isdigit() and val in ALLOWED_TF and any(abs(i - r) <= 1 for r, _ in roles):
            cands.append((i, val)); i += 1; continue
        if val is None and (_is_hour(t) or t == "hourly"):
            prev = toks[i-1] if i else ""
            if not (prev.isdigit() or prev in NUMWORDS): cands.append((i, 60))
        i += 1
    out = {}
    if cands and roles:
        import itertools
        k = min(len(cands), len(roles))
        best_cost, best = None, None
        for cs in itertools.permutations(range(len(cands)), k):
            for rs in itertools.permutations(range(len(roles)), k):
                cost = sum(abs(cands[c][0] - roles[r][0]) for c, r in zip(cs, rs))
                if best_cost is None or cost < best_cost:
                    best_cost, best = cost, list(zip(cs, rs))
        for c, r in best:
            out[roles[r][1]] = str(cands[c][1])
    # --- direction
    stems = set(toks)
    joined = " ".join(toks)
    LONG_PRE  = ("лонг", "long", "buy", "покупк", "купит", "купл")
    SHORT_PRE = ("шорт", "short", "sell", "продаж", "продат")
    longw = bool(stems & LONG_W) or "сатып ал" in joined or any(t.startswith(LONG_PRE) for t in raw)
    shortw = bool(stems & SHORT_W) or any(t.startswith(SHORT_PRE) for t in raw)
    both = bool(stems & BOTH_W)
    direction = "BOTH" if (both or (longw == shortw) or (longw and shortw)) else ("LONG" if longw else "SHORT")
    return {"market": market, "sweep_tf": out.get("sweep"), "mss_tf": out.get("mss"), "direction": direction}

# ----------------------------------------------------------------- evaluation
SLOTS = ["market", "sweep_tf", "mss_tf", "direction"]
def evaluate(parser, data):
    hits = {s: 0 for s in SLOTS}; exact = 0; fails = []
    for text, gold in data:
        pred = parser(text); ok = True
        for s in SLOTS:
            if pred[s] == gold[s]: hits[s] += 1
            else: ok = False
        exact += ok
        if not ok: fails.append((text, gold, pred))
    n = len(data)
    return {s: hits[s] / n for s in SLOTS} | {"exact": exact / n, "n": n}, fails

# ----------------------------------------------------------------- NLG: alert JSON -> text
TXT = {
 "kk": dict(title="{ev} расталды · {sym}", dir_l="Бағыт: LONG (баға жоғары қарай күтіледі)", dir_s="Бағыт: SHORT (баға төмен қарай күтіледі)",
   low="төменгі ликвидностьте", high="жоғарғы ликвидностьте",
   sweep="{sym} нарығында {tf}м таймфреймде {side} Sweep болды: баға {lvl} деңгейін фитильмен алып, свеча деңгейдің ішінде жабылды.",
   raid="{sym} нарығында {tf}м таймфреймде {side} Raid болды: баға {lvl} деңгейін денемен бұзып, келесі свеча кері қайтып жабылды.",
   mss_up="Содан кейін {tf}м таймфреймде MSS расталды: баға {mss} деңгейін денемен бұзды, сондықтан жоғары қарай қозғалыс күтіледі.",
   mss_dn="Содан кейін {tf}м таймфреймде MSS расталды: баға {mss} деңгейін денемен бұзды, сондықтан төмен қарай қозғалыс күтіледі.",
   levels="Деңгейлер:", mss_lvl="MSS деңгейі", sweep_lvl="Sweep деңгейі", note="Деңгейлер дәл мәндер, бұл инвестициялық кеңес емес."),
 "ru": dict(title="{ev} подтверждён · {sym}", dir_l="Направление: LONG (ожидается рост цены)", dir_s="Направление: SHORT (ожидается падение цены)",
   low="нижней ликвидности", high="верхней ликвидности",
   sweep="На рынке {sym} на таймфрейме {tf}м произошёл Sweep {side}: цена забрала уровень {lvl} тенью, а свеча закрылась внутри уровня.",
   raid="На рынке {sym} на таймфрейме {tf}м произошёл Raid {side}: цена закрылась телом за уровнем {lvl}, а следующая свеча вернулась обратно.",
   mss_up="Затем на таймфрейме {tf}м подтверждён MSS: цена пробила уровень {mss} телом, поэтому ожидается движение вверх.",
   mss_dn="Затем на таймфрейме {tf}м подтверждён MSS: цена пробила уровень {mss} телом, поэтому ожидается движение вниз.",
   levels="Уровни:", mss_lvl="Уровень MSS", sweep_lvl="Уровень Sweep", note="Уровни указаны точно. Это не инвестиционная рекомендация."),
 "en": dict(title="{ev} confirmed · {sym}", dir_l="Direction: LONG (price expected to rise)", dir_s="Direction: SHORT (price expected to fall)",
   low="lower liquidity", high="upper liquidity",
   sweep="On {sym}, on the {tf}m timeframe, a Sweep of {side} happened: price took the {lvl} level with a wick and the candle closed back inside the level.",
   raid="On {sym}, on the {tf}m timeframe, a Raid of {side} happened: price closed with its body beyond the {lvl} level and the next candle reversed.",
   mss_up="Then, on the {tf}m timeframe, MSS was confirmed: price broke {mss} with a candle body, so an upward move is expected.",
   mss_dn="Then, on the {tf}m timeframe, MSS was confirmed: price broke {mss} with a candle body, so a downward move is expected.",
   levels="Levels:", mss_lvl="MSS level", sweep_lvl="Sweep level", note="Levels are exact values. This is not investment advice."),
}
def fmt(v): return ("%.5f" % v).rstrip("0").rstrip(".")
def explain(alert, lang="en"):
    t = TXT[lang]; long_ = alert["dir"] == "LONG"
    side = t["low"] if long_ else t["high"]
    kind = "raid" if alert["kind"] == "Raid" else "sweep"
    lines = [t["title"].format(ev=alert["event"], sym=alert["symbol"]), t["dir_l"] if long_ else t["dir_s"], ""]
    lines.append(t[kind].format(sym=alert["symbol"], tf=alert["sweep_tf"], side=side, lvl=fmt(alert["level"])))
    if alert["event"] == "MSS":
        lines.append((t["mss_up"] if long_ else t["mss_dn"]).format(tf=alert["mss_tf"], mss=fmt(alert["mss_level"])))
        lines += ["", t["levels"]]
        for k, label in (("tp4","TP 4"),("tp3","TP 3"),("tp2","TP 2"),("tp1","TP 1"),("entry","Entry")):
            lines.append("%s: %s" % (label, fmt(alert[k])))
        lines += ["%s: %s" % (t["mss_lvl"], fmt(alert["mss_level"])), "%s: %s" % (t["sweep_lvl"], fmt(alert["level"])), "Stop: %s" % fmt(alert["stop"])]
    lines += ["", t["note"]]
    return "\n".join(lines)

def numbers_in(text): return set(re.findall(r"\d+(?:\.\d+)?", text))
def faithful(alert, text):
    allowed = {fmt(v) for k, v in alert.items() if isinstance(v, float)} | {str(alert["sweep_tf"]), str(alert["mss_tf"]), "1", "2", "3", "4"}
    return numbers_in(text.replace(alert["symbol"], "")) <= allowed

def validate_alert(a):
    """Business-rule check on top of alert_schema.json: Stop < Entry < TP1 < ... < TP4 for LONG (reversed for SHORT)."""
    if a["event"] != "MSS": return True
    seq = [a["stop"], a["entry"], a["tp1"], a["tp2"], a["tp3"], a["tp4"]]
    inc = all(x < y for x, y in zip(seq, seq[1:])); dec = all(x > y for x, y in zip(seq, seq[1:]))
    return inc if a["dir"] == "LONG" else dec

SAMPLE = {"src":"GENESIS","event":"MSS","kind":"Sweep","symbol":"BTCUSD","sweep_tf":"3","mss_tf":"3","dir":"LONG","level":83691.23,"stop":83690.67,"entry":84078.01,"tp1":84317.38612,"tp2":84704.72612,"tp3":85092.06612,"tp4":85479.40612,"mss_level":83914.53,"time":"2026-10-11 22:33"}


# ----------------------------------------------------------------- demo / evaluation
if __name__ == "__main__":
    import nlp_data as D
    print("=== Text -> settings (NLU) ===")
    for text in ("золото: свип 60 минут, мсс 3 минуты, только лонг", "Биткоинге свип сағаттық, мсс 3 минут, екі жаққа", "bitcon sweep 60m mss 3m long"):
        print(text, "->", json.dumps(parse_improved(text), ensure_ascii=False))
    print()
    for name, p in (("baseline", parse_baseline), ("improved", parse_improved)):
        r, f = evaluate(p, D.TEST)
        print("TEST %-9s n=%d  market %.2f  sweep %.2f  mss %.2f  direction %.2f  exact %.2f" % (name, r["n"], r["market"], r["sweep_tf"], r["mss_tf"], r["direction"], r["exact"]))
    print()
    print("alert passes business rules:", validate_alert(SAMPLE)); print()
    print("=== Alert JSON -> text (NLG) ===")
    for lang in ("kk", "ru", "en"):
        t = explain(SAMPLE, lang); print(t, "\n", "faithful numbers:", faithful(SAMPLE, t), "\n")
