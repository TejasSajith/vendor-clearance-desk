"""PHASE 1 (independent, parallel run): live-collect SIGNALS for every row of evaluation/cases_real.csv.

Runs alongside Tejas's evaluation/collect_signals.py by design (the user chose "run in parallel"). To avoid
clobbering that run it writes only NAMESPACED files and keeps its own SQLite ledger:
  evaluation/signals_real.sid.json    per-row signals + per-row state   (NO verdicts, NO labels)
  evaluation/stability_real.sid.json  adverse hit/date stability over 3 repeats for 12 rows
  evaluation/tuning_progress.sid.md   checkpoint written >= every 10 min (done / credits / remaining)
  probe/live/tuning_sid.db            cost+evidence ledger and response cache (gitignored)

Rules honoured (AGENTS.md + task): never writes policy.py/config.json; writes no labels; no person names in
any file (no claimed director -> no /person call is ever made); every external call goes through
core.cached_call (throttle, cache, limit, ledger, retry); exactly-once on resume (global response cache keyed
on endpoint+params; terminal rows skipped); a timeout is never "nothing found" (adverse -> unreachable); on
429 live._post backs off using the reset time. Per-vendor outcomes go to FILES ONLY; the console prints only
aggregate counts and credits.

    python evaluation/collect_real_sid.py [--credits 600] [--minutes 45] [--stability 12]
"""
import argparse, csv, hashlib, json, subprocess, sys, time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import core, pipeline
from checks import adverse, exists, live, normalize

EV = ROOT / "evaluation"
CSV = EV / "cases_real.csv"
SIGNALS = EV / "signals_real.sid.json"
STABILITY = EV / "stability_real.sid.json"
PROGRESS = EV / "tuning_progress.sid.md"
DBDIR = ROOT / "probe" / "live"
DB = DBDIR / "tuning_sid.db"
COMMIT_FILES = ["evaluation/signals_real.sid.json", "evaluation/stability_real.sid.json",
                "evaluation/tuning_progress.sid.md", "evaluation/tuning_report.sid.md", "evaluation/collect_real_sid.py"]
CHECKPOINT_SECONDS = 600          # 10 minutes
TERMINAL = {"done", "no_record", "ambiguous"}   # rows not worth re-running on resume


class SidSources(live.LiveSources):
    """Live Crustdata sources. identify keeps no third-party company names (only id, our similarity, domain).
    adverse runs FOUR distinct, name-scoped searches and supports repeat= for the stability probe."""

    def identify(self, ctx, name, domain):
        res = live.call(ctx, "/company/identify", {"names": [name]})
        ms = (res[0]["matches"] if res else []) or []
        cands = [{"id": m["company_data"]["basic_info"]["crustdata_company_id"], "name": "",
                  "sim": exists.token_sort_ratio(name, m["company_data"]["basic_info"].get("name") or ""),
                  "domain": normalize.normalize_domain(m["company_data"]["basic_info"].get("primary_domain")) or None}
                 for m in ms]
        dom_ids = None
        if domain:
            dres = live.call(ctx, "/company/identify", {"domains": [domain]})
            dom_ids = [m["company_data"]["basic_info"]["crustdata_company_id"]
                       for m in ((dres[0]["matches"] if dres else []) or [])]
        self.records = {c["id"]: c for c in cands}
        return {"candidates": cands, "status": None, "domain_candidate_ids": dom_ids}

    QUERIES = ((" fraud OR scam OR default OR FIR OR blacklisted", "web"),
               (" FIR OR arrested OR police complaint OR chargesheet", "web"),
               (" insolvency OR NCLT OR bankruptcy OR default OR struck off", "news"),
               (" blacklisted OR banned OR penalty OR scam", "news"))

    def adverse(self, ctx, name, domain="", repeat=0):
        hits, ran, scanned = [], 0, 0
        for suffix, src in self.QUERIES:
            body = {"query": f"{name}{suffix}", "sources": [src], "location": "IN"}
            logged = {**body, "_repeat": repeat} if repeat else body    # distinct cache key per repeat; marker never sent to the API
            res = ctx.call("/web/search/live", logged, lambda b=body: live._post("/web/search/live", b),
                           credits_from=lambda o: o["credits"])["body"]
            ran += 1
            rs = res.get("results") or []
            scanned += len(rs)
            for r in rs:
                hs = adverse.build_hits([r], name, domain)   # name/domain-scoped; returns flags + url_host only
                if hs:
                    h = hs[0]
                    m = adverse.DATE_PREFIX.match(r.get("snippet", "") or "")
                    h["date_text"] = m.group(1) if m else None      # the date prefix only (needed for date-stability), never the snippet body
                    h["url_id"] = hashlib.sha256((r.get("url", "") or "").encode()).hexdigest()[:10]
                    h["query_src"] = src
                    hits.append(h)
        return {"state": "searched", "searches_run": ran, "results_scanned": scanned, "hits": hits,
                "sources": ["crustdata:/web/search/live"]}


