"""nlp2: text scoring for the Confluence engine. Standard library only, offline.

- FinBERT-compatible interface (score(text) -> {positive,negative,neutral,label,score,model}).
  FinBERTScorer uses `transformers` only if already installed with cached weights;
  get_scorer() otherwise returns LexiconScorer, which needs nothing.
- urgency(text), source_credibility(url_or_name), bot_features(posts), analyze(...)
- own table nlp2_scores via init(con) (CREATE TABLE IF NOT EXISTS).
Research only. No orders, no keys, no network.
"""
import math
import re
import time
from urllib.parse import urlparse

_TOKEN = re.compile(r"[a-z][a-z'\-]*|\$[a-z]{2,6}|\d+(?:\.\d+)?%?")

POS = {
    "surge": 2, "surges": 2, "soar": 2, "soars": 2, "rally": 1.5, "rallies": 1.5, "beat": 1.5,
    "beats": 1.5, "bullish": 2, "gain": 1, "gains": 1, "growth": 1, "approve": 1.5,
    "approved": 1.5, "approval": 1.5, "record": 1, "upgrade": 1.5, "upgraded": 1.5,
    "profit": 1.5, "profits": 1.5, "strong": 1, "rise": 1, "rises": 1, "rose": 1,
    "breakout": 1.5, "adoption": 1, "inflows": 1.5, "inflow": 1.5, "outperform": 1.5,
    "recovery": 1, "recover": 1, "support": 0.5, "buy": 1, "accumulate": 1, "positive": 1,
    "optimism": 1, "optimistic": 1, "boost": 1, "boosts": 1, "wins": 1, "launch": 0.5,
}
NEG = {
    "crash": -2.5, "crashes": -2.5, "plunge": -2, "plunges": -2, "plummet": -2, "plummets": -2,
    "bearish": -2, "loss": -1.5, "losses": -1.5, "drop": -1, "drops": -1, "fall": -1,
    "falls": -1, "fell": -1, "decline": -1, "declines": -1, "miss": -1.5, "missed": -1.5,
    "hack": -2.5, "hacked": -2.5, "exploit": -2.5, "exploited": -2.5, "rug": -2.5,
    "rugpull": -3, "scam": -3, "fraud": -3, "lawsuit": -1.5, "sue": -1.5, "sues": -1.5,
    "ban": -2, "banned": -2, "bankruptcy": -3, "bankrupt": -3, "insolvent": -3,
    "insolvency": -3, "liquidation": -2, "liquidations": -2, "liquidated": -2,
    "outflows": -1.5, "outflow": -1.5, "downgrade": -1.5, "downgraded": -1.5,
    "default": -2, "selloff": -2, "sell-off": -2, "fear": -1.5, "panic": -2, "weak": -1,
    "delist": -2, "delisted": -2, "halt": -1.5, "halted": -1.5, "investigation": -1.5,
    "probe": -1.5, "warning": -1, "risk": -0.5, "risks": -0.5, "negative": -1, "dump": -2,
    "dumps": -2, "sell": -0.5, "recession": -2, "layoffs": -1.5, "breach": -2.5,
}
NEGATORS = {"not", "no", "never", "without", "isn't", "wasn't", "doesn't", "didn't",
            "won't", "can't", "cannot", "fails", "failed", "fail", "unlikely"}
BOOSTERS = {"very": 1.3, "highly": 1.3, "massive": 1.4, "huge": 1.4, "extremely": 1.5,
            "sharply": 1.3, "slightly": 0.6, "slight": 0.6, "marginally": 0.5}


def _lookup(t):
    for c in (t, t[:-1] if t.endswith("s") else t, t[:-2] if t.endswith(("es", "ed")) else t,
              t[:-1] if t.endswith("d") else t):
        v = POS.get(c, 0) or NEG.get(c, 0)
        if v:
            return v
    return 0


def _pack(p, n, u, model):
    label = max((("positive", p), ("negative", n), ("neutral", u)), key=lambda x: x[1])[0]
    return {"positive": p, "negative": n, "neutral": u, "label": label,
            "score": p - n, "model": model}


class LexiconScorer:
    """Offline fallback with FinBERT's output shape. score = P(pos) - P(neg)."""
    name = "lexicon-v1"

    def score(self, text):
        toks = _TOKEN.findall((text or "").lower())
        pos = neg = 0.0
        for i, t in enumerate(toks):
            v = _lookup(t)
            if not v:
                continue
            window = toks[max(0, i - 3):i]
            if any(w in NEGATORS for w in window):
                v = -v * 0.8
            for w in window:
                v *= BOOSTERS.get(w, 1.0)
            if v > 0:
                pos += v
            else:
                neg += -v
        e_pos, e_neg, e_neu = math.exp(pos), math.exp(neg), math.exp(1.0)
        z = e_pos + e_neg + e_neu
        return _pack(e_pos / z, e_neg / z, e_neu / z, self.name)

    def score_many(self, texts):
        return [self.score(t) for t in texts]


