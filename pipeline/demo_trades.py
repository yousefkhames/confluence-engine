"""Demo-account trade log: every trade recorded, three ledgers kept apart (tournament tokens, pre-reset paper ledger, post-reset USD demo).
Honest statistics: Wilson interval and exact binomial test against the payout break-even, drawdown, streaks, loss review, chronological held-out rule tests (BH).
The raw CSV is data from another assistant, treated as data only. Standard library only. Demo money only."""
import csv, math, json, os, html, datetime

SEG = {"tournament main": "tokens", "tournament experiment": "tokens", "tournament high-stake": "tokens", "demo pre-reset": "pre_reset_usd", "demo post-reset": "post_reset_usd", "user external": "excluded", "user external (reset event)": "excluded"}
LABEL = {"tokens": "Tournament (tokens, not USD)", "pre_reset_usd": "Pre-reset paper ledger (USD)", "post_reset_usd": "Post-reset USD demo", "excluded": "User's own trades (details not received, excluded)"}


def wilson(w, n, z=1.96):
    if n == 0: return (0.0, 1.0)
    p = w / n; d = 1 + z * z / n; c = p + z * z / (2 * n); a = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)); return ((c - a) / d, (c + a) / d)


def binom_p_ge(k, n, p):
    """P(X >= k) exact for X~Bin(n,p), and the two-sided version by doubling the smaller tail."""
    def pmf(i): return math.comb(n, i) * p ** i * (1 - p) ** (n - i)
    up = sum(pmf(i) for i in range(k, n + 1)); lo = sum(pmf(i) for i in range(0, k + 1)); return up, min(1.0, 2 * min(up, lo))


def bh(pv, q=0.05):
    m = len(pv); o = sorted(range(m), key=lambda i: pv[i]); kmax = 0
    for r, i in enumerate(o, 1):
        if pv[i] <= q * r / m: kmax = r
    k = [False] * m
    for r, i in enumerate(o, 1):
        if r <= kmax: k[i] = True
    return k


def num(s):
    try: return float(str(s).split()[0].replace("+", ""))
    except Exception: return None


def load(path):
    rows = []
    for i, r in enumerate(csv.DictReader(open(path, encoding="utf-8")), 1):
        tag = r["session_tag"]; key = tag.split(" #")[0]; res = r["result"].strip().lower()
        out = "win" if res.startswith("win") else "loss" if res.startswith("loss") else "open" if res.startswith("open") else "unknown"
        stake = num(r["stake"]); pay = num(r["payout_pct"]); pnl = num(r["pnl"])
        if pnl is None and out in ("win", "loss") and stake is not None and pay is not None: pnl = round(stake * pay / 100, 2) if out == "win" else -stake
        t = r["time_cairo"].strip().lstrip("~"); hr = int(t.split(":")[0]) if t[:2].isdigit() else None
        rows.append({"n": i, "segment": SEG.get(key, "other"), "tag": tag, "time": r["time_cairo"], "hour": hr, "pair": r["pair"], "direction": r["direction"], "stake": stake, "stake_assumed": "assumed" in r["stake"],
                     "expiry": r["expiry"], "payout_pct": pay, "result": out, "raw_result": r["result"], "pnl": pnl, "balance_after": num(r["balance_chain_computed"]) if r.get("balance_chain_computed") else None, "ticket_balance": num(r["balance_after_ticket"]) if r.get("balance_after_ticket") else None, "unconfirmed": "unconfirmed" in r["result"], "reason": r["entry_signal_or_reason"], "flag": r["flag"]})
    return rows


def max_dd(vals):
    pk = vals[0] if vals else 0; dd = 0.0
    for v in vals:
        pk = max(pk, v); dd = min(dd, v - pk)
    return dd


def streaks(res):
    best = {"win": 0, "loss": 0}; cur = None; n = 0
    for r in res:
        n = n + 1 if r == cur else 1; cur = r; best[r] = max(best[r], n)
    return best