# ---------- helpers ----------
def load_cases():
    with CSV.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))

def total_credits(db):
    return round(db.execute("SELECT COALESCE(SUM(credits),0) FROM calls").fetchone()[0], 3)

def load_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default

def save_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)                                   # atomic: a crash never leaves a half-written file

def row_outcome(sig, state):
    if "not_run" in state.values(): return "stopped_at_cap"
    if "unreachable" in state.values(): return "unreachable"
    idn = sig.get("identify") or {}
    if idn.get("ambiguous"): return "ambiguous"
    if not idn.get("found"): return "no_record"
    return "done"

def hit_summary(h):
    return {"url_id": h.get("url_id"), "url_host": h.get("url_host"), "severity": h.get("severity"),
            "dated": h.get("dated"), "date_text": h.get("date_text"), "query_src": h.get("query_src")}


# ---------- one row ----------
def collect_row(db, case, src, run_id):
    name = case["vendor_name"]
    domain = normalize.normalize_domain(case.get("website") or "")
    core.start_run(db, json.dumps({"vendor_name": name, "website": domain}), run_id=run_id)
    ctx = pipeline.Ctx(db, run_id)
    state = {}

    def stage(n, fn):
        if "not_run" in state.values(): state[n] = "not_run"; return None
        try:
            out = core.run_step(db, run_id, n, fn); state[n] = "ok"; return out
        except (core.TransientError, core.SourceUnreachable):
            state[n] = "unreachable"; return None       # a timeout is never "nothing found"
        except core.LimitExceeded:
            state[n] = "not_run"; return None           # a per-run cap stopped this vendor

    ident = stage("identify", lambda: src.identify(ctx, name, domain))
    sig = {"identify": pipeline.identify_signals(name, domain, ident) if ident is not None else {}}
    cid = sig["identify"].get("company_id")
    if cid is not None:
        sig["profile"] = stage("profile", lambda: src.profile(ctx, cid))
        if sig["profile"] and sig["profile"].get("status"):
            sig["identify"]["status"] = sig["profile"]["status"]
    sig["director"] = {"not_requested": True, "sources": []}     # no claimed director: no person data, ever
    adv = stage("adverse", lambda: src.adverse(ctx, name, domain, repeat=0))
    if adv is not None: sig["adverse"] = adv
    sig = {k: v for k, v in sig.items() if v is not None}
    core.purge_sensitive(db, run_id)
    return sig, state, row_outcome(sig, state)


# ---------- git checkpoint ----------
def _git(args):
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True)

def git_checkpoint(msg):
    try:
        existing = [f for f in COMMIT_FILES if (ROOT / f).exists()]   # git add is all-or-nothing; skip files not written yet
        if not existing:
            return "nothing to add"
        _git(["add", *existing])
        if _git(["diff", "--cached", "--quiet"]).returncode == 0:
            return "nothing to commit"
        _git(["commit", "-q", "-m", msg])
        r = _git(["pull", "--rebase", "origin", "main"])
        if r.returncode != 0:
            _git(["rebase", "--abort"])
            return "push skipped (rebase conflict); will retry next checkpoint"
        p = _git(["push", "origin", "main"])
        return "pushed" if p.returncode == 0 else f"commit ok, push failed: {p.stderr.strip()[:120]}"
    except Exception as e:
        return f"git error (non-fatal): {e!r}"


