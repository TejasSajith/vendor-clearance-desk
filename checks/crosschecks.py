"""Cross-checks between checks (PROPOSED, D45). An adverse-media pass only means "searched, nothing found"; it says nothing if we could not identify the
vendor or show it operating. These rules can only turn an adverse `pass` into `unknown`; they never create a pass or a fail. Defaults keep today's behaviour."""
CROSS_PARAMS = {"adverse_pass_needs_exists": False,        # PROPOSED: no adverse pass unless exists passed
                "adverse_pass_needs_active": False,        # PROPOSED: no adverse pass unless active passed
                "adverse_min_results_scanned": 0}          # PROPOSED: no adverse pass unless the searches returned at least this many results

def apply(checks, adverse_signals, params=None):
    p = {**CROSS_PARAMS, **(params or {})}; a = checks.get("adverse_media")
    if not a or a["status"] != "pass": return checks
    why = None
    if p["adverse_pass_needs_exists"] and checks["exists"]["status"] != "pass": why = "the vendor was not identified (exists is not a pass)"
    elif p["adverse_pass_needs_active"] and checks["active"]["status"] != "pass": why = "the vendor was not shown to be operating (active is not a pass)"
    elif (adverse_signals or {}).get("results_scanned", 0) < p["adverse_min_results_scanned"]:
        why = f"only {(adverse_signals or {}).get('results_scanned', 0)} results were scanned (need {p['adverse_min_results_scanned']})"
    if why: checks["adverse_media"] = {**a, "status": "unknown", "reason": f"nothing found in the searches, but it cannot count as a pass: {why}", "missing": ["adverse media (searched, but no basis to call it a pass)"]}
    return checks