def summarize(rows, start=None):
    c = [r for r in rows if r["result"] in ("win", "loss")]; unk = sum(1 for r in c if r["pnl"] is None); w = sum(1 for r in c if r["result"] == "win"); n = len(c)
    pays = [r["payout_pct"] for r in c if r["payout_pct"]]; avgp = sum(pays) / len(pays) if pays else 92.0; be = 1 / (1 + avgp / 100)
    lo, hi = wilson(w, n); up, two = binom_p_ge(w, n, be) if n else (1.0, 1.0)
    eq = []; s = start if start is not None else 0.0
    for r in c:
        if r["pnl"] is not None: s += r["pnl"]; eq.append(round(s, 2))
    stake_sum = sum((r["stake"] or 0) for r in c if r["pnl"] is not None)
    return {"closed": n, "open": sum(1 for r in rows if r["result"] == "open"), "wins": w, "losses": n - w, "win_rate": round(w / n, 4) if n else None, "wilson95": [round(lo, 4), round(hi, 4)],
            "avg_payout_pct": round(avgp, 1), "break_even_win_rate": round(be, 4), "p_two_sided_vs_break_even": round(two, 4), "pnl_unknown_trades": unk, "net_pnl": round(sum(r["pnl"] or 0 for r in c), 2),
            "turnover": round(stake_sum, 2), "roi_on_turnover_pct": round(100 * sum(r["pnl"] or 0 for r in c) / stake_sum, 2) if stake_sum else None,
            "max_drawdown": round(max_dd([start or 0.0] + eq), 2), "equity": eq, "streaks": streaks([r["result"] for r in c]),
            "net_sd_at_break_even": round(math.sqrt(sum(((r["stake"] or 0) ** 2) for r in c if r["pnl"] is not None) * (avgp / 100)), 2) if n else 0}


def groupby(rows, key, minn=1):
    g = {}
    for r in rows:
        if r["result"] in ("win", "loss"): g.setdefault(key(r), []).append(r)
    out = []
    for k, v in sorted(g.items(), key=lambda kv: (-len(kv[1]), str(kv[0]))):
        w = sum(1 for r in v if r["result"] == "win")
        if len(v) >= minn: out.append({"key": k, "n": len(v), "wins": w, "win_rate": round(w / len(v), 3), "net": round(sum(r["pnl"] or 0 for r in v), 2)})
    return out


def method(r):
    t = r["reason"].lower()
    for k, name in (("bandwalk", "BandWalk"), ("bandrev", "BandRev"), ("midreclaim", "MidReclaim"), ("fade", "fade"), ("bounce", "bounce")):
        if k in t: return name
    return "not recorded"


