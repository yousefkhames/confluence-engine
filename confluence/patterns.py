"""Pattern library: repeating setups written as code rules, each with a plain-language statement
("if X from A to B then expect Y") and a backtest on real candles.

Pure standard library. A bar is a tuple (ts, open, high, low, close, volume), oldest first.
A rule looks only at bars[:i+1] (no look-ahead), and returns +1 (expect up), -1 (expect down) or 0.
The backtest enters at the NEXT bar's open and exits at the close `hold` bars later, net of fees and slippage.
Honest reporting: every rule is judged against the unconditional base rate, with a Wilson interval, and a
chronological in-sample / out-of-sample split. A rule is only called 'supported' when the out-of-sample result agrees.
"""
import math


# ---------- indicators (all causal) ----------
def sma(x, n, i):
    return sum(x[i - n + 1:i + 1]) / n if i >= n - 1 else None


def ema_series(x, n):
    k = 2 / (n + 1); out = []; e = None
    for v in x:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out


def rsi_series(c, n=14):
    out = [None] * len(c)
    if len(c) <= n:
        return out
    g = l = 0.0
    for i in range(1, n + 1):
        d = c[i] - c[i - 1]; g += max(d, 0); l += max(-d, 0)
    g /= n; l /= n
    out[n] = 100 - 100 / (1 + g / l) if l else 100.0
    for i in range(n + 1, len(c)):
        d = c[i] - c[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n; l = (l * (n - 1) + max(-d, 0)) / n
        out[i] = 100 - 100 / (1 + g / l) if l else 100.0
    return out


def atr_series(b, n=14):
    tr = [b[0][2] - b[0][3]] + [max(b[i][2] - b[i][3], abs(b[i][2] - b[i - 1][4]), abs(b[i][3] - b[i - 1][4])) for i in range(1, len(b))]
    out = [None] * len(b)
    for i in range(n - 1, len(b)):
        out[i] = sum(tr[i - n + 1:i + 1]) / n
    return out


class Ctx:
    """Precomputed causal indicators for one series."""
    def __init__(self, bars, fng=None):
        self.b = bars
        # Fear & Greed value for the bar's UTC day (published at the start of that day, so known when the bar opens)
        self.f = [(fng or {}).get(x[0] // 86400 * 86400) for x in bars]
        self.o = [x[1] for x in bars]; self.h = [x[2] for x in bars]; self.l = [x[3] for x in bars]
        self.c = [x[4] for x in bars]; self.v = [x[5] for x in bars]
        self.bw = None
        self.rsi = rsi_series(self.c); self.atr = atr_series(bars)
        self.e20 = ema_series(self.c, 20); self.e50 = ema_series(self.c, 50); self.e200 = ema_series(self.c, 200)

    def body(self, i):
        return abs(self.c[i] - self.o[i])

    def range(self, i):
        return self.h[i] - self.l[i]

    def lower_wick(self, i):
        return min(self.o[i], self.c[i]) - self.l[i]

    def upper_wick(self, i):
        return self.h[i] - max(self.o[i], self.c[i])

    def swing_lows(self, i, lookback=60, wing=3):
        """Confirmed swing lows (low lower than `wing` bars each side) fully known by bar i."""
        out = []
        for j in range(max(wing, i - lookback), i - wing):
            if all(self.l[j] <= self.l[j - k] and self.l[j] <= self.l[j + k] for k in range(1, wing + 1)):
                out.append(self.l[j])
        return out

    def swing_highs(self, i, lookback=60, wing=3):
        out = []
        for j in range(max(wing, i - lookback), i - wing):
            if all(self.h[j] >= self.h[j - k] and self.h[j] >= self.h[j + k] for k in range(1, wing + 1)):
                out.append(self.h[j])
        return out


# ---------- rules ----------
def r_support_bounce(x, i):
    """A bullish rejection candle (long lower wick, closes up) that dips into a prior swing low that already held once."""
    if i < 40 or x.atr[i] is None:
        return 0
    if x.c[i] <= x.o[i] or x.lower_wick(i) < max(x.body(i), 0.5 * x.range(i) * 0.6):
        return 0
    for s in x.swing_lows(i):
        if abs(x.l[i] - s) <= 0.35 * x.atr[i] and x.c[i] > s:
            return 1
    return 0


def r_resistance_rejection(x, i):
    if i < 40 or x.atr[i] is None:
        return 0
    if x.c[i] >= x.o[i] or x.upper_wick(i) < max(x.body(i), 0.5 * x.range(i) * 0.6):
        return 0
    for s in x.swing_highs(i):
        if abs(x.h[i] - s) <= 0.35 * x.atr[i] and x.c[i] < s:
            return -1
    return 0


def _breakout(x, i, up):
    if i < 25:
        return 0
    vavg = sum(x.v[i - 20:i]) / 20 or 1e-9
    if up and x.c[i] > max(x.h[i - 20:i]) and x.v[i] > 1.5 * vavg:
        return 1
    if not up and x.c[i] < min(x.l[i - 20:i]) and x.v[i] > 1.5 * vavg:
        return -1
    return 0


def r_breakout_up(x, i):
    return _breakout(x, i, True)


def r_breakdown(x, i):
    return _breakout(x, i, False)


def r_oversold_engulfing(x, i):
    if i < 20 or x.rsi[i] is None or x.rsi[i - 1] is None:
        return 0
    if x.rsi[i - 1] < 32 and x.c[i - 1] < x.o[i - 1] and x.c[i] > x.o[i] and x.c[i] >= x.o[i - 1] and x.o[i] <= x.c[i - 1]:
        return 1
    return 0


def r_overbought_engulfing(x, i):
    if i < 20 or x.rsi[i] is None or x.rsi[i - 1] is None:
        return 0
    if x.rsi[i - 1] > 68 and x.c[i - 1] > x.o[i - 1] and x.c[i] < x.o[i] and x.c[i] <= x.o[i - 1] and x.o[i] >= x.c[i - 1]:
        return -1
    return 0


def r_squeeze_breakout(x, i):
    """Bollinger bandwidth in its lowest 10% of the last 100 bars, then a close outside the 20-bar range."""
    if i < 120:
        return 0
    if x.bw is None:
        x.bw = [None] * len(x.c)
        for j in range(19, len(x.c)):
            w = x.c[j - 19:j + 1]; m = sum(w) / 20
            x.bw[j] = 4 * (sum((v - m) ** 2 for v in w) / 20) ** 0.5 / m if m else 0
    cur = x.bw[i - 1]; hist = sorted(x.bw[i - 100:i])
    if cur > hist[10]:
        return 0
    if x.c[i] > max(x.h[i - 20:i]):
        return 1
    if x.c[i] < min(x.l[i - 20:i]):
        return -1
    return 0


def r_trend_pullback(x, i):
    """Uptrend (close > EMA50 > EMA200), price pulls back to EMA20 and prints a bullish candle."""
    if i < 210:
        return 0
    if x.c[i] > x.e50[i] > x.e200[i] and x.l[i] <= x.e20[i] and x.c[i] > x.o[i] and x.c[i] > x.e20[i]:
        return 1
    return 0


def r_downtrend_rally_fail(x, i):
    if i < 210:
        return 0
    if x.c[i] < x.e50[i] < x.e200[i] and x.h[i] >= x.e20[i] and x.c[i] < x.o[i] and x.c[i] < x.e20[i]:
        return -1
    return 0


def r_four_down_reversal(x, i):
    """Four red bars in a row, then a green bar closing above the previous bar's high: expect a bounce."""
    if i < 6:
        return 0
    if all(x.c[i - k] < x.o[i - k] for k in range(1, 5)) and x.c[i] > x.o[i] and x.c[i] > x.h[i - 1]:
        return 1
    return 0


def r_exhaustion_spike(x, i):
    """A bar that moves more than 3 ATR down on 2x volume often over-extends: expect a partial retrace."""
    if i < 30 or x.atr[i - 1] is None:
        return 0
    vavg = sum(x.v[i - 20:i]) / 20 or 1e-9
    if x.o[i] - x.c[i] > 3 * x.atr[i - 1] and x.v[i] > 2 * vavg:
        return 1
    return 0


def r_inside_bar_breakout(x, i):
    """Inside bar (range within previous bar) followed by a close above its high, in an uptrend."""
    if i < 60:
        return 0
    if x.h[i - 1] < x.h[i - 2] and x.l[i - 1] > x.l[i - 2] and x.c[i] > x.h[i - 2] and x.c[i] > x.e50[i]:
        return 1
    return 0


# ---------- trader-psychology rules (fear, greed, panic, FOMO) ----------
def r_extreme_fear_turn(x, i):
    """Crowd in extreme fear (Fear & Greed <= 20) and the first bar that closes above the prior high: expect a relief bounce."""
    if i < 5 or x.f[i] is None:
        return 0
    return 1 if x.f[i] <= 20 and x.c[i] > x.o[i] and x.c[i] > x.h[i - 1] else 0


def r_extreme_greed_fade(x, i):
    """Crowd in extreme greed (Fear & Greed >= 80) and the first bar that closes below the prior low: expect a pullback."""
    if i < 5 or x.f[i] is None:
        return 0
    return -1 if x.f[i] >= 80 and x.c[i] < x.o[i] and x.c[i] < x.l[i - 1] else 0


def r_capitulation(x, i):
    """Panic: more than 15% down over 3 bars on 2x volume with RSI < 30, then a green bar: expect a rebound."""
    if i < 25 or x.rsi[i] is None:
        return 0
    vavg = sum(x.v[i - 20:i]) / 20 or 1e-9
    drop = x.c[i - 1] / x.c[i - 4] - 1
    return 1 if drop < -0.15 and max(x.v[i - 3:i]) > 2 * vavg and x.rsi[i - 1] < 30 and x.c[i] > x.o[i] else 0


def r_fomo_blowoff(x, i):
    """FOMO: RSI > 78 and price more than 20% above EMA50, then a red bar: expect a pullback."""
    if i < 60 or x.rsi[i] is None:
        return 0
    return -1 if x.rsi[i - 1] > 78 and x.c[i - 1] > 1.2 * x.e50[i - 1] and x.c[i] < x.o[i] else 0


def r_sentiment_thaw(x, i):
    """Mood turning: Fear & Greed rose 15+ points over 7 bars from below 30 (fear easing): expect a rise."""
    if i < 10 or x.f[i] is None or x.f[i - 7] is None:
        return 0
    return 1 if x.f[i - 7] < 30 and x.f[i] - x.f[i - 7] >= 15 else 0


def r_complacency_top(x, i):
    """Greed cooling: Fear & Greed fell 15+ points over 7 bars from above 70 (greed fading): expect a fall."""
    if i < 10 or x.f[i] is None or x.f[i - 7] is None:
        return 0
    return -1 if x.f[i - 7] > 70 and x.f[i - 7] - x.f[i] >= 15 else 0


PSYCH = [
    ("extreme_fear_turn", "If the crowd is in extreme fear (Fear & Greed <= 20) and a bar closes green above the prior high, expect a relief bounce over the next 6 bars.", r_extreme_fear_turn, 6, ("1d", "6h")),
    ("extreme_greed_fade", "If the crowd is in extreme greed (Fear & Greed >= 80) and a bar closes red below the prior low, expect a pullback over the next 6 bars.", r_extreme_greed_fade, 6, ("1d", "6h")),
    ("capitulation_rebound", "If price fell more than 15% in 3 bars on 2x volume with RSI < 30 (panic) and a green bar follows, expect a rebound over the next 6 bars.", r_capitulation, 6, ("1d", "6h")),
    ("fomo_blowoff_fade", "If RSI > 78 and price is more than 20% above EMA50 (FOMO) and a red bar follows, expect a pullback over the next 6 bars.", r_fomo_blowoff, 6, ("1d", "6h")),
    ("fear_thaw", "If Fear & Greed rose 15+ points in 7 bars from below 30 (fear easing), expect a rise over the next 6 bars.", r_sentiment_thaw, 6, ("1d",)),
    ("greed_cooling", "If Fear & Greed fell 15+ points in 7 bars from above 70 (greed fading), expect a fall over the next 6 bars.", r_complacency_top, 6, ("1d",)),
]


# id, rule text, function, hold bars (optional 5th item: allowed timeframes)
RULES = [
    ("support_bounce", "If price dips into a prior swing low that already held once and prints a bullish rejection candle, expect a rise over the next 6 bars.", r_support_bounce, 6),
    ("resistance_rejection", "If price pokes into a prior swing high and prints a bearish rejection candle, expect a fall over the next 6 bars.", r_resistance_rejection, 6),
    ("breakout_up_volume", "If a bar closes above the 20-bar high on 1.5x average volume, expect continuation up over the next 6 bars.", r_breakout_up, 6),
    ("breakdown_volume", "If a bar closes below the 20-bar low on 1.5x average volume, expect continuation down over the next 6 bars.", r_breakdown, 6),
    ("oversold_engulfing", "If RSI(14) was below 32 and a bullish engulfing candle follows, expect a rise over the next 6 bars.", r_oversold_engulfing, 6),
    ("overbought_engulfing", "If RSI(14) was above 68 and a bearish engulfing candle follows, expect a fall over the next 6 bars.", r_overbought_engulfing, 6),
    ("squeeze_breakout", "If volatility is in its lowest 10% of the last 100 bars and price then closes outside the 20-bar range, expect continuation in that direction over the next 12 bars.", r_squeeze_breakout, 12),
    ("trend_pullback", "If close > EMA50 > EMA200 and price pulls back to EMA20 then closes green above it, expect a rise over the next 12 bars.", r_trend_pullback, 12),
    ("downtrend_rally_fail", "If close < EMA50 < EMA200 and a rally into EMA20 closes red below it, expect a fall over the next 12 bars.", r_downtrend_rally_fail, 12),
    ("four_down_reversal", "If four red bars in a row are followed by a green bar closing above the prior high, expect a bounce over the next 6 bars.", r_four_down_reversal, 6),
    ("exhaustion_spike_retrace", "If one bar falls more than 3 ATR on 2x volume, expect a partial retrace over the next 6 bars.", r_exhaustion_spike, 6),
    ("inside_bar_breakout_up", "If an inside bar is followed by a close above its mother bar's high while close > EMA50, expect a rise over the next 6 bars.", r_inside_bar_breakout, 6),
]

RULES = RULES + PSYCH


# ---------- backtest ----------
def wilson(k, n, z=1.96):
    if n == 0:
        return [None, None]
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; w = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - w, 4), round(c + w, 4)]


def scan(bars, rule_fn, hold, cost_pct, ctx=None, fng=None):
    """Return list of trades [(ts, direction, net_ret_pct, gross_ret_pct)] for one series. No overlapping trades."""
    x = ctx or Ctx(bars, fng); out = []; busy = -1
    for i in range(30, len(bars) - hold - 1):
        if i <= busy:
            continue
        d = rule_fn(x, i)
        if d:
            entry = bars[i + 1][1]; exit_ = bars[i + hold][4]
            if entry <= 0:
                continue
            g = (exit_ / entry - 1) * 100 * d
            out.append((bars[i][0], d, g - cost_pct, g))
            busy = i + hold
    return out


def base_rate(bars, hold, direction_list):
    """Share of all entries (next open -> close after hold) that went up, for context."""
    ups = n = 0
    for i in range(30, len(bars) - hold - 1, max(1, hold)):
        entry = bars[i + 1][1]; ex = bars[i + hold][4]
        if entry > 0:
            n += 1; ups += ex > entry
    return ups, n


def summarize(trades):
    n = len(trades)
    if not n:
        return {"n": 0}
    hits = sum(1 for t in trades if t[3] > 0)
    net = [t[2] for t in trades]
    return {"n": n, "hit_rate": round(hits / n, 4), "hit_ci95": wilson(hits, n), "avg_gross_pct": round(sum(t[3] for t in trades) / n, 4),
            "avg_net_pct": round(sum(net) / n, 4), "total_net_pct": round(sum(net), 2)}


def backtest_rule(series, rule, cost_pct, split=0.7, fng=None):
    """series: {(symbol, tf): bars}. Judge against the base rate of the same direction; split by time, not by random."""
    rid, text, fn, hold = rule[:4]; tfs = rule[4] if len(rule) > 4 else None
    allt = []; ups = nb = 0; ups_dirs = []
    for (sym, tf), bars in series.items():
        if len(bars) < 260 or (tfs and tf not in tfs):
            continue
        for t in scan(bars, fn, hold, cost_pct, fng=fng):
            allt.append((t[0], t[1], t[2], t[3], sym, tf))
        u, n = base_rate(bars, hold, None); ups += u; nb += n
    allt.sort()
    res = {"id": rid, "rule": text, "hold_bars": hold, "all": summarize(allt)}
    if not allt:
        res["status"] = "no occurrences"; return res
    cut = allt[0][0] + (allt[-1][0] - allt[0][0]) * split
    res["in_sample"] = summarize([t for t in allt if t[0] <= cut])
    res["out_of_sample"] = summarize([t for t in allt if t[0] > cut])
    up_rate = ups / nb if nb else 0.5
    share_long = sum(1 for t in allt if t[1] == 1) / len(allt)
    res["base_rate_hit"] = round(share_long * up_rate + (1 - share_long) * (1 - up_rate), 4)
    res["direction"] = "long" if share_long > 0.99 else "short" if share_long < 0.01 else "both"
    o = res["out_of_sample"]; a = res["all"]
    if a["n"] < 30 or o.get("n", 0) < 15:
        res["status"] = "insufficient data"
    else:
        lo_all = wilson(round(a["hit_rate"] * a["n"]), a["n"], z=2.8)[0]   # wide interval: 12 rules are tested at once
        if lo_all > res["base_rate_hit"] and o["hit_rate"] > res["base_rate_hit"] and a["avg_net_pct"] > 0 and o["avg_net_pct"] > 0:
            res["status"] = "supported (beats base rate and costs, in and out of sample)"
        elif a["hit_rate"] > res["base_rate_hit"] and a["hit_ci95"][1] > res["base_rate_hit"] and o["hit_rate"] > res["base_rate_hit"]:
            res["status"] = "weak (beats base rate but not costs or not significant)"
        else:
            res["status"] = "not supported"
    res["by_tf"] = {}
    for tf in sorted({t[5] for t in allt}):
        res["by_tf"][tf] = summarize([t for t in allt if t[5] == tf])
    return res


def run_all(series, cost_pct, fng=None):
    return [backtest_rule(series, r, cost_pct, fng=fng) for r in RULES]


def live_matches(series, last_n=1, fng=None):
    """Which rules fire on the newest closed bar of each series (for the dashboard)."""
    out = []
    for (sym, tf), bars in series.items():
        if len(bars) < 260:
            continue
        x = Ctx(bars, fng); i = len(bars) - 1
        for rule in RULES:
            rid, text, fn, hold = rule[:4]
            if len(rule) > 4 and rule[4] and tf not in rule[4]:
                continue
            try:
                d = fn(x, i)
            except Exception:
                d = 0
            if d:
                out.append({"symbol": sym, "tf": tf, "rule": rid, "direction": "long" if d > 0 else "short", "bar_ts": bars[i][0], "price": bars[i][4]})
    return out
