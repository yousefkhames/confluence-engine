"""confluence/learning.py -- Workstream S1: self-learning loop v2.

Paper-only research and analytics for the Confluence Score engine.
Standard library only. No network, no orders, no credentials, no execution.

The loop has three jobs
-----------------------
1. **Dynamic weighting from outcomes.**  Re-estimate how much each confluence
   factor is actually worth from realized results (``signals`` joined to
   ``outcomes``), instead of trusting the hand-set defaults forever.
2. **Calibration.**  Turn the raw 0-100 Confluence Score into an observed hit
   rate, with Brier / log loss / ECE and reliability bins, so "score 78" means
   something checkable rather than a vibe.
3. **Walk-forward test.**  Time-ordered, embargoed out-of-fold evaluation of
   the whole loop against the current engine weights, so a proposed weight
   change has to earn its promotion on data it never saw.

Design rules baked into the code
--------------------------------
* **No look-ahead.**  Every fold fits weights *and* calibration on rows strictly
  older than the fold, minus an embargo, and calibration is fitted on *inner*
  out-of-fold predictions rather than in-sample ones.
* **Shrink, do not swing.**  New weights are blended toward the current engine
  weights with a strength that grows with the evidence (empirical Bayes), and
  are hard-bounded, so a handful of lucky calls cannot rewrite the model.
* **Direction-aware features.**  ``signals.factors`` are signed bullish/bearish
  (-1..+1) while ``signals.direction`` is LONG/SHORT, so a bearish factor on a
  SHORT is a *supporting* factor.  Features are aligned by side before fitting;
  fitting raw values would teach the loop that "news = -0.6" is bearish even
  when the engine correctly shorted it.
* **Self-reported results are unverified.**  Rows from ``trade_cases`` carry
  ``verified`` and ``confidence``; unverified rows get a smaller sample weight,
  every metric is reported for all-rows and verified-only, and survivorship bias
  is stated in the report rather than assumed away.  Losses are kept with their
  ``why_what`` / ``lesson`` text, because a loss without its why teaches nothing.
* **Read the core, never write it.**  This module never writes to ``signals``,
  ``outcomes``, ``prices``, ``explanations`` or any other core table.  It writes
  only to its own ``learning_*`` tables, and touches ``weights`` only through
  ``apply_weights()``, which is off unless the caller asks for it.

Entry point
-----------
    from confluence import db
    from confluence import learning
    con = db.connect()
    summary = learning.run(con)                  # dry run: report only
    summary = learning.run(con, promote=True)    # write weights if they earned it

Everything is also usable piecemeal: ``fit_weights``, ``fit_calibration``,
``walk_forward``, ``predict``, ``research_digest``.
"""

from __future__ import annotations

import argparse
import inspect
import json
import math
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

VERSION = "2.0.0"

# --- my tables -------------------------------------------------------------
CASES_TABLE = "learning_cases"
WEIGHTS_TABLE = "learning_weights"
CALIBRATION_TABLE = "learning_calibration"
RUNS_TABLE = "learning_runs"
PREDICTIONS_TABLE = "learning_predictions"

# --- core tables I only ever read -----------------------------------------
SIGNALS_TABLE = "signals"
OUTCOMES_TABLE = "outcomes"
CORE_WEIGHTS_TABLE = "weights"
SHARED_CASES_TABLE = "trade_cases"

DEFAULT_FACTORS = ("whale", "news", "sentiment")
DEFAULT_PRIOR_WEIGHTS = {"whale": 0.40, "news": 0.30, "sentiment": 0.30}
DEFAULT_HORIZONS = ("15m", "1h", "4h", "24h")
MANIP_FLAG = "MANIPULATION_WARNING"

EPS = 1e-6


# ---------------------------------------------------------------------------
# small utilities
# ---------------------------------------------------------------------------

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _q(name: str) -> str:
    """Quote a SQL identifier, refusing anything that is not a plain name."""
    if not name or not all(c.isalnum() or c == "_" for c in name):
        raise ValueError("unsafe SQL identifier: %r" % (name,))
    return '"%s"' % name


def _table_exists(con, name: str) -> bool:
    try:
        row = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?",
            (name,),
        ).fetchone()
        if row:
            return True
    except Exception:
        pass
    try:
        con.execute("SELECT 1 FROM %s WHERE 1=0" % _q(name))
        return True
    except Exception:
        return False


def _columns(con, name: str):
    """Column names of a table, or [] when it does not exist. Portable-ish."""
    try:
        rows = con.execute("PRAGMA table_info(%s)" % _q(name)).fetchall()
        if rows:
            return [r[1] for r in rows]
    except Exception:
        pass
    try:
        cur = con.execute("SELECT * FROM %s WHERE 1=0" % _q(name))
        return [d[0] for d in (cur.description or [])]
    except Exception:
        return []


def _pick(cols, *candidates):
    """First candidate present in cols (case-insensitive), else None."""
    low = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand.lower() in low:
            return low[cand.lower()]
    return None


_TS_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)