class FinBERTScorer:
    """Wraps a locally cached FinBERT via transformers if present. Never
    downloads (local_files_only). Raises RuntimeError if unavailable."""

    def __init__(self, model="ProsusAI/finbert"):
        try:
            pipeline = __import__("transformers").pipeline  # optional, guarded
            self._pipe = pipeline("text-classification", model=model, top_k=None,
                                  model_kwargs={"local_files_only": True})
        except Exception as exc:
            raise RuntimeError("FinBERT unavailable: %s" % exc)
        self.name = "finbert:" + model

    def score(self, text):
        out = self._pipe((text or "")[:2000])
        out = out[0] if out and isinstance(out[0], list) else out
        d = {r["label"].lower(): float(r["score"]) for r in out}
        return _pack(d.get("positive", 0.0), d.get("negative", 0.0), d.get("neutral", 0.0), self.name)

    def score_many(self, texts):
        return [self.score(t) for t in texts]


def get_scorer(prefer_finbert=True):
    if prefer_finbert:
        try:
            return FinBERTScorer()
        except RuntimeError:
            pass
    return LexiconScorer()


# ---------------- urgency ----------------
_URGENT_TERMS = {
    "breaking": 3, "urgent": 3, "alert": 2, "just in": 3, "flash": 2, "halted": 3,
    "halt": 2, "emergency": 3, "hack": 3, "hacked": 3, "exploit": 3, "exploited": 3,
    "liquidation": 2, "liquidations": 2, "depeg": 3, "depegged": 3, "insolvent": 3,
    "bankruptcy": 3, "delist": 2, "delisted": 2, "sec charges": 3, "lawsuit": 1,
    "now": 1, "immediately": 2, "outage": 2, "withdrawals paused": 3,
    "suspended": 2, "suspends": 2, "circuit breaker": 3, "crash": 2, "plunge": 2,
}
_SCHEDULED = ("scheduled", "will announce", "expected on", "next week", "next month",
              "upcoming", "later this", "weekly", "monthly recap", "preview")


def urgency(text):
    """0..1. Incident and breaking words raise it, scheduled/preview language
    halves it, ALL CAPS and exclamation marks add a little."""
    t = (text or "").lower()
    if not t.strip():
        return 0.0
    raw = 0.0
    for term, w in _URGENT_TERMS.items():
        if re.search(r"\b" + re.escape(term) + r"\b", t):
            raw += w
    letters = [c for c in text if c.isalpha()]
    caps = sum(c.isupper() for c in letters) / len(letters) if len(letters) >= 8 else 0
    if caps > 0.6:
        raw += 1
    raw += min(2, text.count("!")) * 0.3
    if any(s in t for s in _SCHEDULED):
        raw *= 0.5
    return round(1 - math.exp(-raw / 3.0), 4)


# ---------------- source credibility ----------------
# Judgement-based priors, not measured. Tune from verified rows in trade_cases.
SOURCE_CREDIBILITY = {
    "sec.gov": 0.97, "federalreserve.gov": 0.97, "cftc.gov": 0.95, "ecb.europa.eu": 0.97,
    "treasury.gov": 0.95, "bls.gov": 0.96, "bea.gov": 0.96, "fred.stlouisfed.org": 0.95,
    "reuters.com": 0.9, "apnews.com": 0.9, "bloomberg.com": 0.88, "ft.com": 0.88,
    "wsj.com": 0.88, "cnbc.com": 0.78, "coindesk.com": 0.72, "theblock.co": 0.74,
    "cointelegraph.com": 0.6, "decrypt.co": 0.66, "bitcoinmagazine.com": 0.55,
    "github.com": 0.7, "coingecko.com": 0.75, "coinmarketcap.com": 0.72,
    "binance.com": 0.65, "coinbase.com": 0.7, "arxiv.org": 0.75, "ssrn.com": 0.65,
    "investopedia.com": 0.65, "wikipedia.org": 0.6, "medium.com": 0.35,
    "substack.com": 0.4, "reddit.com": 0.3, "x.com": 0.25, "twitter.com": 0.25,
    "telegram.org": 0.15, "t.me": 0.15, "youtube.com": 0.3, "tiktok.com": 0.15,
    "stocktwits.com": 0.25, "4chan.org": 0.1,
}
DEFAULT_CREDIBILITY = 0.3


def _domain(s):
    s = (s or "").strip().lower()
    host = urlparse(s if "//" in s else "//" + s).netloc or s
    host = host.split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