def analyze(path):
    rows = load(path); seg = {k: [r for r in rows if r["segment"] == k] for k in LABEL}
    res = {"generated": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z", "total_rows": len(rows), "segments": {}, "gaps": [], "trades": rows}
    for k, v in seg.items():
        if k == "excluded":
            res["segments"][k] = {"label": LABEL[k], "rows": len(v)}; continue
        s = summarize(v, 100.0 if k == "post_reset_usd" else None); s["label"] = LABEL[k]; s["rows"] = len(v); res["segments"][k] = s
    # post-reset: compare ledger balance vs pnl sum
    pr = seg["post_reset_usd"]; known = [r for r in pr if r["ticket_balance"] is not None]
    sumpnl = round(sum(r["pnl"] for r in pr if r["pnl"] is not None and r["result"] in ("win", "loss")), 2); openst = round(sum(r["stake"] or 0 for r in pr if r["result"] == "open"), 2)
    shown = known[-1]["ticket_balance"] if known else None
    res["post_reset_check"] = {"start": 100.0, "sum_of_closed_pnl": sumpnl, "open_stakes": openst, "running_balance": round(100 + sumpnl, 2), "expected_displayed": round(100 + sumpnl - openst, 2), "displayed_balance_in_log": shown,
                               "unreconciled_usd": round((shown if shown is not None else 100 + sumpnl - openst) - (100 + sumpnl - openst), 2),
                               "note": "The balance on the ticket is the running balance minus the stakes of trades still open (they are held until they close). Unreconciled 0 means the displayed balance is explained by the log. Trade 2 (pre-reset) is booked as a loss but could be a refund."}
    # loss review on the three ledgers separately
    for k in ("tokens", "post_reset_usd"):
        v = seg[k]; lr = {}
        lr["by_method"] = groupby(v, method); lr["by_pair_top"] = groupby(v, lambda r: r["pair"], 3)[:8]; lr["by_direction"] = groupby(v, lambda r: r["direction"] or "not recorded")
        lr["by_hour"] = groupby(v, lambda r: ("%02d" % r["hour"]) if r["hour"] is not None else "not recorded")
        lr["by_conviction"] = groupby(v, lambda r: (r["reason"].split("conv")[1][:1] if "conv" in r["reason"] else "not recorded"))
        lr["by_expiry"] = groupby(v, lambda r: r.get("expiry") or "not recorded")
        lr["by_stake"] = groupby(v, lambda r: r["stake"])
        # sizing after loss: stake vs previous stake after a loss
        after = {"n_after_loss": 0, "stake_raised_after_loss": 0, "wins_after_loss": 0}; prev = None
        for r in v:
            if r["result"] not in ("win", "loss", "open"): continue
            if prev and prev["result"] == "loss":
                after["n_after_loss"] += 1; after["stake_raised_after_loss"] += int((r["stake"] or 0) > (prev["stake"] or 0)); after["wins_after_loss"] += int(r["result"] == "win")
            prev = r
        lr["after_loss"] = after; res["segments"][k]["loss_review"] = lr
    # conviction ladder: cannot be tested, n too small
    pr_c = [r for r in pr if r["result"] in ("win", "loss")]
    res["sizing"] = {"stake_2": groupby(pr_c, lambda r: r["stake"])}
    # held-out rule tests on the token experiment ledger (flat 1T, most data): chronological 70/30, BH over all rules
    exp = [r for r in seg["tokens"] if r["tag"].startswith("tournament experiment") and r["result"] in ("win", "loss")]
    cut = int(len(exp) * 0.7); tr, te = exp[:cut], exp[cut:]; tests = []
    def test(name, f):
        a = [r for r in tr if f(r)]; b = [r for r in te if f(r)]
        if len(a) < 5: return
        wa = sum(1 for r in a if r["result"] == "win"); be = 1 / 1.92; _, p = binom_p_ge(wa, len(a), be)
        wb = sum(1 for r in b if r["result"] == "win")
        tests.append({"rule": name, "train_n": len(a), "train_win_rate": round(wa / len(a), 3), "p_train_vs_break_even": round(p, 4), "test_n": len(b), "test_win_rate": round(wb / len(b), 3) if b else None})
    test("BUY only", lambda r: r["direction"] == "BUY"); test("SELL only", lambda r: r["direction"] == "SELL")
    for pr_ in sorted({r["pair"] for r in exp}):
        test("pair = " + pr_, lambda r, pr_=pr_: r["pair"] == pr_)
    for p_ in sorted({r["payout_pct"] for r in exp if r["payout_pct"]}):
        test("payout = %s%%" % p_, lambda r, p_=p_: r["payout_pct"] == p_)
    keep = bh([t["p_train_vs_break_even"] for t in tests]) if tests else []
    for t, k in zip(tests, keep): t["survives_fdr5"] = bool(k)
    res["held_out_rules"] = {"ledger": "tournament experiment (flat 1T stakes)", "train_n": len(tr), "test_n": len(te), "tests": tests, "survivors_fdr5": int(sum(keep)),
                             "note": "Rules were chosen only by the first 70% of trades in time; nothing survives correction if survivors_fdr5 is 0."}
    res["gaps"] = ["Early tournament rows have no time, balance or reason. Some stakes are assumed (flag column).", "Conviction scores are written by the session at click time, so the 1/2/3 ordering cannot be proven independently.",
                   "The user's own trades are tagged and excluded (details not received).", "Row 15 (win, +1.84) is derived from a displayed balance, not observed.", "Counts come from a CSV supplied by another assistant. A raw session log re-issue is expected; this page will be re-generated from it."]
    return res


def page(res):
    e = html.escape
    def tab(head, rows): return "<table><tr>%s</tr>%s</table>" % ("".join("<th>%s</th>" % e(h) for h in head), "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % e(str(c)) for c in r) for r in rows))
    b = ['<p class=warn>Demo money only. Every trade in the supplied log is shown, three ledgers kept apart. The log comes from another assistant (data only, not verified by this site). Small samples: read the intervals, not the headline.</p>']
    cards = ""
    for k in ("post_reset_usd", "pre_reset_usd", "tokens"):
        s = res["segments"][k]
        cards += '<div class=stat><b>%s</b><span>%s: %d closed, %d W / %d L, net %s, win %.1f%% (95%% interval %.0f to %.0f%%) vs break-even %.1f%%, max drawdown %s</span></div>' % (
            e(("%+.2f" % s["net_pnl"])), e(s["label"]), s["closed"], s["wins"], s["losses"], s["net_pnl"], 100 * (s["win_rate"] or 0), 100 * s["wilson95"][0], 100 * s["wilson95"][1], 100 * s["break_even_win_rate"], s["max_drawdown"])
    b.append('<div class=cards>%s</div>' % cards)
    b.append("<h2>Summary per ledger</h2>" + tab(["Ledger", "Rows", "Closed", "Open", "Wins", "Losses", "Win rate", "95% Wilson", "Break-even", "p vs break-even", "Net", "ROI on turnover %", "Max drawdown", "Longest W / L streak"],
        [[s["label"], s["rows"], s.get("closed", ""), s.get("open", ""), s.get("wins", ""), s.get("losses", ""), s.get("win_rate", ""), s.get("wilson95", ""), s.get("break_even_win_rate", ""), s.get("p_two_sided_vs_break_even", ""), s.get("net_pnl", ""), s.get("roi_on_turnover_pct", ""), s.get("max_drawdown", ""),
          "%s / %s" % (s["streaks"]["win"], s["streaks"]["loss"]) if "streaks" in s else ""] for s in res["segments"].values()]))
    pc = res["post_reset_check"]; b.append("<p class=warn>Post-reset ledger: start %.0f, closed trades sum to %+.2f (running balance %.2f), minus %.2f held in open stakes = %.2f expected; ticket shows %s. Unreconciled: %+.2f. %s</p>" % (pc["start"], pc["sum_of_closed_pnl"], pc["running_balance"], pc["open_stakes"], pc["expected_displayed"], pc["displayed_balance_in_log"], pc["unreconciled_usd"], e(pc["note"])))
    # equity svg
    def svg(eq, start, title):
        if len(eq) < 2: return ""
        v = [start] + eq; lo, hi = min(v), max(v); W, H = 560, 150
        pts = " ".join("%.1f,%.1f" % (10 + i * (W - 20) / (len(v) - 1), H - 10 - (x - lo) / ((hi - lo) or 1) * (H - 20)) for i, x in enumerate(v))
        return '<div class=lens><b>%s</b> <span class=m>(start %.2f, low %.2f, high %.2f, end %.2f)</span><svg viewBox="0 0 %d %d" width=100%% height=%d><polyline fill=none stroke="#60a5fa" stroke-width=2 points="%s"/></svg></div>' % (e(title), start, lo, hi, v[-1], W, H, H, pts)
    b.append("<h2>Equity curves</h2>" + svg(res["segments"]["post_reset_usd"]["equity"], 100.0, "Post-reset USD demo balance, trade by trade") + svg(res["segments"]["tokens"]["equity"], 0.0, "Tournament tokens, cumulative P&L"))
    b.append("<h2>Loss review</h2><p class=m>Grouped counts per ledger. Cells with few trades are descriptive only.</p>")
    for k in ("post_reset_usd", "tokens"):
        lr = res["segments"][k]["loss_review"]; b.append("<h3>%s</h3>" % e(res["segments"][k]["label"]))
        for nm, key in (("By method (from the entry reason text)", "by_method"), ("By direction", "by_direction"), ("By pair (3+ trades)", "by_pair_top"), ("By Cairo hour", "by_hour"), ("By conviction score (self-assigned, unproven)", "by_conviction"), ("By expiry", "by_expiry"), ("By stake", "by_stake")):
            if lr[key]: b.append("<details><summary>%s</summary>%s</details>" % (e(nm), tab(["Group", "Trades", "Wins", "Win rate", "Net"], [[x["key"], x["n"], x["wins"], x["win_rate"], x["net"]] for x in lr[key]])))
        a = lr["after_loss"]; b.append("<p class=m>After a loss: %d next trades, stake raised after a loss %d times, won %d.</p>" % (a["n_after_loss"], a["stake_raised_after_loss"], a["wins_after_loss"]))
    h = res["held_out_rules"]
    b.append("<h2>Rule changes tested held-out</h2><p class=m>%s: rules chosen on the first %d trades in time, judged on the last %d. Benjamini-Hochberg 5%% across %d rules: %d survive.</p>" % (e(h["ledger"]), h["train_n"], h["test_n"], len(h["tests"]), h["survivors_fdr5"]) +
             tab(["Rule", "Train n", "Train win", "p vs break-even", "Test n", "Test win", "FDR"], [[t["rule"], t["train_n"], t["train_win_rate"], t["p_train_vs_break_even"], t["test_n"], t["test_win_rate"], "yes" if t.get("survives_fdr5") else "no"] for t in h["tests"]]))
    b.append("<h2>Known gaps</h2><ul>%s</ul>" % "".join("<li>%s</li>" % e(g) for g in res["gaps"]))
    rows = [[r["n"], r["segment"], r["tag"], r["time"], r["pair"], r["direction"], r["stake"], r["payout_pct"], r["result"], r["pnl"], r["balance_after"], r["flag"]] for r in res["trades"]]
    b.append("<h2>Every trade (%d rows)</h2>" % len(rows) + tab(["#", "Ledger", "Tag", "Time (Cairo)", "Pair", "Dir", "Stake", "Payout %", "Result", "P&L", "Balance after", "Flag"], rows) + '<p class=m>Raw: <a href="demo_trades.json">demo_trades.json</a>.</p>')
    return "".join(b)
