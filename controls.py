"""User controls: three simple dials that map to policy parameter overrides. They never touch the hard rules.

  strictness          lenient | balanced | strict
  rejection_evidence  standard | high
  freshness_days      policy | 30 | 90 | 180      (policy = the current max_series_age_days)

The table is config.json "control_presets" (PROPOSED, D38). If evaluation/presets_candidate.json exists AND contains
"approved": true (set by Tejas), its sections replace the config ones. Otherwise all three strictness levels equal the
current policy defaults, and resolve() says so in its notes (shown on screen).

Hard rules are not exposed: verdict semantics live in decision.py, and the keys below in HARD_KEYS can never be set
by a preset. Floors keep a rejection sourced (reject_min_sources >= 1) and "nothing found" meaningful (min_searches >= 1).
"""
import hashlib, json
from pathlib import Path
import core, policy

ROOT = Path(__file__).resolve().parent
CANDIDATE = ROOT / "evaluation" / "presets_candidate.json"
CONTROLS = ("strictness", "rejection_evidence", "freshness_days")
TUNABLE = {"name_sim_min", "candidate_name_sim_floor", "min_headcount", "max_decline_pct", "max_series_age_days", "min_jobs_90d",
           "active_min_signals", "tier_extra_medium", "tier_extra_high", "min_searches", "adverse_min_severity",
           "reject_min_sources", "reject_min_severity"}
HARD_KEYS = set(policy.PROPOSED_PARAMS) - TUNABLE     # reject_require_dated, deleted_is_fail, domain_mismatch_is_fail, conflict terms
FLOORS = {"reject_min_sources": 1, "min_searches": 1, "reject_min_severity": 1, "adverse_min_severity": 1}

def presets(candidate_path=None):
    """Returns (table, notes). The candidate file is used only if it says approved: true."""
    path = Path(candidate_path) if candidate_path else CANDIDATE
    table = json.loads(json.dumps(core.CONFIG.get("control_presets") or {}))
    notes = []
    if path.exists():
        try: cand = json.loads(path.read_text())
        except ValueError: cand = {}; notes.append(f"{path.name} is not valid JSON; ignored")
        if cand.get("approved") is True:
            for k in CONTROLS:
                if isinstance(cand.get(k), dict): table[k] = cand[k]
            notes.append(f"strictness presets loaded from {path.name} (approved)")
        elif cand:
            notes.append(f"{path.name} exists but is not approved; using the current policy defaults")
    if not any("approved)" in n for n in notes):
        notes.append("Strictness levels are all the current policy defaults (no approved presets yet), so lenient, balanced and strict give the same result")
    return table, notes

def options(candidate_path=None):
    table, notes = presets(candidate_path)
    d = table.get("defaults") or {}
    return {k: {"choices": [c for c in table.get(k, {})], "default": d.get(k)} for k in CONTROLS}, notes

def _clean_overrides(o, notes, where):
    out = {}
    for k, v in (o or {}).items():
        if k.startswith("_"): continue
        if k in HARD_KEYS or k not in TUNABLE:
            notes.append(f"{where}: '{k}' is not a control parameter; ignored"); continue
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            notes.append(f"{where}: '{k}' must be a number; ignored"); continue
        if k in FLOORS and v < FLOORS[k]:
            notes.append(f"{where}: '{k}' raised to its floor {FLOORS[k]}"); v = FLOORS[k]
        out[k] = v
    return out

def resolve(choices=None, candidate_path=None):
    """choices: {control: value}. Returns {"params": full parameter set, "controls": chosen values, "notes": [...], "tag": str}.
    An unknown value falls back to the default and is noted. Later controls apply on top of earlier ones."""
    table, notes = presets(candidate_path)
    d = table.get("defaults") or {}
    chosen, params = {}, dict(policy.PROPOSED_PARAMS)
    for k in CONTROLS:
        v = str((choices or {}).get(k) or d.get(k) or "")
        if v not in table.get(k, {}):
            if (choices or {}).get(k) is not None: notes.append(f"{k}: '{v}' is not an option; using {d.get(k)}")
            v = d.get(k)
        chosen[k] = v
        params.update(_clean_overrides(table.get(k, {}).get(v), notes, f"{k}={v}"))
    for k in HARD_KEYS: params[k] = policy.PROPOSED_PARAMS[k]        # belt and braces: hard rules stay as policy has them
    tag = "" if params == policy.PROPOSED_PARAMS else hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:8]
    return {"params": params, "controls": chosen, "notes": notes, "tag": tag}