def parse_ts(value):
    """Best-effort timestamp -> aware UTC datetime (or None)."""
    if value is None or value == "":
        return None
    dt = None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, bool):
        return None
    elif isinstance(value, (int, float)):
        v = float(value)
        if v > 1e11:  # milliseconds
            v /= 1000.0
        try:
            return datetime.fromtimestamp(v, timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        s = str(value).strip()
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
        except ValueError:
            for fmt in _TS_FORMATS:
                try:
                    dt = datetime.strptime(s, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt) -> str:
    if dt is None:
        return ""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_float(value, default=None):
    if value is None or isinstance(value, bool):
        return default
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(f) or math.isinf(f):
        return default
    return f


def _as_bool(value):
    """Truthiness that survives TEXT/INTEGER/BOOL columns."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in ("1", "true", "yes", "y", "t", "verified")


def _json_obj(text):
    """Parse a JSON object out of a TEXT column; {} on anything else."""
    if text is None:
        return {}
    if isinstance(text, dict):
        return dict(text)
    try:
        val = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return dict(val) if isinstance(val, dict) else {}


def _json_list(text):
    if text is None:
        return []
    if isinstance(text, (list, tuple)):
        return list(text)
    try:
        val = json.loads(text)
    except (TypeError, ValueError):
        return []
    return list(val) if isinstance(val, (list, tuple)) else []


def _dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)


def _sign(x: float) -> float:
    return 1.0 if x > 0 else (-1.0 if x < 0 else 0.0)


def sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-min(x, 700.0))
        return 1.0 / (1.0 + z)
    z = math.exp(max(x, -700.0))
    return z / (1.0 + z)


def logit(p: float, eps: float = 1e-4) -> float:
    p = min(max(float(p), eps), 1.0 - eps)
    return math.log(p / (1.0 - p))


# ---------------------------------------------------------------------------
# outcomes
# ---------------------------------------------------------------------------

_WIN_TOKENS = {
    "win", "won", "w", "profitable", "profit", "tp", "target", "target_hit",
    "correct", "success", "successful", "up", "yes", "true", "hit", "good",
    "right", "worked",
}
_LOSS_TOKENS = {
    "loss", "lost", "lose", "l", "stop", "stopped", "stopped_out", "sl",
    "incorrect", "fail", "failed", "failure", "down", "no", "false", "miss",
    "wrong", "bad", "invalidated", "liq", "liquidated",
}
_FLAT_TOKENS = {
    "flat", "breakeven", "break_even", "be", "scratch", "even", "neutral",
    "unchanged", "no_trade", "expired", "timeout", "time_out",
}
_OPEN_TOKENS = {
    "open", "pending", "active", "running", "unresolved", "unknown", "", "none",
    "nan", "null",
}


def normalize_outcome(raw):
    """Map a free-text / numeric outcome to 'win' | 'loss' | 'flat' | 'open' | None.

    Numbers: 1 -> win, 0 -> loss (a binary label column), -1 -> loss.
    Anything unrecognised returns None so callers can count it as unusable
    rather than silently treating it as a win.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        return "win" if raw else "loss"
    if isinstance(raw, (int, float)):
        if isinstance(raw, float) and math.isnan(raw):
            return None
        if raw == 1:
            return "win"
        if raw == 0:
            return "loss"
        if raw == -1:
            return "loss"
        return None
    token = str(raw).strip().lower().replace("-", "_").replace(" ", "_")
    if token in _WIN_TOKENS:
        return "win"
    if token in _LOSS_TOKENS:
        return "loss"
    if token in _FLAT_TOKENS:
        return "flat"
    if token in _OPEN_TOKENS:
        return "open" if token else None
    return None


def label_of(outcome):
    """1.0 for a win, 0.0 for a loss, None for flat/open/unknown."""
    if outcome == "win":
        return 1.0
    if outcome == "loss":
        return 0.0
    return None


def label_from_prices(entry_price, exit_price, side):
    """Realized label from prices, used when ``outcome`` text is missing."""
    entry = _as_float(entry_price)
    exit_ = _as_float(exit_price)
    if not entry or not exit_ or entry <= 0:
        return None
    sign = 1.0 if str(side or "").strip().lower() in ("long", "buy", "l", "1") else -1.0
    ret = (exit_ - entry) / entry * sign
    if abs(ret) < 1e-9:
        return None
    return "win" if ret > 0 else "loss"


# ---------------------------------------------------------------------------
# schema (mine only)
# ---------------------------------------------------------------------------

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS learning_cases (
        case_id     TEXT PRIMARY KEY,
        source      TEXT NOT NULL,
        horizon     TEXT,
        ts          REAL,
        symbol      TEXT,
        market      TEXT,
        direction   TEXT,
        score       REAL,
        label       INTEGER,
        outcome     TEXT,
        verified    INTEGER DEFAULT 0,
        confidence  REAL,
        source_url  TEXT,
        why_what    TEXT,
        how         TEXT,
        where_ctx   TEXT,
        lesson      TEXT,
        features    TEXT,
        collected_at REAL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_learning_cases_ts ON learning_cases(ts)",
    """
    CREATE TABLE IF NOT EXISTS learning_weights (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at  REAL NOT NULL,
        market      TEXT,
        horizon     TEXT,
        method      TEXT,
        n_cases     INTEGER,
        n_events    REAL,
        payload     TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS learning_calibration (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at  REAL NOT NULL,
        market      TEXT,
        horizon     TEXT,
        kind        TEXT,
        method      TEXT,
        n_cases     INTEGER,
        payload     TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS learning_runs (
        run_id      TEXT PRIMARY KEY,
        created_at  REAL NOT NULL,
        kind        TEXT NOT NULL,
        market      TEXT,
        horizon     TEXT,
        payload     TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS learning_predictions (
        run_id      TEXT NOT NULL,
        case_id     TEXT NOT NULL,
        fold        INTEGER,
        ts          REAL,
        p_raw       REAL,
        p_cal       REAL,
        p_base      REAL,
        y           INTEGER,
        PRIMARY KEY (run_id, case_id)
    )
    """,
)


def ensure_schema(con) -> None:
    """Create my tables if they are missing. Safe to call on every run."""
    for stmt in _SCHEMA:
        con.execute(stmt)
    try:
        con.commit()
    except Exception:
        pass


def init(con) -> None:
    """Alias kept for the integrator's loader convention."""
    ensure_schema(con)


# ---------------------------------------------------------------------------
# sources: core signals/outcomes, and the shared research table
# ---------------------------------------------------------------------------

def load_core_weights(con):
    """Current engine weights: signals.load_weights() if importable, else the
    ``weights`` table, else the documented defaults. Never raises."""
    try:
        mod = _signals_module()
        if mod is not None and hasattr(mod, "load_weights"):
            got = mod.load_weights(con)
            if isinstance(got, dict) and got:
                return {str(k): float(v) for k, v in got.items()}
    except Exception:
        pass
    weights = dict(DEFAULT_PRIOR_WEIGHTS)
    if _table_exists(con, CORE_WEIGHTS_TABLE):
        try:
            rows = con.execute(
                "SELECT k, v FROM %s" % _q(CORE_WEIGHTS_TABLE)
            ).fetchall()
            found = {str(r[0]): _as_float(r[1]) for r in rows if _as_float(r[1]) is not None}
            found = {k: v for k, v in found.items() if v is not None}
            if found:
                weights = found
        except Exception:
            pass
    total = sum(abs(v) for v in weights.values()) or 1.0
    return {k: v / total for k, v in weights.items()}


def _signals_module():
    """Import the core signals module from either package layout, or None."""
    for name in ("confluence.signals", "signals"):
        try:
            mod = __import__(name, fromlist=["*"])
        except Exception:
            continue
        if mod is not None:
            return mod
    return None


def _flag_list(flags):
    out = []
    for item in _json_list(flags):
        if isinstance(item, dict):
            for key in ("flag", "name", "code", "text"):
                if key in item:
                    out.append(str(item[key]))
                    break
        else:
            out.append(str(item))
    return out


def load_signals(con, horizon="1h", *, since=None, until=None, symbols=None,
                 extras=("manip",), use_score=False):
    """Scored core signals joined to their realized outcome.

    Returns a list of case dicts. ``factors`` are the engine's signed factors
    already multiplied by the trade side (+1 LONG, -1 SHORT) so that a positive
    value always means "this factor supported the call that was made".
    ``label`` is 1 for a win, 0 for a loss, None when unresolved.
    """
    if not (_table_exists(con, SIGNALS_TABLE) and _table_exists(con, OUTCOMES_TABLE)):
        return []
    scols = _columns(con, SIGNALS_TABLE)
    ocols = _columns(con, OUTCOMES_TABLE)
    if not scols or not ocols:
        return []

    sid = _pick(scols, "id", "signal_id")
    sts = _pick(scols, "ts", "created_at", "created_ts", "entry_ts")
    ssym = _pick(scols, "symbol", "instrument", "market")
    sdir = _pick(scols, "direction", "side")
    sscore = _pick(scols, "score", "confluence_score")
    sfac = _pick(scols, "factors", "components", "contributions")
    sflags = _pick(scols, "flags")
    sedge = _pick(scols, "net_edge_pct", "net_edge")
    if sid is None or sts is None or sfac is None:
        return []

    osid = _pick(ocols, "signal_id", "case_id", "id")
    ohor = _pick(ocols, "horizon", "timeframe")
    oret = _pick(ocols, "ret_pct", "ret", "return_pct")
    ohit = _pick(ocols, "hit", "label", "outcome")
    if osid is None:
        return []

    select = [
        "s.%s AS signal_id" % _q(sid),
        "s.%s AS ts" % _q(sts),
        ("s.%s" % _q(ssym)) if ssym else "NULL",
        ("s.%s" % _q(sdir)) if sdir else "NULL",
        ("s.%s" % _q(sscore)) if sscore else "NULL",
        ("s.%s" % _q(sfac)) if sfac else "NULL",
        ("s.%s" % _q(sflags)) if sflags else "NULL",
        ("s.%s" % _q(sedge)) if sedge else "NULL",
        ("o.%s" % _q(oret)) if oret else "NULL",
        ("o.%s" % _q(ohit)) if ohit else "NULL",
        ("o.%s" % _q(ohor)) if ohor else "NULL",
    ]
    sql = (
        "SELECT %s FROM %s s JOIN %s o ON o.%s = s.%s"
        % (", ".join(select), _q(SIGNALS_TABLE), _q(OUTCOMES_TABLE), _q(osid), _q(sid))
    )
    where, params = [], []
    if ohor is not None and horizon not in (None, "all"):
        where.append("o.%s = ?" % _q(ohor))
        params.append(horizon)
    if since is not None:
        where.append("s.%s >= ?" % _q(sts))
        params.append(float(since))
    if until is not None:
        where.append("s.%s < ?" % _q(sts))
        params.append(float(until))
    if symbols and ssym is not None:
        where.append("s.%s IN (%s)" % (_q(ssym), ",".join("?" * len(symbols))))
        params.extend(list(symbols))
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY s.%s" % _q(sts)

    try:
        rows = con.execute(sql, params).fetchall()
    except Exception:
        return []

    cases = []
    for row in rows:
        (signal_id, ts_raw, symbol, direction, score, factors, flags,
         net_edge, ret_pct, hit_raw, hor) = row
        ts = parse_ts(ts_raw)
        dir_txt = (str(direction).strip().upper() if direction is not None else "")
        dir_sign = -1.0 if dir_txt.startswith("S") else 1.0
        raw_factors = {}
        for name, value in _json_obj(factors).items():
            f = _as_float(value)
            if f is not None:
                raw_factors[str(name)] = f
        feats = {name: f * dir_sign for name, f in raw_factors.items()}
        flag_list = _flag_list(flags)
        if "manip" in extras:
            feats["manip"] = -1.0 if MANIP_FLAG in flag_list else 0.0
        if "net_edge" in extras:
            edge = _as_float(net_edge)
            feats["net_edge"] = (edge / 100.0) if edge is not None else 0.0
        if use_score or "score" in extras:
            sc = _as_float(score)
            feats["score_centered"] = ((sc - 50.0) / 50.0) if sc is not None else 0.0

        ret = _as_float(ret_pct)
        dir_ret = ret * dir_sign if ret is not None else None
        label = None
        hit_val = _as_float(hit_raw)
        if hit_val is not None and hit_val in (0.0, 1.0):
            label = int(hit_val)
        elif isinstance(hit_raw, str):
            norm = normalize_outcome(hit_raw)
            if norm == "win":
                label = 1
            elif norm == "loss":
                label = 0
        if label is None and dir_ret is not None and abs(dir_ret) > 1e-12:
            label = 1 if dir_ret > 0 else 0

        cases.append({
            "case_id": "sig:%s:%s" % (signal_id, hor or horizon or "-"),
            "signal_id": signal_id,
            "source": "signals",
            "horizon": hor if hor is not None else horizon,
            "ts": ts,
            "ts_epoch": ts.timestamp() if ts else None,
            "symbol": symbol,
            "market": symbol,
            "direction": dir_txt or None,
            "dir_sign": dir_sign,
            "score": _as_float(score),
            "net_edge_pct": _as_float(net_edge),
            "flags": flag_list,
            "factors": feats,
            "raw_factors": raw_factors,
            "ret_pct": ret,
            "dir_ret": dir_ret,
            "hit_raw": hit_raw,
            "label": label,
        })
    return cases


def load_research_cases(con):
    """Rows from the shared ``trade_cases`` table, normalized.

    These carry no factor values, so they are not used to fit factor weights;
    they are the survivorship-bias and "why did it lose" corpus.
    """
    if not _table_exists(con, SHARED_CASES_TABLE):
        return []
    cols = _columns(con, SHARED_CASES_TABLE)
    if not cols:
        return []
    c_id = _pick(cols, "id", "case_id")
    c_ts = _pick(cols, "entry_ts", "collected_at", "ts")
    c_market = _pick(cols, "market", "symbol")
    c_inst = _pick(cols, "instrument")
    c_side = _pick(cols, "side", "direction")
    c_out = _pick(cols, "outcome", "result")
    c_ver = _pick(cols, "verified")
    c_conf = _pick(cols, "confidence")
    c_url = _pick(cols, "source_url")
    c_why = _pick(cols, "why_what", "why")
    c_how = _pick(cols, "how")
    c_where = _pick(cols, "where_ctx", "where")
    c_lesson = _pick(cols, "lesson")
    c_entry = _pick(cols, "entry_price")
    c_exit = _pick(cols, "exit_price")
    c_pnl = _pick(cols, "pnl_note")

    select = ["%s" % (_q(c_id) if c_id else "rowid")]
    for c in (c_ts, c_market, c_inst, c_side, c_out, c_ver, c_conf, c_url,
              c_why, c_how, c_where, c_lesson, c_entry, c_exit, c_pnl):
        select.append(_q(c) if c else "NULL")
    try:
        rows = con.execute("SELECT %s FROM %s" % (", ".join(select), _q(SHARED_CASES_TABLE))).fetchall()
    except Exception:
        return []

    cases = []
    for row in rows:
        (case_id, ts_raw, market, instrument, side, outcome, verified, confidence,
         url, why, how, where_ctx, lesson, entry, exit_, pnl) = row
        norm = normalize_outcome(outcome)
        if norm is None and pnl:
            norm = normalize_outcome(pnl)
        if norm is None:
            norm = label_from_prices(entry, exit_, side)
        ts = parse_ts(ts_raw)
        cases.append({
            "case_id": str(case_id) if case_id is not None else "tc:%d" % len(cases),
            "source": "research",
            "horizon": None,
            "ts": ts,
            "ts_epoch": ts.timestamp() if ts else None,
            "symbol": instrument or market,
            "market": market,
            "direction": (str(side).strip().upper() if side is not None else None),
            "outcome": norm or "open",
            "label": label_of(norm),
            "verified": 1 if _as_bool(verified) else 0,
            "confidence": _as_float(confidence),
            "source_url": url,
            "why_what": why,
            "how": how,
            "where_ctx": where_ctx,
            "lesson": lesson,
            "factors": {},
            "pnl_note": pnl,
        })
    return cases


def sync_cases(con) -> int:
    """Materialize ``trade_cases`` into ``learning_cases``. Returns rows written."""
    ensure_schema(con)
    cases = load_research_cases(con)
    now = utcnow().timestamp()
    written = 0
    for c in cases:
        con.execute(
            """INSERT INTO learning_cases
               (case_id, source, horizon, ts, symbol, market, direction, score,
                label, outcome, verified, confidence, source_url, why_what, how,
                where_ctx, lesson, features, collected_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(case_id) DO UPDATE SET
                 source=excluded.source, horizon=excluded.horizon, ts=excluded.ts,
                 symbol=excluded.symbol, market=excluded.market,
                 direction=excluded.direction, score=excluded.score,
                 label=excluded.label, outcome=excluded.outcome,
                 verified=excluded.verified, confidence=excluded.confidence,
                 source_url=excluded.source_url, why_what=excluded.why_what,
                 how=excluded.how, where_ctx=excluded.where_ctx,
                 lesson=excluded.lesson, features=excluded.features,
                 collected_at=excluded.collected_at""",
            (
                c["case_id"], c["source"], c["horizon"], c["ts_epoch"], c["symbol"],
                c["market"], c["direction"], None, c["label"], c["outcome"],
                c["verified"], c["confidence"], c["source_url"], c["why_what"],
                c["how"], c["where_ctx"], c["lesson"],
                _dumps(c["factors"] or {}), now,
            ),
        )
        written += 1
    try:
        con.commit()
    except Exception:
        pass
    return written


def ingest_trade_cases(con, rows, *, replace=False) -> int:
    """Upsert research rows into the shared ``trade_cases`` table.

    Only columns that exist in the live table are written, so the integrator's
    DDL always wins. ``replace`` deletes the given ids first (re-ingest path).
    """
    ensure_schema(con)
    rows = [dict(r) for r in rows or []]
    if not rows:
        return 0
    if not _table_exists(con, SHARED_CASES_TABLE):
        con.execute(
            """CREATE TABLE IF NOT EXISTS trade_cases (
                   id TEXT PRIMARY KEY, collected_at REAL, source_type TEXT,
                   source_url TEXT, market TEXT, instrument TEXT, side TEXT,
                   entry_ts REAL, entry_price REAL, exit_price REAL,
                   size_note TEXT, outcome TEXT, pnl_note TEXT, why_what TEXT,
                   how TEXT, where_ctx TEXT, lesson TEXT,
                   verified INTEGER DEFAULT 0, confidence REAL, tags TEXT)"""
        )
    cols = _columns(con, SHARED_CASES_TABLE)
    if not cols:
        return 0
    known = set(cols)
    now = utcnow().timestamp()
    written = 0
    for i, row in enumerate(rows):
        payload = {k: v for k, v in row.items() if k in known}
        if "collected_at" in known and not payload.get("collected_at"):
            payload["collected_at"] = now
        if "id" in known and not payload.get("id"):
            payload["id"] = "tc-%d-%s" % (int(now), i)
        if "verified" in known:
            payload["verified"] = 1 if _as_bool(payload.get("verified")) else 0
        if not payload:
            continue
        if replace and payload.get("id") is not None:
            con.execute("DELETE FROM %s WHERE id = ?" % _q(SHARED_CASES_TABLE), (payload["id"],))
        keys = sorted(payload)
        sql = "INSERT OR REPLACE INTO %s (%s) VALUES (%s)" % (
            _q(SHARED_CASES_TABLE),
            ", ".join(_q(k) for k in keys),
            ", ".join("?" for _ in keys),
        )
        con.execute(sql, [payload[k] for k in keys])
        written += 1
    try:
        con.commit()
    except Exception:
        pass
    return written


def load_cases(con, source="auto", *, horizon="1h", since=None, until=None,
               symbols=None, extras=("manip",), use_score=False):
    """Cases for fitting. 'signals' needs factor values; 'research' does not."""
    if source in ("auto", "signals"):
        cases = load_signals(con, horizon, since=since, until=until, symbols=symbols,
                             extras=extras, use_score=use_score)
        if cases or source == "signals":
            return cases
    if source in ("auto", "research", "trade_cases"):
        return load_research_cases(con)
    return []


# ---------------------------------------------------------------------------
# design matrix and the logistic fit behind the weights
# ---------------------------------------------------------------------------

def feature_names(cases):
    """Every factor key seen in the corpus, sorted for reproducibility."""
    names = set()
    for c in cases:
        names.update((c.get("factors") or {}).keys())
    return sorted(names)


def _column_stats(cases, names):
    """center/scale per feature from the values actually present."""
    center, scale, coverage = {}, {}, {}
    n = len(cases)
    for name in names:
        vals = [c["factors"][name] for c in cases
                if c.get("factors") and c["factors"].get(name) is not None]
        coverage[name] = len(vals)
        if not vals:
            center[name], scale[name] = 0.0, 1.0
            continue
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / max(len(vals) - 1, 1)
        sd = math.sqrt(var)
        center[name] = mean
        scale[name] = sd if sd > 1e-9 else 1.0
    return center, scale, coverage


def sample_weights(cases, *, as_of=None, half_life_days=90.0, unverified_weight=0.35):
    """Per-case weight: stated confidence x verification x recency.

    Unverified rows are discounted rather than dropped, so a small verified
    corpus still contributes; the report always shows verified-only metrics too.
    The recency decay is normalized to a mean of 1: it re-weights the corpus
    toward recent rows without also shrinking the effective sample size, which
    would make the loop unable to learn from a long history.
    """
    if not cases:
        return []
    if as_of is None:
        stamps = [c["ts"] for c in cases if c.get("ts")]
        as_of = max(stamps) if stamps else utcnow()
    bases, decays = [], []
    for c in cases:
        base = _as_float(c.get("confidence"), 1.0)
        base = 1.0 if base is None else min(max(base, 0.05), 1.0)
        if c.get("source") == "research" and not c.get("verified"):
            base *= unverified_weight
        ts = c.get("ts")
        decay = 1.0
        if half_life_days and half_life_days > 0 and ts is not None:
            age_days = max((as_of - ts).total_seconds() / 86400.0, 0.0)
            decay = 0.5 ** (age_days / float(half_life_days))
        bases.append(base)
        decays.append(decay)
    mean_decay = sum(decays) / len(decays) or 1.0
    return [max(b * (d / mean_decay), 1e-3) for b, d in zip(bases, decays)]


def build_design(cases, names, center, scale):
    """X rows (standardized, missing -> 0 i.e. the mean), y, and usable index."""
    X, y, idx = [], [], []
    for i, c in enumerate(cases):
        label = c.get("label")
        if label is None:
            continue
        row = []
        for name in names:
            val = (c.get("factors") or {}).get(name)
            row.append(0.0 if val is None else (val - center[name]) / scale[name])
        X.append(row)
        y.append(float(label))
        idx.append(i)
    return X, y, idx


def _solve(A, b):
    """Gaussian elimination with partial pivoting. Raises on a singular system."""
    n = len(b)
    M = [list(A[i]) + [b[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[pivot][col]) < 1e-12:
            raise ValueError("singular matrix")
        if pivot != col:
            M[col], M[pivot] = M[pivot], M[col]
        pv = M[col][col]
        for r in range(col + 1, n):
            factor = M[r][col] / pv
            if factor == 0.0:
                continue
            for c2 in range(col, n + 1):
                M[r][c2] -= factor * M[col][c2]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        acc = M[r][n] - sum(M[r][c] * x[c] for c in range(r + 1, n))
        x[r] = acc / M[r][r]
    return x


def fit_logistic(X, y, sw, *, l2=1.0, iters=60, tol=1e-9):
    """Ridge-penalized logistic regression by IRLS. Pure stdlib.

    Returns {'intercept', 'coef', 'iters', 'converged'}. The intercept is not
    penalized; the ridge keeps separable data and collinear factors finite.
    """
    if not X or not X[0]:
        raise ValueError("empty design matrix")
    k = len(X[0])
    beta = [0.0] * (k + 1)
    converged = False
    used = 0
    for it in range(iters):
        used = it + 1
        A = [[0.0] * (k + 1) for _ in range(k + 1)]
        g = [0.0] * (k + 1)
        for xi, yi, wi in zip(X, y, sw):
            eta = beta[0] + sum(beta[j + 1] * xi[j] for j in range(k))
            p = sigmoid(eta)
            p = min(max(p, EPS), 1.0 - EPS)
            w = wi * p * (1.0 - p)
            if w <= 0.0:
                continue
            z = eta + (yi - p) / (p * (1.0 - p))
            xr = [1.0] + xi
            for a in range(k + 1):
                wa = w * xr[a]
                if wa == 0.0:
                    continue
                g[a] += wa * z
                for c2 in range(a, k + 1):
                    A[a][c2] += wa * xr[c2]
        for a in range(k + 1):
            for c2 in range(a):
                A[a][c2] = A[c2][a]
        for j in range(1, k + 1):
            A[j][j] += l2
        A[0][0] += 1e-9
        new = _solve(A, g)
        delta = max(abs(new[i] - beta[i]) for i in range(k + 1))
        beta = new
        if delta < tol:
            converged = True
            break
    return {"intercept": beta[0], "coef": beta[1:], "iters": used,
            "converged": converged}


def _normalize(mapping):
    total = sum(abs(v) for v in mapping.values())
    if total <= 0:
        return {k: 0.0 for k in mapping}
    return {k: v / total for k, v in mapping.items()}


def _prior_importance(prior, core_names):
    base = {name: abs(float(prior.get(name, 0.0))) for name in core_names}
    if sum(base.values()) <= 0:
        base = {name: 1.0 for name in core_names}
    return _normalize(base)


def fit_weights(con, horizon="1h", *, market=None, source="auto", since=None,
                symbols=None, half_life_days=90.0, l2=1.0, prior=None,
                prior_strength=150.0, min_events=25, max_abs_coef=3.0,
                unverified_weight=0.35, extras=("manip",), use_score=False,
                as_of=None, cases=None):
    """Re-estimate factor weights from realized outcomes.

    Returns a payload dict (also what ``save_weights`` stores)::

        method      'logistic' | 'univariate' | 'prior'
        coef        log-odds per one SD of each standardized feature
        center/scale  the standardization, so predict() reproduces it exactly
        weights     signed importance, sum(|w|) == 1 over the core factors
        weights_nonneg  same, negatives clipped and renormalized (engine-safe)
        alpha       per-factor trust in the fit, n/(n+prior_strength)
        diagnostics coverage, events, convergence, corpus description
    """
    as_of_dt = parse_ts(as_of) or utcnow()
    if cases is None:
        cases = load_cases(con, source, horizon=horizon, since=since,
                           symbols=symbols, extras=extras, use_score=use_score)
    else:
        cases = list(cases)
    if market:
        cases = [c for c in cases
                 if str(c.get("market") or "").lower() == str(market).lower()
                 or str(c.get("symbol") or "").lower() == str(market).lower()]
    closed = [c for c in cases if c.get("label") is not None and c.get("ts") is not None]
    core_prior = dict(prior or load_core_weights(con))
    names = feature_names(closed)
    core_names = [n for n in names if n in core_prior] or list(core_prior)

    base_payload = {
        "version": VERSION,
        "created_at": iso(as_of_dt),
        "horizon": horizon,
        "market": market,
        "source": source,
        "method": "prior",
        "coef": {},
        "center": {},
        "scale": {},
        "intercept": 0.0,
        "weights": _normalize({n: float(core_prior.get(n, 0.0)) for n in core_names}),
        "weights_nonneg": _normalize(
            {n: max(float(core_prior.get(n, 0.0)), 0.0) for n in core_names}),
        "alpha": {n: 0.0 for n in core_names},
        "prior": core_prior,
        "n_cases": len(cases),
        "n_events": 0,
        "diagnostics": {"reason": "no closed cases with factors"},
    }
    if not closed or not names:
        return base_payload

    center, scale, coverage = _column_stats(closed, names)
    sw_all = sample_weights(closed, as_of=as_of_dt, half_life_days=half_life_days,
                            unverified_weight=unverified_weight)
    X, y, idx = build_design(closed, names, center, scale)
    if len(y) < max(min_events, 5) or len(set(y)) < 2:
        base_payload["n_events"] = len(y)
        base_payload["diagnostics"] = {
            "reason": "not enough events or only one class",
            "n_events": len(y),
            "min_events": min_events,
            "coverage": coverage,
        }
        return base_payload
    sw = [sw_all[i] for i in idx]
    if sum(sw) <= 0:
        base_payload["diagnostics"] = {"reason": "all sample weights are zero"}
        return base_payload

    method = "logistic"
    coefs, intercept = None, 0.0
    fit = {}
    fit_error = None
    try:
        fit = fit_logistic(X, y, sw, l2=l2)
        coefs, intercept = fit["coef"], fit["intercept"]
        if not all(math.isfinite(v) for v in coefs):
            raise ValueError("non-finite coefficients")
    except Exception as exc:  # singular / degenerate: fall back to one factor at a time
        method = "univariate"
        fit_error = str(exc)
        coefs, intercept = [], 0.0
        for j in range(len(names)):
            try:
                one = fit_logistic([[row[j]] for row in X], y, sw, l2=l2)
                coefs.append(one["coef"][0])
            except Exception:
                coefs.append(0.0)

    coefs = [max(min(c, max_abs_coef), -max_abs_coef) for c in coefs]
    coef_map = dict(zip(names, coefs))

    weighted_n = {}
    for name in names:
        weighted_n[name] = sum(
            sw_all[i] for i in idx if (closed[i].get("factors") or {}).get(name) is not None
        )

    alpha = {}
    blended = {}
    prior_imp = _prior_importance(core_prior, core_names)
    fitted_imp = {n: abs(coef_map.get(n, 0.0)) for n in core_names}
    fitted_imp = _normalize(fitted_imp)
    for name in core_names:
        a = weighted_n.get(name, 0.0) / (weighted_n.get(name, 0.0) + float(prior_strength))
        alpha[name] = a
        blended[name] = (1.0 - a) * prior_imp.get(name, 0.0) + a * fitted_imp.get(name, 0.0)
    signed = {}
    for name in core_names:
        sign = _sign(coef_map.get(name, 0.0))
        signed[name] = sign * blended[name] if sign else 0.0
    weights = _normalize(signed) if any(abs(v) > 0 for v in signed.values()) else \
        _normalize(prior_imp)
    nonneg = _normalize({n: max(v, 0.0) for n, v in weights.items()})
    if sum(nonneg.values()) <= 0:
        nonneg = _normalize({n: max(prior_imp.get(n, 0.0), 0.0) for n in core_names})

    extras_coef = {n: coef_map[n] for n in names if n not in core_names}
    payload = {
        "version": VERSION,
        "created_at": iso(as_of_dt),
        "horizon": horizon,
        "market": market,
        "source": source,
        "method": method,
        "coef": {n: coef_map[n] for n in names},
        "extras_coef": extras_coef,
        "center": center,
        "scale": scale,
        "intercept": intercept,
        "weights": weights,
        "weights_nonneg": nonneg,
        "alpha": alpha,
        "prior": core_prior,
        "n_cases": len(cases),
        "n_events": len(y),
        "weighted_events": sum(sw),
        "positives": int(sum(y)),
        "diagnostics": {
            "coverage": coverage,
            "weighted_coverage": {k: round(v, 3) for k, v in weighted_n.items()},
            "multivariate_error": fit_error,
            "fit": {"l2": l2, "iters": fit.get("iters") if method == "logistic" else None,
                    "converged": fit.get("converged") if method == "logistic" else None},
            "half_life_days": half_life_days,
            "prior_strength": prior_strength,
            "unverified_weight": unverified_weight,
            "extras": list(extras),
            "n_symbols": len({c.get("symbol") for c in closed if c.get("symbol")}),
            "ts_range": [iso(min(c["ts"] for c in closed)), iso(max(c["ts"] for c in closed))],
        },
    }
    return payload


# ---------------------------------------------------------------------------
# weight artifacts
# ---------------------------------------------------------------------------

def save_weights(con, payload) -> int:
    ensure_schema(con)
    con.execute(
        "INSERT INTO %s (created_at, market, horizon, method, n_cases, n_events, payload)"
        " VALUES (?,?,?,?,?,?,?)" % _q(WEIGHTS_TABLE),
        (utcnow().timestamp(), payload.get("market"), payload.get("horizon"),
         payload.get("method"), payload.get("n_cases"), payload.get("n_events"),
         _dumps(payload)),
    )
    try:
        con.commit()
    except Exception:
        pass
    return 1


def load_weights(con, horizon=None, market=None):
    """Most recent stored weight payload matching the filters, or None."""
    if not _table_exists(con, WEIGHTS_TABLE):
        return None
    sql = "SELECT payload FROM %s" % _q(WEIGHTS_TABLE)
    where, params = [], []
    if horizon is not None:
        where.append("horizon = ?")
        params.append(horizon)
    if market is not None:
        where.append("(market = ? OR market IS NULL)")
        params.append(market)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT 1"
    try:
        row = con.execute(sql, params).fetchone()
    except Exception:
        return None
    if not row:
        return None
    try:
        return json.loads(row[0])
    except (TypeError, ValueError):
        return None


def weight_drift(previous, current):
    """L1 and max change between two weight dicts, for a sanity check."""
    if not previous or not current:
        return None
    keys = set(previous) | set(current)
    diffs = {k: float(current.get(k, 0.0)) - float(previous.get(k, 0.0)) for k in keys}
    return {
        "l1": sum(abs(v) for v in diffs.values()),
        "max": max((abs(v) for v in diffs.values()), default=0.0),
        "by_key": diffs,
    }


def _writer(con):
    """The core's weight-writing function, if it exposes one. Never guessed."""
    mod = _signals_module()
    if mod is None:
        return None
    for name in ("save_weights", "set_weights", "write_weights", "update_weights"):
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn
    return None


def apply_weights(con, mapping, *, horizon="1h", dry_run=False):
    """Write proposed weights through the core's own writer.

    This module never UPDATEs the core ``weights`` table directly; if the core
    does not expose a writer, this returns {'applied': False, 'reason': ...} and
    the integrator decides how to land the numbers.
    """
    ensure_schema(con)
    current = load_core_weights(con)
    mapping = {k: float(v) for k, v in (mapping or {}).items() if k in current or not current}
    result = {"applied": False, "proposed": mapping, "current": current,
              "drift": weight_drift(current, mapping), "horizon": horizon}
    if not mapping:
        result["reason"] = "nothing to apply"
        return result
    if dry_run:
        result["reason"] = "dry_run"
        return result
    fn = _writer(con)
    if fn is None:
        result["reason"] = "core exposes no weight writer (save_weights/set_weights)"
        return result
    try:
        fn(con, mapping)
    except TypeError:
        try:
            fn(con, **mapping)
        except Exception as exc:
            result["reason"] = "writer call failed: %s" % exc
            return result
    except Exception as exc:
        result["reason"] = "writer call failed: %s" % exc
        return result
    result["applied"] = True
    result["reason"] = "written via %s" % getattr(fn, "__name__", "core writer")
    return result


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

def _clean_pairs(pairs):
    out = []
    for p, y in pairs:
        pf = _as_float(p)
        yf = _as_float(y)
        if pf is None or yf is None:
            continue
        out.append((min(max(pf, EPS), 1.0 - EPS), 1.0 if yf >= 0.5 else 0.0))
    return out


def brier(pairs):
    ps = _clean_pairs(pairs)
    if not ps:
        return None
    return sum((p - y) ** 2 for p, y in ps) / len(ps)


def log_loss(pairs, eps=EPS):
    ps = _clean_pairs(pairs)
    if not ps:
        return None
    total = 0.0
    for p, y in ps:
        p = min(max(p, eps), 1.0 - eps)
        total -= y * math.log(p) + (1.0 - y) * math.log(1.0 - p)
    return total / len(ps)


def accuracy(pairs, thr=0.5):
    ps = _clean_pairs(pairs)
    if not ps:
        return None
    hits = sum(1 for p, y in ps if (p >= thr) == (y >= 0.5))
    return hits / len(ps)


def _rankdata(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def auc(pairs):
    """Rank quality of the predictions, independent of calibration."""
    ps = _clean_pairs(pairs)
    pos = [p for p, y in ps if y >= 0.5]
    neg = [p for p, y in ps if y < 0.5]
    if not pos or not neg:
        return None
    ranks = _rankdata([p for p, _ in ps])
    pos_rank = sum(r for r, (_, y) in zip(ranks, ps) if y >= 0.5)
    u = pos_rank - len(pos) * (len(pos) + 1) / 2.0
    return u / (len(pos) * len(neg))


def reliability(pairs, bins=10):
    """Predicted vs observed hit rate per equal-width probability bin."""
    ps = _clean_pairs(pairs)
    if not ps:
        return []
    buckets = [[] for _ in range(bins)]
    for p, y in ps:
        i = min(int(p * bins), bins - 1)
        buckets[i].append((p, y))
    out = []
    for i, bucket in enumerate(buckets):
        if not bucket:
            continue
        out.append({
            "lo": i / bins,
            "hi": (i + 1) / bins,
            "n": len(bucket),
            "pred": sum(p for p, _ in bucket) / len(bucket),
            "obs": sum(y for _, y in bucket) / len(bucket),
            "gap": sum(y for _, y in bucket) / len(bucket) - sum(p for p, _ in bucket) / len(bucket),
        })
    return out


def ece(pairs, bins=10):
    ps = _clean_pairs(pairs)
    if not ps:
        return None
    return sum(b["n"] / len(ps) * abs(b["gap"]) for b in reliability(ps, bins))


def summarize(pairs, bins=10):
    """One dict of every headline number, safe on small samples."""
    ps = _clean_pairs(pairs)
    return {
        "n": len(ps),
        "positives": int(sum(y for _, y in ps)),
        "base_rate": (sum(y for _, y in ps) / len(ps)) if ps else None,
        "brier": brier(ps),
        "log_loss": log_loss(ps),
        "accuracy": accuracy(ps),
        "auc": auc(ps),
        "ece": ece(ps, bins),
        "reliability": reliability(ps, bins),
    }


# ---------------------------------------------------------------------------
# calibration: raw score -> observed hit rate
# ---------------------------------------------------------------------------

def fit_isotonic(pairs, min_block=1.0):
    """Pool-adjacent-violators isotonic regression. Returns [[x, y], ...] knots.

    Monotone by construction, so a higher score can never map to a lower hit
    rate; ties in x are averaged first so duplicate scores do not fight.
    """
    ps = _clean_pairs(pairs)
    if not ps:
        return []
    agg = {}
    for p, y in ps:
        key = round(p, 6)
        w, s = agg.get(key, (0.0, 0.0))
        agg[key] = (w + 1.0, s + y)
    xs = sorted(agg)
    blocks = []  # [weight, sum_y, first_x, last_x]
    for x in xs:
        w, s = agg[x]
        blocks.append([w, s, x, x])
        while len(blocks) > 1:
            prev, cur = blocks[-2], blocks[-1]
            if prev[1] / prev[0] <= cur[1] / cur[0] + 1e-15:
                break
            blocks.pop()
            prev[0] += cur[0]
            prev[1] += cur[1]
            prev[3] = cur[3]
    knots = []
    for w, s, first_x, last_x in blocks:
        if w < min_block:
            continue
        knots.append([round((first_x + last_x) / 2.0, 6), round(s / w, 6)])
    if not knots:
        mean = sum(y for _, y in ps) / len(ps)
        knots = [[0.0, round(mean, 6)], [1.0, round(mean, 6)]]
    return knots


def apply_isotonic(knots, p):
    p = min(max(float(p), 0.0), 1.0)
    if not knots:
        return p
    if p <= knots[0][0]:
        return float(knots[0][1])
    if p >= knots[-1][0]:
        return float(knots[-1][1])
    for i in range(1, len(knots)):
        x0, y0 = knots[i - 1]
        x1, y1 = knots[i]
        if p <= x1:
            if x1 - x0 <= 1e-12:
                return float(y1)
            frac = (p - x0) / (x1 - x0)
            return float(y0 + frac * (y1 - y0))
    return float(knots[-1][1])


def fit_platt(pairs, iters=100, l2=1e-6):
    """Two-parameter logistic recalibration: p_cal = sigmoid(a*logit(p) + b)."""
    ps = _clean_pairs(pairs)
    if not ps:
        return {"a": 1.0, "b": 0.0}
    xs = [logit(p) for p, _ in ps]
    ys = [y for _, y in ps]
    a, b = 1.0, 0.0
    for _ in range(iters):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for x, y in zip(xs, ys):
            p = sigmoid(a * x + b)
            d = p - y
            g0 += d * x
            g1 += d
            w = p * (1.0 - p)
            h00 += w * x * x
            h01 += w * x
            h11 += w
        h00 += l2
        h11 += l2
        det = h00 * h11 - h01 * h01
        if abs(det) < 1e-12:
            break
        da = (h11 * g0 - h01 * g1) / det
        db = (-h01 * g0 + h00 * g1) / det
        a -= da
        b -= db
        if abs(da) + abs(db) < 1e-9:
            break
    if not math.isfinite(a) or not math.isfinite(b):
        return {"a": 1.0, "b": 0.0}
    return {"a": max(min(a, 5.0), 0.05), "b": max(min(b, 10.0), -10.0)}


def _build_calibration(name, pairs):
    if name == "isotonic":
        return {"method": "isotonic", "knots": fit_isotonic(pairs), "n": len(pairs)}
    if name == "platt":
        platt = fit_platt(pairs)
        return {"method": "platt", "a": platt["a"], "b": platt["b"], "n": len(pairs)}
    return {"method": "identity", "n": len(pairs)}


def _holdout_scores(pairs, train_frac=0.6):
    """Brier of each candidate calibrator on a forward holdout split.

    The split is by time, not interleaved: these rows arrive in time order and
    calibration is only ever used forwards, so fitting on the older 60% and
    scoring the newer 40% is the question that matters. Calibration that only
    looks good in sample is worth nothing, and on an already-calibrated score
    the extra freedom of isotonic actively hurts, so identity has to be beaten
    by a margin before a recalibration is accepted.
    """
    ps = list(pairs)
    cut = int(len(ps) * train_frac)
    train, test = ps[:cut], ps[cut:]
    scores = {}
    for name in ("identity", "platt", "isotonic"):
        if len(train) < 10 or len(test) < 5 or len({y for _, y in train}) < 2:
            scores[name] = float("inf")
            continue
        model = _build_calibration(name, train)
        total = sum((apply_calibration(model, p) - y) ** 2 for p, y in test)
        scores[name] = total / len(test)
    return scores


def fit_calibration_model(pairs, *, min_n_isotonic=60, min_n_platt=15,
                          choose="holdout", margin=0.005):
    """Pick identity / Platt / isotonic for raw score -> hit rate.

    ``choose='holdout'`` (default) scores the three candidates on held-out rows
    and only accepts a recalibration that beats identity by ``margin``.
    ``choose='rule'`` falls back to the size rule: isotonic with volume, Platt
    with less, identity with almost nothing.
    """
    ps = _clean_pairs(pairs)
    n = len(ps)
    distinct = len({round(p, 4) for p, _ in ps})
    if n < min_n_platt or len({y for _, y in ps}) < 2:
        return {"method": "identity", "n": n}
    allowed = ["identity", "platt"]
    if n >= min_n_isotonic and distinct >= 4:
        allowed.append("isotonic")
    if choose == "rule" or n < 40:
        return _build_calibration(allowed[-1], ps)
    scores = _holdout_scores(ps)
    ranked = [name for name in allowed if math.isfinite(scores.get(name, float("inf")))]
    if not ranked:
        return _build_calibration("identity", ps)
    best = min(ranked, key=lambda name: scores[name])
    if best != "identity" and scores[best] > scores["identity"] - margin:
        best = "identity"
    model = _build_calibration(best, ps)
    model["holdout"] = {k: _r(v, 6) for k, v in scores.items()}
    model["candidates"] = allowed
    return model


def apply_calibration(model, p):
    if not model:
        return float(p)
    method = model.get("method", "identity")
    if method == "isotonic":
        return apply_isotonic(model.get("knots") or [], p)
    if method == "platt":
        return sigmoid(model.get("a", 1.0) * logit(p) + model.get("b", 0.0))
    return min(max(float(p), 0.0), 1.0)


def fit_calibration(con, horizon="1h", *, market=None, source="auto",
                    weights_payload=None, extras=("manip",), use_score=False,
                    bins=10):
    """Fit score -> hit-rate calibration on the current corpus.

    In-sample by construction (``evaluation: in_sample``); the honest number is
    the walk-forward one. Returns a payload ready for ``save_calibration``.
    """
    payload_w = weights_payload or load_weights(con, horizon=horizon, market=market)
    cases = load_cases(con, source, horizon=horizon, extras=extras, use_score=use_score)
    if market:
        cases = [c for c in cases
                 if str(c.get("market") or "").lower() == str(market).lower()
                 or str(c.get("symbol") or "").lower() == str(market).lower()]
    closed = [c for c in cases if c.get("label") is not None]
    pairs_raw, pairs_model = [], []
    for c in closed:
        p_base = _baseline_p(c)
        pairs_raw.append((p_base, c["label"]))
        if payload_w:
            pairs_model.append((_predict_case(c, payload_w), c["label"]))
    model = fit_calibration_model(pairs_model or pairs_raw)
    calibrated = [(apply_calibration(model, p), y) for p, y in (pairs_model or pairs_raw)]
    return {
        "version": VERSION,
        "created_at": iso(utcnow()),
        "kind": "score",
        "horizon": horizon,
        "market": market,
        "method": model.get("method"),
        "model": model,
        "n_cases": len(closed),
        "evaluation": "in_sample",
        "bins": bins,
        "before": summarize(pairs_model or pairs_raw, bins),
        "after": summarize(calibrated, bins),
        "baseline_raw": summarize(pairs_raw, bins),
        "weights_created_at": (payload_w or {}).get("created_at"),
    }


def save_calibration(con, payload) -> int:
    ensure_schema(con)
    con.execute(
        "INSERT INTO %s (created_at, market, horizon, kind, method, n_cases, payload)"
        " VALUES (?,?,?,?,?,?,?)" % _q(CALIBRATION_TABLE),
        (utcnow().timestamp(), payload.get("market"), payload.get("horizon"),
         payload.get("kind", "score"), payload.get("method"),
         payload.get("n_cases"), _dumps(payload)),
    )
    try:
        con.commit()
    except Exception:
        pass
    return 1


def load_calibration(con, horizon=None, market=None, kind="score"):
    if not _table_exists(con, CALIBRATION_TABLE):
        return None
    sql = "SELECT payload FROM %s WHERE kind = ?" % _q(CALIBRATION_TABLE)
    params = [kind]
    if horizon is not None:
        sql += " AND horizon = ?"
        params.append(horizon)
    if market is not None:
        sql += " AND (market = ? OR market IS NULL)"
        params.append(market)
    sql += " ORDER BY id DESC LIMIT 1"
    try:
        row = con.execute(sql, params).fetchone()
    except Exception:
        return None
    if not row:
        return None
    try:
        return json.loads(row[0])
    except (TypeError, ValueError):
        return None


def _baseline_p(case):
    """The engine as it stands: raw 0-100 score read as a probability."""
    score = _as_float(case.get("score"))
    if score is None:
        return 0.5
    return min(max(score / 100.0, 0.01), 0.99)


def _predict_case(case, payload):
    """Probability from a fitted weight payload, reproducing its standardization."""
    if not payload:
        return _baseline_p(case)
    coef = payload.get("coef") or {}
    center = payload.get("center") or {}
    scale = payload.get("scale") or {}
    eta = float(payload.get("intercept") or 0.0)
    used = 0
    for name, beta in coef.items():
        val = (case.get("factors") or {}).get(name)
        if val is None:
            z = 0.0
        else:
            z = (val - center.get(name, 0.0)) / (scale.get(name) or 1.0)
            used += 1
        eta += beta * z
    if not used:
        return _baseline_p(case)
    return sigmoid(eta)


# ---------------------------------------------------------------------------
# walk-forward test
# ---------------------------------------------------------------------------

def _split_blocks(items, n_blocks, start=0):
    """Index ranges of ``items[start:]`` cut into n_blocks contiguous blocks."""
    n = len(items)
    if n <= start:
        return []
    n_blocks = max(1, min(int(n_blocks), n - start))
    size = (n - start) / float(n_blocks)
    out = []
    for k in range(n_blocks):
        a = start + int(round(k * size))
        b = start + int(round((k + 1) * size))
        if b > a:
            out.append((a, b))
    return out


def _inner_oof(con, train, *, inner_folds, min_inner_train, horizon, market, prior,
               fit_kw):
    """Out-of-fold predictions inside the training window, for calibration only.

    Without this, calibration would be fitted on the same rows the weights were
    fitted on and would look better than it is.
    """
    if len(train) < min_inner_train + max(inner_folds, 1) * 5:
        return None
    blocks = _split_blocks(train, inner_folds, start=min_inner_train)
    pairs = []
    for a, b in blocks:
        sub_train = train[:a]
        if len({c["label"] for c in sub_train}) < 2:
            continue
        payload = fit_weights(con, horizon=horizon, market=market, prior=prior,
                              cases=sub_train, **fit_kw)
        for c in train[a:b]:
            pairs.append((_predict_case(c, payload), c["label"]))
    return pairs or None


def _metrics_block(pairs, bins=10):
    s = summarize(pairs, bins)
    return {
        "n": s["n"],
        "brier": _r(s["brier"]),
        "log_loss": _r(s["log_loss"]),
        "accuracy": _r(s["accuracy"]),
        "auc": _r(s["auc"]),
        "ece": _r(s["ece"]),
    }


def _r(value, nd=4):
    if value is None:
        return None
    try:
        return round(float(value), nd)
    except (TypeError, ValueError):
        return None


def paired_gain(learned_pairs, base_pairs, z_gate=1.645):
    """Per-row squared-error gain with a normal-approximation z score.

    A raw Brier improvement of 0.003 over 60 rows is noise. This asks whether
    the improvement is consistent row by row, which is the difference between a
    real edge and a lucky fold. ``z_gate`` 1.645 is one-sided 95%.
    """
    if not learned_pairs or len(learned_pairs) != len(base_pairs):
        return {"n": 0, "mean_gain": None, "z": None, "significant": False}
    diffs = []
    for (pl, yl), (pb, yb) in zip(learned_pairs, base_pairs):
        if (yl >= 0.5) != (yb >= 0.5):
            continue
        diffs.append((pb - yl) ** 2 - (pl - yl) ** 2)
    n = len(diffs)
    if n < 10:
        return {"n": n, "mean_gain": None, "z": None, "significant": False}
    mean = sum(diffs) / n
    var = sum((d - mean) ** 2 for d in diffs) / max(n - 1, 1)
    se = math.sqrt(var / n) if var > 0 else 0.0
    if se > 0:
        z = mean / se
    else:
        z = 99.0 if mean > 0 else 0.0
    return {"n": n, "mean_gain": mean, "z": z, "significant": bool(z >= z_gate)}


def walk_forward(con, horizon="1h", *, folds=5, market=None, source="auto",
                 embargo_days=1.0, mode="expanding", rolling_days=None,
                 min_train_cases=40, inner_folds=3, min_inner_train=20,
                 half_life_days=90.0, l2=1.0, prior_strength=150.0, min_events=25,
                 unverified_weight=0.35, extras=("manip",), use_score=False,
                 bins=10, min_eval_n=40, min_brier_gain=0.002, run_id=None,
                 persist=True):
    """Time-ordered out-of-fold test of the whole loop.

    Three arms are scored on identical test rows so the report shows what each
    change is worth:

    ``base_raw``   the engine as it stands (score/100 as the probability)
    ``base_cal``   same scores, calibration only, no reweighting
    ``learned``    reweighted from past outcomes + calibrated, fitted only on
                   data older than the fold minus the embargo
    """
    ensure_schema(con)
    cases = load_cases(con, source, horizon=horizon, extras=extras, use_score=use_score)
    if market:
        cases = [c for c in cases
                 if str(c.get("market") or "").lower() == str(market).lower()
                 or str(c.get("symbol") or "").lower() == str(market).lower()]
    closed = sorted(
        [c for c in cases if c.get("label") is not None and c.get("ts") is not None],
        key=lambda c: (c["ts"], str(c.get("case_id"))),
    )
    n = len(closed)
    start = max(int(min_train_cases), 1)
    need = start + max(int(folds), 1) * 3
    report = {
        "version": VERSION,
        "created_at": iso(utcnow()),
        "kind": "walk_forward",
        "horizon": horizon,
        "market": market,
        "source": source,
        "config": {
            "folds": folds, "embargo_days": embargo_days, "mode": mode,
            "rolling_days": rolling_days, "min_train_cases": min_train_cases,
            "inner_folds": inner_folds, "half_life_days": half_life_days,
            "l2": l2, "prior_strength": prior_strength, "min_events": min_events,
            "unverified_weight": unverified_weight, "extras": list(extras),
            "use_score": use_score,
        },
        "corpus": {
            "n_cases": len(cases),
            "n_closed": n,
            "n_positives": int(sum(c["label"] for c in closed)),
            "ts_range": [iso(closed[0]["ts"]), iso(closed[-1]["ts"])] if closed else [],
            "source_used": (closed[0].get("source") if closed else None),
            "has_factor_values": bool(closed and any(c.get("factors") for c in closed)),
        },
    }
    if n < need:
        report["status"] = "insufficient_data"
        report["reason"] = "need at least %d closed cases, have %d" % (need, n)
        report["promotion"] = {"recommend": False, "reason": "insufficient data"}
        if persist:
            _save_run(con, run_id or _run_id("wf", horizon), report, horizon, market)
        return report

    core_prior = load_core_weights(con)
    fit_kw = {
        "half_life_days": half_life_days, "l2": l2, "prior_strength": prior_strength,
        "min_events": min_events, "unverified_weight": unverified_weight,
        "extras": extras, "use_score": use_score, "source": source,
    }
    blocks = _split_blocks(closed, folds, start=start)
    fold_reports, pooled = [], {"learned": [], "base_raw": [], "base_cal": []}
    weight_history = []
    leakage_ok = True
    for k, (a, b) in enumerate(blocks):
        test = closed[a:b]
        fold_start = test[0]["ts"]
        cutoff = fold_start - timedelta(days=float(embargo_days or 0.0))
        if mode == "rolling" and rolling_days:
            lo = cutoff - timedelta(days=float(rolling_days))
            train = [c for c in closed if lo <= c["ts"] <= cutoff]
        else:
            train = [c for c in closed if c["ts"] <= cutoff]
        entry = {
            "fold": k,
            "train_n": len(train),
            "test_n": len(test),
            "train_ts": [iso(train[0]["ts"]), iso(train[-1]["ts"])] if train else [],
            "test_ts": [iso(test[0]["ts"]), iso(test[-1]["ts"])],
        }
        if len(train) < max(int(min_events), 20) or len({c["label"] for c in train}) < 2:
            entry["status"] = "skipped"
            entry["reason"] = "training window too small or single-class"
            fold_reports.append(entry)
            continue
        if train[-1]["ts"] >= test[0]["ts"]:
            leakage_ok = False
        weights_payload = fit_weights(con, horizon=horizon, market=market,
                                      prior=core_prior, cases=train, **fit_kw)
        oof = _inner_oof(con, train, inner_folds=inner_folds,
                         min_inner_train=min_inner_train, horizon=horizon,
                         market=market, prior=core_prior, fit_kw=fit_kw)
        if oof is None:
            oof = [(_predict_case(c, weights_payload), c["label"]) for c in train]
            entry["calibration_in_sample"] = True
        cal = fit_calibration_model(oof)
        cal_base = fit_calibration_model(
            [(_baseline_p(c), c["label"]) for c in train])

        learned_pairs, raw_pairs, cal_pairs = [], [], []
        for c in test:
            p_raw = _predict_case(c, weights_payload)
            p_cal = apply_calibration(cal, p_raw)
            p_base = _baseline_p(c)
            p_base_cal = apply_calibration(cal_base, p_base)
            learned_pairs.append((p_cal, c["label"]))
            raw_pairs.append((p_base, c["label"]))
            cal_pairs.append((p_base_cal, c["label"]))
            pooled["learned"].append((p_cal, c["label"]))
            pooled["base_raw"].append((p_base, c["label"]))
            pooled["base_cal"].append((p_base_cal, c["label"]))
            entry.setdefault("_rows", []).append(
                (c["case_id"], c["ts"].timestamp(), p_raw, p_cal, p_base, int(c["label"])))
        entry["weights_method"] = weights_payload.get("method")
        entry["weights"] = {k2: _r(v) for k2, v in (weights_payload.get("weights") or {}).items()}
        entry["weights_nonneg"] = {k2: _r(v) for k2, v in
                                   (weights_payload.get("weights_nonneg") or {}).items()}
        entry["alpha"] = {k2: _r(v) for k2, v in (weights_payload.get("alpha") or {}).items()}
        entry["calibration_method"] = cal.get("method")
        entry["metrics"] = {
            "learned": _metrics_block(learned_pairs, bins),
            "base_raw": _metrics_block(raw_pairs, bins),
            "base_cal": _metrics_block(cal_pairs, bins),
        }
        weight_history.append(weights_payload.get("weights") or {})
        fold_reports.append(entry)

    scored = [f for f in fold_reports if f.get("metrics")]
    report["folds"] = fold_reports
    report["status"] = "ok" if scored else "insufficient_data"
    if not scored:
        report["promotion"] = {"recommend": False, "reason": "no fold produced predictions"}
        if persist:
            _save_run(con, run_id or _run_id("wf", horizon), report, horizon, market)
        return report

    pooled_metrics = {arm: _metrics_block(pairs, bins) for arm, pairs in pooled.items()}
    base = pooled_metrics["base_raw"]
    learned = pooled_metrics["learned"]
    # one sign convention for every metric: positive = the learned loop is better
    improvement = {}
    for key in ("brier", "log_loss", "ece"):
        if base.get(key) is not None and learned.get(key) is not None:
            improvement[key] = _r(base[key] - learned[key])
    for key in ("auc", "accuracy"):
        if base.get(key) is not None and learned.get(key) is not None:
            improvement[key] = _r(learned[key] - base[key])
    improvement["convention"] = ("positive means the learned loop is better; "
                                 "brier/log_loss/ece lower is better, auc/accuracy higher")
    keys = set()
    for w in weight_history:
        keys.update(w)
    stability = {}
    for key in sorted(keys):
        vals = [w.get(key, 0.0) for w in weight_history]
        stability[key] = {"min": _r(min(vals)), "max": _r(max(vals)),
                          "mean": _r(sum(vals) / len(vals))}
    n_eval = learned.get("n") or 0
    reasons = []
    recommend = True
    if n_eval < min_eval_n:
        recommend = False
        reasons.append("only %d out-of-fold rows (need %d)" % (n_eval, min_eval_n))
    if improvement.get("brier") is None or improvement["brier"] < min_brier_gain:
        recommend = False
        reasons.append("brier gain %s below gate %s"
                       % (improvement.get("brier"), min_brier_gain))
    significance = paired_gain(pooled["learned"], pooled["base_raw"])
    if not significance["significant"]:
        recommend = False
        reasons.append("gain is not significant row by row (z=%s, n=%s)"
                       % (_r(significance["z"], 2), significance["n"]))
    if (base.get("auc") is not None and learned.get("auc") is not None
            and learned["auc"] < base["auc"] - 0.02):
        recommend = False
        reasons.append("ranking got worse (auc %s -> %s)"
                       % (base["auc"], learned["auc"]))
    if not leakage_ok:
        recommend = False
        reasons.append("leakage check failed: a training row is not older than its fold")

    report["pooled"] = pooled_metrics
    report["improvement"] = improvement
    report["significance"] = significance
    report["weight_stability"] = stability
    report["leakage"] = {
        "ok": leakage_ok,
        "embargo_days": embargo_days,
        "note": ("outcome resolution time is not stored, so the embargo is the only "
                 "guard; raise it to the typical holding period for slow horizons"),
    }
    report["promotion"] = {
        "recommend": bool(recommend),
        "reason": "; ".join(reasons) if reasons else "learned loop beat the baseline out of fold",
        "gate": {"min_eval_n": min_eval_n, "min_brier_gain": min_brier_gain,
                 "max_auc_drop": 0.02, "require_significant": True},
        "proposed_weights": None,
    }
    if persist:
        rid = run_id or _run_id("wf", horizon)
        report["run_id"] = rid
        rows = []
        for f in fold_reports:
            for row in f.pop("_rows", []) or []:
                rows.append((rid, row[0], f["fold"], row[1], row[2], row[3], row[4], row[5]))
        _save_run(con, rid, report, horizon, market)
        if rows:
            con.executemany(
                "INSERT OR REPLACE INTO %s (run_id, case_id, fold, ts, p_raw, p_cal,"
                " p_base, y) VALUES (?,?,?,?,?,?,?,?)" % _q(PREDICTIONS_TABLE), rows)
            try:
                con.commit()
            except Exception:
                pass
    else:
        for f in fold_reports:
            f.pop("_rows", None)
    return report


def _run_id(prefix, horizon):
    return "%s-%s-%s" % (prefix, horizon or "all",
                         utcnow().strftime("%Y%m%dT%H%M%S"))


def _save_run(con, run_id, report, horizon, market):
    ensure_schema(con)
    con.execute(
        "INSERT OR REPLACE INTO %s (run_id, created_at, kind, market, horizon, payload)"
        " VALUES (?,?,?,?,?,?)" % _q(RUNS_TABLE),
        (run_id, utcnow().timestamp(), report.get("kind", "run"), market, horizon,
         _dumps(report)),
    )
    try:
        con.commit()
    except Exception:
        pass
    report["run_id"] = run_id


def load_run(con, run_id=None, kind=None):
    if not _table_exists(con, RUNS_TABLE):
        return None
    sql = "SELECT payload FROM %s" % _q(RUNS_TABLE)
    where, params = [], []
    if run_id:
        where.append("run_id = ?")
        params.append(run_id)
    if kind:
        where.append("kind = ?")
        params.append(kind)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT 1"
    try:
        row = con.execute(sql, params).fetchone()
    except Exception:
        return None
    if not row:
        return None
    try:
        return json.loads(row[0])
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# data quality
# ---------------------------------------------------------------------------

def outcome_consistency(con, horizon="1h", limit=5):
    """Do ``outcomes.hit`` and the direction-adjusted return agree?

    ``ret_pct`` is a raw price change, so the directional return is
    ``ret_pct * (+1 LONG / -1 SHORT)``. When ``hit`` disagrees with its sign the
    two columns are measuring different things and every metric downstream is
    suspect, so this is reported before any weights are trusted.
    """
    cases = load_signals(con, horizon, extras=())
    both = [c for c in cases if c.get("dir_ret") is not None and c.get("hit_raw") is not None]
    mismatches = []
    for c in both:
        hit = _as_float(c.get("hit_raw"))
        if hit is None:
            continue
        if (c["dir_ret"] > 0) != (hit >= 0.5):
            mismatches.append({
                "case_id": c["case_id"],
                "direction": c.get("direction"),
                "ret_pct": c.get("ret_pct"),
                "dir_ret": c.get("dir_ret"),
                "hit": hit,
            })
    return {
        "horizon": horizon,
        "n": len(both),
        "mismatches": len(mismatches),
        "rate": (len(mismatches) / len(both)) if both else None,
        "examples": mismatches[:limit],
    }


# ---------------------------------------------------------------------------
# research corpus digest (self-reported, therefore suspect)
# ---------------------------------------------------------------------------

def research_digest(con, *, limit=20):
    """What the shared ``trade_cases`` corpus says, with its bias exposed.

    Reported separately from the engine's own signals because these rows are
    self-reported: unverified claims, chosen by whoever wrote them. Win rates are
    shown for all rows and for verified rows only, because the gap between the
    two is the size of the survivorship problem.
    """
    cases = load_research_cases(con)
    closed = [c for c in cases if c.get("label") is not None]
    verified = [c for c in closed if c.get("verified")]

    def _rate(rows):
        if not rows:
            return None
        return sum(c["label"] for c in rows) / len(rows)

    def _group(rows, key):
        groups = {}
        for c in rows:
            name = str(c.get(key) or "unknown")
            groups.setdefault(name, []).append(c)
        return {
            name: {"n": len(items), "win_rate": _rate(items)}
            for name, items in sorted(groups.items(), key=lambda kv: -len(kv[1]))
        }

    conf_pairs = [(c["confidence"], c["label"]) for c in closed
                  if c.get("confidence") is not None]
    overconfidence = None
    if conf_pairs:
        overconfidence = {
            "n": len(conf_pairs),
            "mean_stated_confidence": sum(p for p, _ in conf_pairs) / len(conf_pairs),
            "observed_win_rate": sum(y for _, y in conf_pairs) / len(conf_pairs),
            "brier_of_stated_confidence": brier(conf_pairs),
        }
        if overconfidence["mean_stated_confidence"] is not None:
            overconfidence["gap"] = (overconfidence["mean_stated_confidence"]
                                     - overconfidence["observed_win_rate"])

    losses = sorted(
        [c for c in closed if c["label"] == 0],
        key=lambda c: (-(c.get("confidence") or 0.0), c.get("ts") or utcnow()),
    )
    loss_notes = [{
        "case_id": c["case_id"],
        "market": c.get("market"),
        "side": c.get("direction"),
        "why_what": c.get("why_what"),
        "lesson": c.get("lesson"),
        "source_url": c.get("source_url"),
        "confidence": c.get("confidence"),
        "verified": c.get("verified"),
    } for c in losses[:limit]]

    urls = {}
    for c in cases:
        url = c.get("source_url")
        if url:
            urls[url] = urls.get(url, 0) + 1

    return {
        "n_rows": len(cases),
        "n_closed": len(closed),
        "n_open_or_flat": len(cases) - len(closed),
        "win_rate": _rate(closed),
        "verified": {"n": len(verified), "win_rate": _rate(verified)},
        "unverified": {"n": len(closed) - len(verified),
                       "win_rate": _rate([c for c in closed if not c.get("verified")])},
        "by_market": _group(closed, "market"),
        "by_side": _group(closed, "direction"),
        "stated_confidence": overconfidence,
        "losses_with_reasons": loss_notes,
        "n_sources": len(urls),
        "top_sources": sorted(urls.items(), key=lambda kv: -kv[1])[:10],
        "caveat": ("survivorship bias: these rows are self-reported and self-selected, "
                   "so the win rate is an upper bound, not an estimate"),
    }


# ---------------------------------------------------------------------------
# predict / run
# ---------------------------------------------------------------------------

def predict(con, factors, direction="LONG", *, horizon="1h", market=None,
            weights_payload=None, calibration_payload=None):
    """Score one candidate with the learned weights and calibration.

    ``factors`` are the engine's signed factors (positive = bullish). They are
    aligned by side here, exactly as they are during fitting.
    """
    dir_txt = str(direction or "LONG").strip().upper()
    dir_sign = -1.0 if dir_txt.startswith("S") else 1.0
    raw = {str(k): float(v) for k, v in (factors or {}).items()
           if _as_float(v) is not None}
    feats = {k: v * dir_sign for k, v in raw.items()}
    case = {"factors": feats, "score": None, "direction": dir_txt}
    w = weights_payload if weights_payload is not None else load_weights(
        con, horizon=horizon, market=market)
    cal = calibration_payload if calibration_payload is not None else load_calibration(
        con, horizon=horizon, market=market)
    p_raw = _predict_case(case, w)
    p_cal = apply_calibration((cal or {}).get("model"), p_raw)
    return {
        "direction": dir_txt,
        "aligned_factors": feats,
        "p_raw": p_raw,
        "p_calibrated": p_cal,
        "weights_created_at": (w or {}).get("created_at"),
        "weights_method": (w or {}).get("method"),
        "calibration_method": ((cal or {}).get("model") or {}).get("method"),
    }


def _filter_kwargs(fn, kwargs):
    """Only the keyword arguments this function actually accepts."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return dict(kwargs)
    if any(p.kind == p.VAR_KEYWORD for p in params.values()):
        return dict(kwargs)
    allowed = {name for name, p in params.items()
               if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}
    return {k: v for k, v in kwargs.items() if k in allowed}


def connect():
    """Open the core database via ``confluence.db`` (or a bare ``db`` module)."""
    last = None
    for name in ("confluence.db", "db"):
        try:
            mod = __import__(name, fromlist=["connect"])
        except Exception as exc:
            last = exc
            continue
        fn = getattr(mod, "connect", None)
        if callable(fn):
            return fn()
    raise RuntimeError(
        "cannot import the core db module (%s); pass an open connection instead, "
        "e.g. learning.run(con)" % (last,)
    )


def run(con=None, *, horizon="1h", folds=5, market=None, source="auto",
        promote=False, sync_research=True, persist=True, **kwargs):
    """One pass of the loop: ingest, fit weights, calibrate, walk-forward.

    Returns a summary dict and never raises for missing data; it reports what it
    could not do instead. Weight changes are only written when ``promote`` is
    True *and* the walk-forward gate passes.
    """
    con = con if con is not None else connect()
    ensure_schema(con)
    warnings = []
    n_research = 0
    if sync_research:
        try:
            n_research = sync_cases(con)
        except Exception as exc:
            warnings.append("research sync failed: %s" % exc)

    weights_payload = fit_weights(con, horizon=horizon, market=market, source=source,
                                  **_filter_kwargs(fit_weights, kwargs))
    if weights_payload.get("method") == "prior":
        warnings.append("weights stayed at the prior: %s"
                        % weights_payload.get("diagnostics", {}).get("reason"))
    if persist:
        save_weights(con, weights_payload)

    calibration_payload = fit_calibration(con, horizon=horizon, market=market,
                                          source=source, weights_payload=weights_payload)
    if persist:
        save_calibration(con, calibration_payload)

    wf = walk_forward(con, horizon=horizon, folds=folds, market=market, source=source,
                      persist=persist, **_filter_kwargs(walk_forward, kwargs))
    if wf.get("status") != "ok":
        warnings.append("walk-forward: %s" % wf.get("reason", wf.get("status")))

    consistency = outcome_consistency(con, horizon)
    if consistency["mismatches"]:
        warnings.append("outcomes.hit disagrees with the direction-adjusted return on "
                        "%d of %d rows; check which one the engine treats as truth"
                        % (consistency["mismatches"], consistency["n"]))

    applied = None
    if promote:
        gate = wf.get("promotion", {})
        if gate.get("recommend"):
            applied = apply_weights(con, weights_payload.get("weights_nonneg") or {},
                                    horizon=horizon)
            if not applied.get("applied"):
                warnings.append("promotion blocked: %s" % applied.get("reason"))
        else:
            warnings.append("promotion skipped: %s" % gate.get("reason"))
    if wf.get("promotion", {}).get("recommend"):
        wf["promotion"]["proposed_weights"] = weights_payload.get("weights_nonneg")

    summary = {
        "version": VERSION,
        "created_at": iso(utcnow()),
        "horizon": horizon,
        "market": market,
        "research_rows_synced": n_research,
        "corpus": wf.get("corpus"),
        "weights": {
            "method": weights_payload.get("method"),
            "weights": weights_payload.get("weights"),
            "weights_nonneg": weights_payload.get("weights_nonneg"),
            "extras_coef": weights_payload.get("extras_coef"),
            "alpha": weights_payload.get("alpha"),
            "n_events": weights_payload.get("n_events"),
            "diagnostics": weights_payload.get("diagnostics"),
        },
        "calibration": {
            "method": calibration_payload.get("method"),
            "n_cases": calibration_payload.get("n_cases"),
            "before": {k: _r(calibration_payload.get("before", {}).get(k))
                       for k in ("brier", "log_loss", "ece", "auc")},
            "after": {k: _r(calibration_payload.get("after", {}).get(k))
                      for k in ("brier", "log_loss", "ece", "auc")},
        },
        "walk_forward": {
            "status": wf.get("status"),
            "run_id": wf.get("run_id"),
            "pooled": wf.get("pooled"),
            "improvement": wf.get("improvement"),
            "promotion": wf.get("promotion"),
            "leakage": wf.get("leakage"),
        },
        "outcome_consistency": {k: consistency[k] for k in ("n", "mismatches", "rate")},
        "applied": applied,
        "warnings": warnings,
    }
    if persist:
        _save_run(con, _run_id("run", horizon), summary, horizon, market)
    return summary


def format_summary(summary):
    """A few lines a human can read, from run() or walk_forward() output."""
    lines = []
    corpus = summary.get("corpus") or {}
    if corpus:
        lines.append("corpus: %s closed cases, %s positives, %s -> %s (%s)"
                     % (corpus.get("n_closed"), corpus.get("n_positives"),
                        (corpus.get("ts_range") or ["?", "?"])[0],
                        (corpus.get("ts_range") or ["?", "?"])[1],
                        corpus.get("source_used")))
    weights = (summary.get("weights") or {}).get("weights")
    if weights:
        lines.append("weights: " + ", ".join("%s=%.3f" % (k, v)
                                             for k, v in sorted(weights.items())))
    cal = summary.get("calibration") or {}
    if cal.get("before"):
        b, a = cal["before"], cal["after"]
        lines.append("calibration (%s, in sample): brier %s -> %s, ece %s -> %s"
                     % (cal.get("method"), b.get("brier"), a.get("brier"),
                        b.get("ece"), a.get("ece")))
    wf = summary.get("walk_forward") or summary
    pooled = wf.get("pooled") or {}
    for arm in ("base_raw", "base_cal", "learned"):
        m = pooled.get(arm) or {}
        if m.get("n"):
            lines.append("walk-forward %-8s n=%s brier=%s logloss=%s ece=%s auc=%s"
                         % (arm, m.get("n"), m.get("brier"), m.get("log_loss"),
                            m.get("ece"), m.get("auc")))
    imp = wf.get("improvement") or {}
    if imp.get("brier") is not None:
        lines.append("gain: brier %+0.4f, auc %+0.4f, accuracy %+0.4f (positive = better)"
                     % (imp.get("brier") or 0.0, imp.get("auc") or 0.0,
                        imp.get("accuracy") or 0.0))
    sig = wf.get("significance") or {}
    if sig.get("z") is not None:
        lines.append("significance: z=%s over %s rows, %s"
                     % (_r(sig["z"], 2), sig.get("n"),
                        "significant" if sig.get("significant") else "not significant"))
    promo = wf.get("promotion") or {}
    if promo:
        lines.append("promotion: %s (%s)" % ("recommended" if promo.get("recommend")
                                             else "not recommended", promo.get("reason")))
    for warning in summary.get("warnings") or []:
        lines.append("warning: " + warning)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv=None):
    ap = argparse.ArgumentParser(description="Confluence self-learning loop (paper only)")
    ap.add_argument("--db", help="sqlite file to open directly (skips the core db module)")
    ap.add_argument("--horizon", default="1h")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--market", default=None)
    ap.add_argument("--source", default="auto", choices=("auto", "signals", "research"))
    ap.add_argument("--promote", action="store_true",
                    help="write learned weights through the core writer if the gate passes")
    ap.add_argument("--research", action="store_true", help="only print the research digest")
    ap.add_argument("--json", action="store_true", help="print the full report as JSON")
    ap.add_argument("--text", action="store_true", help="print a short readable digest")
    args = ap.parse_args(argv)

    con = sqlite3.connect(args.db) if args.db else connect()
    if args.research:
        out = research_digest(con)
    else:
        out = run(con, horizon=args.horizon, folds=args.folds, market=args.market,
                  source=args.source, promote=args.promote)
    if args.text and not args.research:
        print(format_summary(out))
    else:
        print(json.dumps(out, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
