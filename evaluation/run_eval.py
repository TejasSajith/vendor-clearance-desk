"""Evaluation harness: run policy+decision over labelled cases, report metrics, compare parameter sets
(report-only), and sweep parameters. It never changes config: Tejas picks the values.

  python evaluation/run_eval.py                          # baseline (proposed params), summary
  python evaluation/run_eval.py --verbose                # per-case results
  python evaluation/run_eval.py --compare cand.json      # shadow mode: what would change under candidate params
  python evaluation/run_eval.py --sweep sweep.json --top 10
Synthetic cases only test the logic. Tuning on them says nothing about real vendors: add real cases first."""
import argparse, itertools, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import policy, decision

DEFINITIVE = {"CLEARED", "REJECTED"}
# Cost of each kind of error. PROPOSED: a wrong answer counts against us more than "cannot verify" (problem statement).
WEIGHTS = {"wrong": 3.0, "abstain": 1.0, "hold_vs_cnv": 0.5}

def verdict_for(case, params):
    checks = policy.evaluate(case["signals"], params, case.get("risk_tier", "low"))
    return decision.decide(checks).verdict

def cost(expected, got, w):
    if got == expected: return 0.0
    if got in DEFINITIVE: return w["wrong"]                      # a definitive answer that is not the right one
    if expected in DEFINITIVE: return w["abstain"]               # we abstained when an answer existed
    return w["hold_vs_cnv"]                                      # CANNOT_VERIFY vs HOLD mix-up

def run(cases, params, weights=WEIGHTS):
    res = [{"id": c["id"], "expected": c["expected"], "got": verdict_for(c, params), "group": c.get("group")} for c in cases]
    for r in res: r["cost"] = cost(r["expected"], r["got"], weights)
    groups = {}
    for r in res:
        if r["group"]: groups.setdefault(r["group"], []).append(r)
    consistent = sum(1 for g in groups.values() if len({x["got"] for x in g}) == 1 and all(x["got"] == x["expected"] for x in g))
    return {"results": res, "n": len(res), "correct": sum(r["got"] == r["expected"] for r in res),
            "wrong_definitive": sum(1 for r in res if r["got"] in DEFINITIVE and r["got"] != r["expected"]),
            "false_clear": sum(1 for r in res if r["got"] == "CLEARED" and r["expected"] != "CLEARED"),
            "false_reject": sum(1 for r in res if r["got"] == "REJECTED" and r["expected"] != "REJECTED"),
            "abstained": sum(1 for r in res if r["got"] not in DEFINITIVE and r["expected"] in DEFINITIVE),
            "loss": round(sum(r["cost"] for r in res), 2),
            "groups": len(groups), "groups_consistent": consistent}

def line(m): return (f"correct {m['correct']}/{m['n']}  wrong-definitive {m['wrong_definitive']} (false-clear {m['false_clear']}, "
                     f"false-reject {m['false_reject']})  abstained-when-answer-existed {m['abstained']}  "
                     f"paraphrase-groups-consistent {m['groups_consistent']}/{m['groups']}  loss {m['loss']}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", nargs="+", default=[str(Path(__file__).parent / "cases_synthetic.json")])
    ap.add_argument("--params"); ap.add_argument("--weights"); ap.add_argument("--compare"); ap.add_argument("--sweep")
    ap.add_argument("--top", type=int, default=10); ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    cases = [c for f in a.cases for c in json.loads(Path(f).read_text())]
    w = {**WEIGHTS, **json.loads(Path(a.weights).read_text())} if a.weights else WEIGHTS
    base_p = policy.load_params(a.params)
    base = run(cases, base_p, w)
    print(f"BASELINE ({len(cases)} cases): {line(base)}")
    if a.verbose:
        for r in base["results"]:
            print(f"  {'ok ' if r['got']==r['expected'] else 'BAD'} {r['id']:<28} expected {r['expected']:<18} got {r['got']}")
    if a.compare:
        cand = run(cases, policy.load_params(a.compare), w)
        print(f"CANDIDATE: {line(cand)}")
        diffs = [(b, c) for b, c in zip(base["results"], cand["results"]) if b["got"] != c["got"]]
        print(f"{len(diffs)} verdict(s) would change (report-only, nothing applied):")
        for b, c in diffs: print(f"  {b['id']:<28} {b['got']} -> {c['got']}  (expected {b['expected']})")
    if a.sweep:
        grid = {k: v for k, v in json.loads(Path(a.sweep).read_text()).items() if not k.startswith("_")}
        rows = []
        for combo in itertools.product(*grid.values()):
            p = {**base_p, **dict(zip(grid.keys(), combo))}
            m = run(cases, p, w); rows.append((m["loss"], m["wrong_definitive"], m["abstained"], dict(zip(grid.keys(), combo))))
        rows.sort(key=lambda r: (r[0], r[1]))
        print(f"SWEEP: {len(rows)} combinations, best {a.top} by loss. Ties are common: choose with Tejas, do not auto-apply.")
        for loss, wr, ab, combo in rows[:a.top]: print(f"  loss {loss:<6} wrong {wr}  abstained {ab}  {combo}")
if __name__ == "__main__": main()