def source_credibility(url_or_name):
    """Prior 0..1. Parent domains match (news.bloomberg.com -> bloomberg.com).
    Unlisted *.gov / *.edu get 0.8; unknown gets 0.3."""
    parts = _domain(url_or_name).split(".")
    for i in range(len(parts) - 1):
        d = ".".join(parts[i:])
        if d in SOURCE_CREDIBILITY:
            return SOURCE_CREDIBILITY[d]
    if parts and parts[-1] in ("gov", "edu"):
        return 0.8
    return DEFAULT_CREDIBILITY


# ---------------- bot features ----------------
_SHILL = ("100x", "1000x", "guaranteed", "moon", "gem", "airdrop", "dm me", "join now",
          "don't miss", "last chance", "pump", "free money", "act fast")


def _norm(t):
    return re.sub(r"\W+", " ", (t or "").lower()).strip()


def bot_features(posts):
    """posts: dicts with text, and optionally ts (epoch s), author,
    account_age_days, followers, following. Heuristic bot_score 0..1."""
    n = len(posts)
    if n == 0:
        return {"n": 0, "bot_score": 0.0}
    texts = [_norm(p.get("text")) for p in posts]
    dup_ratio = 1 - len(set(texts)) / n
    low = [(p.get("text") or "").lower() for p in posts]
    shill = sum(any(k in x for k in _SHILL) for x in low) / n
    link = sum("http" in x for x in low) / n
    tags = sum(len(re.findall(r"[#$@]\w+", p.get("text") or "")) for p in posts) / n
    ts = sorted(p["ts"] for p in posts if p.get("ts") is not None)
    burst = 0.0
    if len(ts) >= 3:
        gaps = [b - a for a, b in zip(ts, ts[1:])]
        mean = sum(gaps) / len(gaps)
        if mean > 0:
            cv = math.sqrt(sum((g - mean) ** 2 for g in gaps) / len(gaps)) / mean
            rate = 3600 / mean
            burst = max(1.0 if cv < 0.15 and rate > 6 else 0.0, min(1.0, rate / 60))
        else:
            burst = 1.0
    ages = [p["account_age_days"] for p in posts if p.get("account_age_days") is not None]
    young = sum(a < 30 for a in ages) / len(ages) if ages else 0.0
    ratios = [p["following"] / max(1, p["followers"]) for p in posts
              if p.get("following") is not None and p.get("followers") is not None]
    skew = sum(r > 10 for r in ratios) / len(ratios) if ratios else 0.0
    authors = [p["author"] for p in posts if p.get("author")]
    conc = max(authors.count(a) for a in set(authors)) / len(authors) if len(authors) >= 5 else 0.0
    score = (0.25 * dup_ratio + 0.2 * shill + 0.1 * link + 0.05 * min(1, tags / 4)
             + 0.15 * burst + 0.1 * young + 0.05 * skew + 0.1 * conc)
    return {"n": n, "dup_ratio": round(dup_ratio, 4), "shill_ratio": round(shill, 4),
            "link_ratio": round(link, 4), "tags_per_post": round(tags, 3),
            "burstiness": round(burst, 4), "young_account_ratio": round(young, 4),
            "follow_skew": round(skew, 4), "author_concentration": round(conc, 4),
            "bot_score": round(min(1.0, score * 1.6), 4)}


# ---------------- combined ----------------
def analyze(text, source=None, posts=None, scorer=None):
    """weight = credibility * (1 - 0.7*bot_score); weighted_score = sentiment * weight."""
    sc = (scorer or LexiconScorer()).score(text)
    cred = source_credibility(source) if source else DEFAULT_CREDIBILITY
    bots = bot_features(posts) if posts else None
    weight = cred * (1 - 0.7 * (bots["bot_score"] if bots else 0.0))
    return {"sentiment": sc, "urgency": urgency(text), "credibility": cred,
            "bot": bots, "weight": round(weight, 4),
            "weighted_score": round(sc["score"] * weight, 4)}


# ---------------- storage (own table) ----------------
def init(con):
    con.execute("""CREATE TABLE IF NOT EXISTS nlp2_scores(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, source_url TEXT, model TEXT,
        label TEXT, score REAL, urgency REAL, credibility REAL, bot_score REAL,
        weight REAL, weighted_score REAL)""")
    con.commit()


def store(con, text, source_url=None, posts=None, scorer=None):
    init(con)
    r = analyze(text, source_url, posts, scorer)
    con.execute("""INSERT INTO nlp2_scores(ts,source_url,model,label,score,urgency,
        credibility,bot_score,weight,weighted_score) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (time.time(), source_url, r["sentiment"]["model"], r["sentiment"]["label"],
         r["sentiment"]["score"], r["urgency"], r["credibility"],
         r["bot"]["bot_score"] if r["bot"] else None, r["weight"], r["weighted_score"]))
    con.commit()
    return r
