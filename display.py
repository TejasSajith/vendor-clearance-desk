"""Display labels: internal states to plain English. DISPLAY ONLY: nothing here changes a check or a verdict.
Inputs are the dicts the pipeline returns; outputs are new dicts (inputs are never modified).

Per check:  pass -> Passed · fail -> Failed · a sourced concern below the rejection bar, or a source conflict -> Suspicious
            unknown / not_run -> Can't verify (always with what is missing) · unreachable -> Couldn't reach the source
Overall:    CLEARED -> Cleared · REJECTED -> Rejected (awaiting your approval) · CANNOT_VERIFY -> Can't verify
            HOLD_FOR_APPROVAL -> Held for approval
"""
PASSED, FAILED, SUSPICIOUS, CANT_VERIFY, UNREACHABLE = "Passed", "Failed", "Suspicious", "Can't verify", "Couldn't reach the source"

OVERALL = {"CLEARED": "Cleared", "REJECTED": "Rejected (awaiting your approval)",
           "CANNOT_VERIFY": "Can't verify", "HOLD_FOR_APPROVAL": "Held for approval"}

CHECK_NAMES = {"exists": "Company exists", "active": "Company is active", "director_match": "Claimed director",
               "adverse_media": "Adverse media"}

def overall_label(verdict):
    return OVERALL.get(verdict, "Can't verify")      # an unknown verdict is never shown as a clean result

def _is_concern(name, c):
    """A sourced concern below the rejection bar: the policy found possible adverse reports but not enough to reject,
    or two sources conflict. Both stay 'unknown' in the engine; the label only makes them visible."""
    if c.get("conflict"): return True
    return name == "adverse_media" and "possible adverse report" in (c.get("reason") or "") and bool(c.get("sources"))

def _missing_for(name, c, decision_missing):
    m = list(c.get("missing") or [])
    m += [x for x in decision_missing or [] if x.startswith(name + " ") and x not in m]
    if not m:
        r = c.get("reason") or ""
        m = [f"{CHECK_NAMES.get(name, name)}: {r}" if r else f"{CHECK_NAMES.get(name, name)}: no evidence either way"]
    return m

def check_label(name, c, decision_missing=None):
    st = (c or {}).get("status", "unknown")
    if st == "pass": label = PASSED
    elif st == "fail": label = FAILED
    elif st == "unreachable": label = UNREACHABLE
    elif _is_concern(name, c): label = SUSPICIOUS
    else: label = CANT_VERIFY                   # unknown, not_run, anything else
    out = {"check": name, "title": CHECK_NAMES.get(name, name), "label": label, "status": st,
           "reason": c.get("reason", ""), "sources": list(c.get("sources") or [])}
    if label in (CANT_VERIFY, SUSPICIOUS, UNREACHABLE): out["missing"] = _missing_for(name, c, decision_missing)
    return out

def display_result(result):
    """Plain-English view of a pipeline result. Returns {"overall", "verdict", "checks": [...], "missing": [...]}."""
    d = result.get("decision") or {}
    verdict = result.get("verdict") or d.get("verdict")
    checks = result.get("checks") or {}
    return {"verdict": verdict, "overall": overall_label(verdict) if verdict else None,
            "checks": [check_label(n, checks[n], d.get("missing")) for n in CHECK_NAMES if n in checks],
            "missing": list(d.get("missing") or [])}
