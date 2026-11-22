"""Policy: turns raw SIGNALS (collected from live data) into check results, using PARAMETERS.

All parameter values below are PROPOSED defaults. Tejas decides the final values (see DECISIONS.md).
Agents must not change a default without a DECIDED entry. Test new values in report-only mode first:
    python evaluation/run_eval.py --compare candidate.json

Signals (produced by the check modules from Crustdata / registry / news data):
  identify: found, status ("active"|"deleted"|None), name_similarity 0..1, top_ties (#candidates tied at top score),
            domain_match (True|False|None), sources[]
  profile:  headcount_total, headcount_trend_pct, series_age_days, jobs_90d, traffic_present, sources[]
  director: found, company_id_match, start_date_plausible, discriminators_agree, contradicted, sources[]
  adverse:  state ("searched"|"unreachable"), searches_run, hits[{dated,names_target,discriminator,source_ok,severity,url}], sources[]
Rules: a rejection (fail) needs sources, otherwise it is only "unknown". Missing data is never a fail.
"""
import json
from pathlib import Path

PROPOSED_PARAMS = {
    "name_sim_min": 0.90,            # exists: minimum name similarity to accept the match
    "domain_mismatch_is_fail": False,  # exists: input domain resolves to another company -> fail (True) or unknown (False)
    "deleted_is_fail": False,        # exists: Crustdata status=deleted -> fail (True) or unknown (False)
    "min_headcount": 5,              # active
    "max_decline_pct": 30.0,         # active: headcount may not fall by more than this over the trend window
    "max_series_age_days": 60,       # active: newest headcount point must be this recent
    "min_jobs_90d": 1,               # active: postings in last 90 days count as a signal
    "active_min_signals": 2,         # active: positive signals needed among headcount, jobs, traffic
    "tier_extra_medium": 0,          # extra signals required for medium-risk vendors
    "tier_extra_high": 1,            # extra signals required for high-risk vendors
    "min_searches": 2,               # adverse: searches that must have run before "nothing found" counts
    "adverse_min_severity": 2,       # adverse: 0 none .. 3 severe; hits below this are ignored
    "reject_min_sources": 1,         # PROPOSED: a rejection needs at least this many distinct sources
    "reject_require_dated": True,    # PROPOSED: every hit behind a rejection must carry a date
    "reject_min_severity": 3,        # PROPOSED: a rejection needs a hit at least this severe (0 none .. 3 severe)
}

def load_params(path=None):
    p = dict(PROPOSED_PARAMS)
    if path:
        p.update({k: v for k, v in json.loads(Path(path).read_text()).items() if not k.startswith("_")})
    return p

def _r(status, reason, sources=None):
    return {"status": status, "reason": reason, "sources": list(sources or [])}

def _fail(reason, sources):
    return _r("fail", reason, sources) if sources else _r("unknown", reason + " (no source, so it cannot support a rejection)")

def _exists(s, p):
    i = s.get("identify") or {}
    src = i.get("sources", [])
    if not i.get("found"):
        r = _r("unknown", "No record found. The vendor may be too new or too small for the data source", src)
        r["missing"] = ["independent registry evidence (CIN/GSTIN/incorporation certificate)"]   # never a sourced fail
        return r
    if i.get("status") == "deleted":
        return _fail("company profile marked deleted", src) if p["deleted_is_fail"] else _r("unknown", "profile marked deleted; needs registry confirmation", src)
    if i.get("top_ties", 1) > 1 and i.get("domain_match") is not True:
        return _r("unknown", "several records tie for this name and the domain does not settle it", src)
    if i.get("name_similarity", 0) < p["name_sim_min"]:
        return _r("unknown", "name match below threshold", src)
    if i.get("domain_match") is False:
        return _fail("input domain belongs to a different company", src) if p["domain_mismatch_is_fail"] else _r("unknown", "input domain belongs to a different company", src)
    return _r("pass", "single matching record", src)

def _active(s, p, tier):
    pr = s.get("profile") or {}
    src = pr.get("sources", [])
    hc, jobs, traffic = pr.get("headcount_total"), pr.get("jobs_90d"), pr.get("traffic_present")
    if hc is None and jobs is None and traffic is None: return _r("unknown", "no activity data", src)
    pos = []
    trend, age = pr.get("headcount_trend_pct"), pr.get("series_age_days")
    if hc is not None and hc >= p["min_headcount"] and trend is not None and trend >= -p["max_decline_pct"] \
            and age is not None and age <= p["max_series_age_days"]:
        pos.append("headcount")
    if (jobs or 0) >= p["min_jobs_90d"]: pos.append("jobs")
    if traffic: pos.append("traffic")
    need = p["active_min_signals"] + p.get({"medium": "tier_extra_medium", "high": "tier_extra_high"}.get(tier, ""), 0)
    if len(pos) >= need: return _r("pass", f"{len(pos)} activity signals: {', '.join(pos)}", src)
    return _r("unknown", f"only {len(pos)} of {need} activity signals", src)

def _director(s, p):
    d = s.get("director") or {}
    src = d.get("sources", [])
    if d.get("contradicted"): return _fail("claimed director contradicted by a dated record", src)
    if not d.get("found"): return _r("unknown", "claimed director not found at this company", src)
    if d.get("company_id_match") and d.get("start_date_plausible") and d.get("discriminators_agree"):
        return _r("pass", "listed at this company per profile data (not a director of record)", src)
    return _r("unknown", "person found but identity or tenure not settled", src)

def _gaps(h, p):
    """What a hit still lacks before it may support a rejection."""
    g = []
    if p["reject_require_dated"] and not h.get("dated"): g.append("a date")
    if not h.get("discriminator"): g.append("a match to the target beyond the name (namesakes possible)")
    if not h.get("source_ok"): g.append("a verified source page")
    if h.get("severity", 0) < p["reject_min_severity"]: g.append(f"severity >= {p['reject_min_severity']}")
    return g

def _adverse(s, p):
    a = s.get("adverse") or {}
    src = a.get("sources", [])
    if a.get("state") == "unreachable": return _r("unreachable", "a source timed out", src)
    relevant = [h for h in a.get("hits", []) if h.get("names_target") and h.get("severity", 0) >= p["adverse_min_severity"]]
    confirmed = [h for h in relevant if not _gaps(h, p)]
    urls = sorted({h["url"] for h in confirmed if h.get("url")})
    if confirmed and len(urls) >= p["reject_min_sources"]:
        return _r("fail", "adverse report naming the target: dated, resolved and sourced" if p["reject_require_dated"] else "adverse report naming the target", urls)
    if relevant:
        missing = sorted({x for h in relevant for x in _gaps(h, p)})
        if confirmed: missing.append(f"{p['reject_min_sources']} distinct sources (have {len(urls)})")
        n = len(relevant)
        return _r("unknown", f"{n} possible adverse report{'s' if n != 1 else ''}, not enough to reject; rejection needs a dated, resolved report: missing "
                  + "; ".join(missing), src)
    if a.get("searches_run", 0) < p["min_searches"]: return _r("unknown", "too few searches run", src)
    return _r("pass", "searched, no relevant adverse report", src)

def evaluate(signals, params=None, risk_tier="low"):
    p = params or PROPOSED_PARAMS
    return {"exists": _exists(signals, p), "active": _active(signals, p, risk_tier),
            "director_match": _director(signals, p), "adverse_media": _adverse(signals, p)}
