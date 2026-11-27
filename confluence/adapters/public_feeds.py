"""Extra free, keyless, public sources. Read-only. Each collector returns the number of new rows and logs its status.

Real and working (checked from a cloud runner): GDELT DOC API, SEC and Federal Reserve press RSS, CryptoSlate and
The Defiant RSS, Fear & Greed index, DeFiLlama stablecoin supply, Hyperliquid public leaderboard + public account
positions (read-only 'info' POSTs, no key, no signing).
Not available free: X/Twitter API (paid), Nitter mirrors (dead), Bluesky search (blocked without login), paid wallet
labels (Arkham/Nansen/Whale Alert). We do not scrape behind logins.
"""
import hashlib, json, time, datetime, re, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from ._http import get, UA
from .. import config, nlp

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, ts REAL, source TEXT, kind TEXT, title TEXT, url TEXT, sentiment REAL, urgency REAL, coins TEXT);
CREATE TABLE IF NOT EXISTS market_ctx(ts REAL, key TEXT, value REAL, label TEXT, PRIMARY KEY(ts, key));
CREATE TABLE IF NOT EXISTS smart_traders(ts REAL, addr TEXT, account_usd REAL, pnl_week REAL, pnl_month REAL, pnl_all REAL, roi_month REAL, PRIMARY KEY(ts, addr));
CREATE TABLE IF NOT EXISTS smart_flow(ts REAL, symbol TEXT, long_usd REAL, short_usd REAL, n_traders INTEGER, PRIMARY KEY(ts, symbol));
CREATE TABLE IF NOT EXISTS source_status(ts REAL, source TEXT, ok INTEGER, items INTEGER, note TEXT, PRIMARY KEY(ts, source));
"""

GOV_FEEDS = {"SEC press releases": "https://www.sec.gov/news/pressreleases.rss",
             "Federal Reserve press": "https://www.federalreserve.gov/feeds/press_all.xml"}
EXTRA_NEWS = {"CryptoSlate": "https://cryptoslate.com/feed/", "TheDefiant": "https://thedefiant.io/api/feed"}
GDELT = ("https://api.gdeltproject.org/api/v2/doc/doc?query=%28bitcoin+OR+ethereum+OR+cryptocurrency+OR+%22crypto+market%22%29"
         "&mode=artlist&maxrecords=60&format=json&timespan=2h&sort=datedesc")
HL_BOARD = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
HL_INFO = "https://api.hyperliquid.xyz/info"
FNG = "https://api.alternative.me/fng/?limit=1"
STABLES = "https://stablecoins.llama.fi/stablecoins?includePrices=false"


def init(con):
    con.executescript(SCHEMA); con.commit()


def _status(con, source, ok, items, note=""):
    con.execute("INSERT OR REPLACE INTO source_status VALUES(?,?,?,?,?)", (time.time(), source, 1 if ok else 0, items, str(note)[:200]))


def _id(*p):
    return hashlib.md5("|".join(str(x) for x in p).encode()).hexdigest()


def _rss(text):
    root = ET.fromstring(text)
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip(); link = (it.findtext("link") or "").strip(); pub = it.findtext("pubDate")
        try:
            import email.utils
            ts = email.utils.parsedate_to_datetime(pub).timestamp()
        except Exception:
            continue
        yield title, link, ts


def _add_event(con, source, kind, title, url, ts):
    s, u = nlp.score_text(title)
    coins = ",".join(nlp.mentions(title, config.COINS))
    cur = con.execute("INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?,?,?)", (_id(source, url or title), ts, source, kind, title[:300], url, s, u, coins))
    return cur.rowcount


def fetch_gov(con, getter=None):
    getter = getter or (lambda u: get(u, as_json=False))
    for name, url in GOV_FEEDS.items():
        n = 0
        try:
            for title, link, ts in _rss(getter(url)):
                n += _add_event(con, name, "official", title, link, ts)
            _status(con, name, True, n)
        except Exception as e:
            _status(con, name, False, 0, e)
    con.commit()


def fetch_extra_news(con, getter=None):
    """Same `news` table the scorer already reads."""
    getter = getter or (lambda u: get(u, as_json=False))
    for name, url in EXTRA_NEWS.items():
        n = 0
        try:
            for title, link, ts in _rss(getter(url)):
                s, u = nlp.score_text(title); cred = nlp.source_credibility(name)
                for c in nlp.mentions(title, config.COINS):
                    cur = con.execute("INSERT OR IGNORE INTO news VALUES(?,?,?,?,?,?,?,?,?)",
                                      (_id(link, c), ts, c, title, name, link, s, u, cred)); n += cur.rowcount
            _status(con, name, True, n)
        except Exception as e:
            _status(con, name, False, 0, e)
    con.commit()


def parse_gdelt(js):
    for a in js.get("articles", []):
        try:
            ts = datetime.datetime.strptime(a["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=datetime.timezone.utc).timestamp()
        except Exception:
            continue
        yield (a.get("title") or "").strip(), a.get("url") or "", ts, a.get("domain") or ""


def fetch_gdelt(con, getter=None):
    getter = getter or get
    try:
        n = 0
        for title, url, ts, dom in parse_gdelt(getter(GDELT)):
            n += _add_event(con, "GDELT:" + dom, "news_wire", title, url, ts)
        _status(con, "GDELT", True, n); con.commit()
    except Exception as e:
        _status(con, "GDELT", False, 0, e)


def fetch_ctx(con, getter=None):
    getter = getter or get
    now = time.time()
    try:
        d = getter(FNG)["data"][0]
        con.execute("INSERT OR REPLACE INTO market_ctx VALUES(?,?,?,?)", (now, "fear_greed", float(d["value"]), d["value_classification"]))
        _status(con, "Fear&Greed", True, 1)
    except Exception as e:
        _status(con, "Fear&Greed", False, 0, e)
    try:
        js = getter(STABLES)
        tot = sum((a.get("circulating") or {}).get("peggedUSD") or 0 for a in js["peggedAssets"])
        con.execute("INSERT OR REPLACE INTO market_ctx VALUES(?,?,?,?)", (now, "stablecoin_supply_usd", float(tot), ""))
        _status(con, "DeFiLlama stablecoins", True, 1)
    except Exception as e:
        _status(con, "DeFiLlama stablecoins", False, 0, e)
    con.commit()


def pick_traders(rows, k=30):
    """'Consistently profitable' = positive PnL over week, month and all-time, with real size. Leaderboards look backward:
    past profit does not guarantee future profit (survivorship bias)."""
    out = []
    for r in rows:
        try:
            perf = {k2: v for k2, v in r["windowPerformances"]}
            av = float(r["accountValue"]); pw, pm, pa = (float(perf[x]["pnl"]) for x in ("week", "month", "allTime"))
            roi = float(perf["month"]["roi"])
        except Exception:
            continue
        if av >= 250_000 and pw > 0 and pm > 0 and pa > 0:
            out.append((pm, r["ethAddress"].lower(), av, pw, pm, pa, roi))
    out.sort(reverse=True)
    return [o[1:] for o in out[:k]]


def _post(url, payload, timeout=20):
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json", "User-Agent": UA})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())


def fetch_smart_money(con, board_getter=None, info_poster=None, k=30, now=None):
    """Daily: refresh the trader list from the public leaderboard. Hourly: read their public open positions
    (read-only info POSTs) and aggregate long/short notional per coin."""
    board_getter = board_getter or (lambda: get(HL_BOARD, timeout=90)["leaderboardRows"])
    info_poster = info_poster or _post
    now = now or time.time(); day = int(now // 86400) * 86400
    try:
        have = con.execute("SELECT COUNT(*) c FROM smart_traders WHERE ts>=?", (day,)).fetchone()["c"]
        if not have:
            for t in pick_traders(board_getter(), k):
                con.execute("INSERT OR REPLACE INTO smart_traders VALUES(?,?,?,?,?,?,?)", (day,) + tuple(t))
        addrs = [r["addr"] for r in con.execute("SELECT addr FROM smart_traders WHERE ts=?", (day,))]
        if not addrs:
            addrs = [r["addr"] for r in con.execute("SELECT addr FROM smart_traders WHERE ts=(SELECT MAX(ts) FROM smart_traders)")]
        agg = {}
        for a in addrs:
            try:
                st = info_poster(HL_INFO, {"type": "clearinghouseState", "user": a})
            except Exception:
                continue
            for p in st.get("assetPositions", []):
                pos = p.get("position", {}); coin = pos.get("coin")
                if coin not in config.COINS:
                    continue
                szi = float(pos.get("szi") or 0); usd = abs(float(pos.get("positionValue") or 0))
                d = agg.setdefault(coin, [0.0, 0.0, 0])
                d[0 if szi > 0 else 1] += usd; d[2] += 1
            time.sleep(0.15)
        for coin, (lo, sh, n) in agg.items():
            con.execute("INSERT OR REPLACE INTO smart_flow VALUES(?,?,?,?,?)", (now, coin, lo, sh, n))
        _status(con, "Hyperliquid smart money", True, len(agg), "%d traders" % len(addrs)); con.commit()
    except Exception as e:
        _status(con, "Hyperliquid smart money", False, 0, e)


def fetch(con):
    init(con)
    fetch_gov(con); fetch_ctx(con)
    fetch_gdelt(con)
    fetch_smart_money(con)
    return con.execute("SELECT COUNT(*) c FROM events").fetchone()["c"]