def write_progress(results, credits, started, cap_credits, cap_minutes, n_total, phase, git_note=""):
    done = Counter(v["state"] for v in results.values())
    elapsed = (time.time() - started) / 60
    lines = [
        "# Tuning progress (SiD parallel run) — checkpoint",
        "",
        f"- as of: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- phase: {phase}",
        f"- rows collected: {len(results)} / {n_total}",
        f"- credits spent (this run's ledger): {credits:.2f} / {cap_credits} cap",
        f"- wall clock: {elapsed:.1f} / {cap_minutes} min",
        f"- last checkpoint git: {git_note}",
        "",
        "## per-row state (counts only)",
    ]
    for s in ("done", "no_record", "ambiguous", "unreachable", "stopped_at_cap"):
        lines.append(f"- {s}: {done.get(s, 0)}")
    remaining = n_total - len([v for v in results.values() if v["state"] in TERMINAL])
    lines += ["", f"## remaining", f"- rows not yet terminal (would run on resume): {remaining}",
              "", "Files: evaluation/signals_real.sid.json, evaluation/stability_real.sid.json. No labels, no verdicts, no person names."]
    PROGRESS.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------- main ----------
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--credits", type=float, default=600.0)
    ap.add_argument("--minutes", type=float, default=45.0)
    ap.add_argument("--stability", type=int, default=12)
    a = ap.parse_args(argv)

    DBDIR.mkdir(parents=True, exist_ok=True)
    db = core.connect(str(DB))
    src = SidSources()
    cases = load_cases()
    n_total = len(cases)
    started = time.time()
    proc = int(started)
    deadline = started + a.minutes * 60

    results = load_json(SIGNALS, {})       # case_id -> {state, signals, credits_row, ts}
    stability = load_json(STABILITY, {})
    last_ckpt = time.time()

    def over_budget():
        return total_credits(db) >= a.credits or time.time() >= deadline

    def checkpoint(phase):
        note = git_checkpoint(f"eval: sid collection checkpoint ({phase}, {len(results)}/{n_total} rows)")
        write_progress(results, total_credits(db), started, a.credits, a.minutes, n_total, phase, note)
        # progress file itself is part of the next commit; commit it too so it is never left behind
        git_checkpoint(f"eval: sid progress ({phase}, {len(results)}/{n_total} rows)")
        print(f"[checkpoint] {phase} rows={len(results)}/{n_total} credits={total_credits(db):.2f} "
              f"elapsed={(time.time()-started)/60:.1f}m git={note}", flush=True)

    # ----- PHASE 1a: one live pass over every row -----
    for case in cases:
        cid_key = case["case_id"]
        prev = results.get(cid_key)
        if prev and prev.get("state") in TERMINAL:
            continue                                   # exactly-once: already collected, don't re-run or re-pay
        if over_budget():
            results.setdefault(cid_key, {"state": "stopped_at_cap", "signals": {},
                                         "ts": time.time(), "note": "cap reached before this row ran"})
            continue
        run_id = f"sid_{proc}_{cid_key}"
        sig, state, outcome = collect_row(db, case, src, run_id)
        results[cid_key] = {"state": outcome, "stratum": case.get("stratum"), "split": case.get("split"),
                            "stages": state, "signals": sig, "ts": time.time()}
        save_json(SIGNALS, results)
        print(f"[collect] done={len([1 for v in results.values() if v['state'] in TERMINAL])} "
              f"attempted={len(results)}/{n_total} credits={total_credits(db):.2f} "
              f"elapsed={(time.time()-started)/60:.1f}m", flush=True)
        if time.time() - last_ckpt >= CHECKPOINT_SECONDS:
            checkpoint("pass"); last_ckpt = time.time()

    save_json(SIGNALS, results)            # persist any rows marked stopped_at_cap by the budget guard
    checkpoint("pass-complete")

    # ----- PHASE 1b: adverse stability on N rows, stratified, 3 repeats >= 1 min apart -----
    by_stratum = {}
    for case in cases:
        by_stratum.setdefault(case.get("stratum"), []).append(case)
    selected, per = [], max(1, a.stability // max(1, len(by_stratum)))
    for st, rows in by_stratum.items():
        selected += rows[:per]
    selected = selected[:a.stability]

    # round 0 comes from the main pass (reuse its adverse hits + timestamp)
    for case in selected:
        k = case["case_id"]
        r = results.get(k) or {}
        adv = (r.get("signals") or {}).get("adverse")
        stability.setdefault(k, {"stratum": case.get("stratum"), "rounds": []})
        if adv is not None and not any(rd["round"] == 0 for rd in stability[k]["rounds"]):
            stability[k]["rounds"].append({"round": 0, "ts": r.get("ts"),
                                           "hits": [hit_summary(h) for h in adv.get("hits", [])],
                                           "searches_run": adv.get("searches_run"), "results_scanned": adv.get("results_scanned")})
    save_json(STABILITY, stability)

    for rnd in (1, 2):
        round_start = time.time()
        for case in selected:
            if over_budget():
                break
            k = case["case_id"]
            if any(rd["round"] == rnd for rd in stability.get(k, {}).get("rounds", [])):
                continue                                # already have this repeat (resume)
            name = case["vendor_name"]; domain = normalize.normalize_domain(case.get("website") or "")
            run_id = f"sid_{proc}_{k}_r{rnd}"
            core.start_run(db, json.dumps({"vendor_name": name, "website": domain}), run_id=run_id)
            ctx = pipeline.Ctx(db, run_id)
            try:
                adv = src.adverse(ctx, name, domain, repeat=rnd)
            except (core.TransientError, core.SourceUnreachable, core.LimitExceeded):
                adv = {"state": "unreachable", "hits": [], "searches_run": 0, "results_scanned": 0}
            stability.setdefault(k, {"stratum": case.get("stratum"), "rounds": []})
            stability[k]["rounds"].append({"round": rnd, "ts": time.time(), "state": adv.get("state", "searched"),
                                           "hits": [hit_summary(h) for h in adv.get("hits", [])],
                                           "searches_run": adv.get("searches_run"), "results_scanned": adv.get("results_scanned")})
            save_json(STABILITY, stability)
            if time.time() - last_ckpt >= CHECKPOINT_SECONDS:
                checkpoint("stability"); last_ckpt = time.time()
        if over_budget():
            break
        gap = time.time() - round_start                 # guarantee >= 60 s between a row's consecutive repeats
        if gap < 60:
            time.sleep(60 - gap)

    # stability summary per row: are the hit sets and dates stable across rounds?
    for k, v in stability.items():
        rounds = [rd for rd in v["rounds"] if rd.get("state", "searched") == "searched"]
        sets = [frozenset(h["url_id"] for h in rd["hits"]) for rd in rounds]
        dates = [frozenset((h["url_id"], h["date_text"]) for h in rd["hits"]) for rd in rounds]
        union = set().union(*sets) if sets else set()
        inter = set.intersection(*[set(s) for s in sets]) if sets else set()
        v["summary"] = {"rounds_measured": len(rounds),
                        "hitset_identical_all_rounds": len(set(sets)) <= 1,
                        "jaccard_stability": round(len(inter) / len(union), 3) if union else 1.0,
                        "dates_identical_all_rounds": len(set(dates)) <= 1}
    save_json(STABILITY, stability)

    checkpoint("final")
    done = Counter(v["state"] for v in results.values())
    print(f"[final] rows={len(results)}/{n_total} states={dict(done)} credits={total_credits(db):.2f} "
          f"elapsed={(time.time()-started)/60:.1f}m stability_rows={len(stability)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
