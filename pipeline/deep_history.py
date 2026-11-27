"""Deep price history from Binance's public data dumps (data.binance.vision), free, no key, no account.

Monthly zips of 1h spot klines (SYMBOL-USDT) are stored compactly as history/<COIN>-1h.csv.gz
(ts,open,high,low,close,volume). Quote asset is USDT, not USD: tiny basis difference, labeled everywhere.
`update` is incremental: it only downloads full months that are missing, so hourly runs are cheap.
"""
import csv, gzip, io, os, time, zipfile, datetime, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from confluence import config

BASE = "https://data.binance.vision/data/spot/monthly/klines/%sUSDT/1h/%sUSDT-1h-%d-%02d.zip"
START = (2017, 8)
UA = "confluence-engine/0.2 (research; public data dumps)"


def _months(a, b):
    y, m = a
    while (y, m) <= b:
        yield y, m
        m += 1
        if m > 12:
            y, m = y + 1, 1


def _download(coin, y, m):
    url = BASE % (coin, coin, y, m)
    for attempt in range(3):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60).read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return []          # pair not listed yet that month
            time.sleep(1 + attempt)
        except Exception:
            time.sleep(1 + attempt)
    else:
        raise RuntimeError("download failed %s %d-%02d" % (coin, y, m))
    rows = []
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for line in z.read(z.namelist()[0]).decode().splitlines():
            p = line.split(",")
            try:
                t = int(p[0])
            except ValueError:
                continue
            if t > 10 ** 14:      # microseconds (Binance changed units in 2025)
                t //= 1000000
            else:
                t //= 1000
            rows.append((t, float(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[5])))
    return rows


def path(hist_dir, coin):
    return os.path.join(hist_dir, "%s-1h.csv.gz" % coin)


def load(hist_dir, coin):
    f = path(hist_dir, coin)
    if not os.path.exists(f):
        return []
    with gzip.open(f, "rt") as fh:
        return [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])) for r in csv.reader(fh)]


def _save(hist_dir, coin, rows):
    os.makedirs(hist_dir, exist_ok=True)
    rows = sorted({r[0]: r for r in rows}.values())
    buf = io.StringIO(); w = csv.writer(buf, lineterminator="\n")
    for r in rows:
        w.writerow((r[0],) + tuple(("%.8g" % v) for v in r[1:]))
    with gzip.GzipFile(path(hist_dir, coin), "wb", mtime=0) as g:    # mtime=0: identical bytes when data is unchanged
        g.write(buf.getvalue().encode())


def update(hist_dir, coins=None, now=None, budget_s=100, workers=6):
    now = now or time.time(); d = datetime.datetime.utcfromtimestamp(now)
    last_full = (d.year, d.month - 1) if d.month > 1 else (d.year - 1, 12)
    jobs = []; have = {}
    for c in coins or config.COINS:
        rows = load(hist_dir, c); have[c] = rows
        if rows:
            t = datetime.datetime.utcfromtimestamp(rows[-1][0]); first = (t.year, t.month)
            # last stored month is complete if its final bar is the month's last hour
            nxt = (t.year + (t.month == 12), 1 if t.month == 12 else t.month + 1)
            first = nxt
        else:
            first = START
        for ym in _months(first, last_full):
            jobs.append((c, ym))
    t0 = time.time(); added = {}; errs = 0

    def work(j):
        if time.time() - t0 > budget_s:
            return j, None
        try:
            return j, _download(j[0], *j[1])
        except Exception:
            return j, "err"
    with ThreadPoolExecutor(workers) as ex:
        for (c, ym), rows in ex.map(work, jobs):
            if rows == "err":
                errs += 1
            elif rows:
                have[c].extend(rows); added[c] = added.get(c, 0) + len(rows)
    for c in added:
        _save(hist_dir, c, have[c])
    return {"jobs": len(jobs), "coins_updated": len(added), "bars_added": sum(added.values()), "errors": errs}


def aggregate(rows, secs):
    """Aggregate 1h bars into `secs`-second bars aligned to UTC; only complete buckets."""
    out = []; cur = None; n = 0; per = secs // 3600
    for r in rows:
        b = r[0] // secs * secs
        if cur is None or cur[0] != b:
            if cur is not None and n == per:
                out.append(tuple(cur))
            cur = [b, r[1], r[2], r[3], r[4], r[5]]; n = 1
        else:
            cur[2] = max(cur[2], r[2]); cur[3] = min(cur[3], r[3]); cur[4] = r[4]; cur[5] += r[5]; n += 1
    if cur is not None and n == per:
        out.append(tuple(cur))
    return out


def series(hist_dir, coins=None):
    """{(coin, tf): bars} for 1h, 6h, 1d built from the stored hourly dumps."""
    out = {}
    for c in coins or config.COINS:
        h = load(hist_dir, c)
        if len(h) < 300:
            continue
        out[(c, "1h")] = h; out[(c, "6h")] = aggregate(h, 21600); out[(c, "1d")] = aggregate(h, 86400)
    return out
