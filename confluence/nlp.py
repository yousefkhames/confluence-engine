"""Light NLP, no model downloads: finance lexicon sentiment, urgency, source credibility, bot filter.
The interface (score_text) is the swap point for FinBERT or an LLM API later."""
import re, hashlib
from collections import Counter

POS = {"surge","soar","rally","partnership","approve","approval","approved","listing","lists","listed","adopt","adoption",
       "launch","upgrade","bullish","record","inflow","inflows","buy","buys","bought","accumulate","etf","integration",
       "breakout","gain","gains","wins","win","backed","invest","invests","milestone","burn"}
NEG = {"hack","hacked","exploit","exploited","ban","bans","banned","lawsuit","sues","sued","fraud","scam","rug",
       "crash","plunge","dump","dumps","bearish","outflow","outflows","liquidation","liquidated","delist","delisting",
       "halt","halted","outage","breach","stolen","probe","investigation","insolvent","bankruptcy","sell-off","selloff","fear"}
URGENT = {"breaking","just in","alert","urgent","halts","halted","hacked","exploit","approves","approved","lists","listing",
          "announces","announced","sec","etf","delist","delisting","liquidation","emergency"}
SOURCE_CRED = {"coindesk": 0.85, "cointelegraph": 0.75, "theblock": 0.85, "decrypt": 0.75, "reuters": 0.95,
               "bloomberg": 0.95, "watcherguru": 0.55, "tier10k": 0.55}

def _tokens(t):
    return re.findall(r"[a-z\-]+", t.lower())

def score_text(text):
    """Return (sentiment in [-1,1], urgency in [0,1]). Set CONFLUENCE_NLP=2 to use confluence.nlp2 (FinBERT if cached)."""
    import os
    if os.environ.get("CONFLUENCE_NLP") == "2":
        from . import nlp2
        a = nlp2.analyze(text)
        return a["sentiment"]["score"], a["urgency"]
    toks = _tokens(text)
    low = text.lower()
    p = sum(1 for w in toks if w in POS)
    n = sum(1 for w in toks if w in NEG)
    sent = 0.0 if p + n == 0 else (p - n) / (p + n)
    sent *= min(1.0, 0.5 + 0.25 * (p + n))
    u = sum(1 for w in URGENT if w in low)
    return max(-1, min(1, sent)), min(1.0, 0.2 + 0.25 * u) if u else 0.2

def source_credibility(source):
    s = (source or "").lower()
    for k, v in SOURCE_CRED.items():
        if k in s:
            return v
    return 0.5

def mentions(text, coins, names=None):
    """Which tracked coins does a text mention (ticker as whole word or common name)."""
    names = names or NAMES
    low = text.lower()
    out = []
    for c in coins:
        if re.search(r"\b" + c.lower() + r"\b", low) or any(re.search(r"\b" + n + r"\b", low) for n in names.get(c, [])):
            out.append(c)
    return out

NAMES = {"BTC": ["bitcoin"], "ETH": ["ethereum", "ether"], "SOL": ["solana"], "XRP": ["ripple"], "ADA": ["cardano"],
         "DOGE": ["dogecoin"], "AVAX": ["avalanche"], "LINK": ["chainlink"], "DOT": ["polkadot"], "LTC": ["litecoin"],
         "BCH": ["bitcoin cash"], "ATOM": ["cosmos"], "UNI": ["uniswap"], "NEAR": ["near protocol"], "APT": ["aptos"],
         "ARB": ["arbitrum"], "OP": ["optimism"], "AAVE": ["aave"], "FIL": ["filecoin"], "ETC": ["ethereum classic"]}

def flag_bots(posts):
    """posts: list of dicts with text, author, author_age_days, ts, engagement.
    Marks p['is_bot'] in [0,1]. Signals: young account, duplicate text across authors, same-second bursts,
    near-zero engagement on a high-volume author."""
    norm = lambda t: hashlib.md5(re.sub(r"\W+", " ", t.lower()).strip().encode()).hexdigest()
    dup = Counter(norm(p["text"]) for p in posts)
    sec = Counter(int(p["ts"]) for p in posts)
    per_author = Counter(p["author"] for p in posts)
    for p in posts:
        s = 0.0
        if (p.get("author_age_days") or 999) < 30: s += 0.35
        if dup[norm(p["text"])] >= 3: s += 0.4
        if sec[int(p["ts"])] >= 4: s += 0.25
        if per_author[p["author"]] >= 5 and (p.get("engagement") or 0) < 1: s += 0.2
        p["is_bot"] = min(1.0, s)
    return posts
