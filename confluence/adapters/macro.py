"""Macro adapter: FRED CSV, ECB SDMX CSV, BoJ (via FRED mirror). Public, no keys, read-only.
fetch(con) -> int rows inserted/updated. Offline-testable via parse_* functions."""
import csv, io, time, urllib.request

FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}"
ECB = "https://data-api.ecb.europa.eu/service/data/{key}?format=csvdata&lastNObservations={n}"

# (source, series_name, remote id)
FRED_SERIES = [
    ("fred", "DGS10", "DGS10"), ("fred", "DGS2", "DGS2"), ("fred", "T10Y2Y", "T10Y2Y"),
    ("fred", "DFF", "DFF"), ("fred", "VIX", "VIXCLS"), ("fred", "DXY", "DTWEXBGS"),
    ("fred", "HY_OAS", "BAMLH0A0HYM2"), ("fred", "FED_ASSETS", "WALCL"),
    ("fred", "SPX", "SP500"), ("fred", "NASDAQ", "NASDAQCOM"),
    ("fred", "BTC", "CBBTCUSD"), ("fred", "ETH", "CBETHUSD"),
    ("boj", "BOJ_ASSETS", "JPNASSETS"), ("boj", "BOJ_RATE", "IRSTCB01JPM156N"),
]
ECB_SERIES = [
    ("ecb", "EURUSD", "EXR/D.USD.EUR.SP00.A"), ("ecb", "EURJPY", "EXR/D.JPY.EUR.SP00.A"),
    ("ecb", "ECB_DFR", "FM/B.U2.EUR.4F.KR.DFR.LEV"),
]
SCHEMA = """CREATE TABLE IF NOT EXISTS macro_obs(
 source TEXT, series TEXT, date TEXT, value REAL, fetched_at REAL,
 PRIMARY KEY(source, series, date))"""

def init(con):
    con.execute(SCHEMA); con.commit()

def parse_fred(text):
    out = []
    rows = csv.reader(io.StringIO(text)); next(rows, None)
    for r in rows:
        if len(r) < 2: continue
        try: out.append((r[0].strip(), float(r[1])))
        except ValueError: continue  # FRED uses "." for missing
    return out

def parse_ecb(text):
    out = []
    for r in csv.DictReader(io.StringIO(text)):
        try: out.append((r["TIME_PERIOD"], float(r["OBS_VALUE"])))
        except (KeyError, ValueError): continue
    return out

def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0", "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def store(con, source, series, obs):
    now = time.time()
    con.executemany("INSERT OR REPLACE INTO macro_obs VALUES(?,?,?,?,?)",
                    [(source, series, d, v, now) for d, v in obs])
    con.commit()
    return len(obs)

def fetch(con, getter=_get, history=900):
    init(con); n = 0
    for src, name, rid in FRED_SERIES:
        try: n += store(con, src, name, parse_fred(getter(FRED.format(id=rid)))[-history:])
        except Exception: continue
    for src, name, key in ECB_SERIES:
        try: n += store(con, src, name, parse_ecb(getter(ECB.format(key=key, n=history))))
        except Exception: continue
    return n
