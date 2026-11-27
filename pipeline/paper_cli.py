"""python -m pipeline.paper_cli --state paper/state.json --minutes 27 : run the live paper test, write stats.json next to the state."""
import argparse, json, os, datetime
from pipeline import paper


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--state", default="paper/state.json"); ap.add_argument("--minutes", type=float, default=27)
    a = ap.parse_args()
    book, log = paper.run(a.state, a.minutes)
    stats = paper.aggregate(book)
    stats.update({"generated": datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z", "meta": book.meta, "pending": len(book.pending),
                  "instruments": sorted({k.split("|")[0] for k in book.cells}), "horizons": list(paper.HORIZONS), "run": log,
                  "not_covered": "silver and oil (no free live feed verified); horizons under 30s; real-venue latency and spread"})
    json.dump(stats, open(os.path.join(os.path.dirname(a.state) or ".", "stats.json"), "w"), indent=1)
    print(json.dumps({k: stats[k] for k in ("tests", "survivors", "pending", "meta", "run")}, default=str))


if __name__ == "__main__":
    main()
