"""Decision schema (verdicts are RECOMMENDATIONS; clearing or rejecting waits for a person) + abstain rules. Wrong answers cost more than CANNOT_VERIFY, so abstain when unsure."""
from dataclasses import dataclass, field, asdict
from core import CONFIG

CLEARED, REJECTED, CANNOT_VERIFY, HOLD = "CLEARED", "REJECTED", "CANNOT_VERIFY", "HOLD_FOR_APPROVAL"

@dataclass
class Decision:
    verdict: str
    reasons: list = field(default_factory=list)   # [{"text":..., "fact_ids"/"sources":[urls]}]
    missing: list = field(default_factory=list)   # what we couldn't verify
    cost_credits: float = 0.0
    def to_dict(self): return asdict(self)

def decide(checks):
    # A source that timed out is not an answer: hold for retry or a person, never read as "clean".
    unreachable = [c for c, v in checks.items() if v.get("status") == "unreachable"]
    if unreachable:
        return Decision(HOLD, [{"text": f"{c}: source unreachable", "sources": []} for c in unreachable],
                        [f"{c} (source unreachable, retry or person)" for c in unreachable])
    return _decide(checks)

def _decide(checks):
    """checks: dict name -> {"status": "pass"|"fail"|"unknown", "reason": str, "sources": [url], "confidence": float}
    Required checks: exists, active, director_match, adverse_media."""
    required = ["exists", "active", "director_match", "adverse_media"]
    missing = [c for c in required if checks.get(c, {}).get("status", "unknown") == "unknown"]
    extra = [m for c in required for m in checks.get(c, {}).get("missing", []) if checks.get(c, {}).get("status", "unknown") == "unknown"]
    low = [c for c in required if checks.get(c, {}).get("confidence", 1.0) < CONFIG["min_match_confidence"]
           and checks.get(c, {}).get("status") != "unknown"]
    fails = [c for c in required if checks.get(c, {}).get("status") == "fail"]
    reasons = [{"text": f"{c}: {checks[c]['reason']}", "sources": checks[c].get("sources", [])}
               for c in required if c in checks]
    if fails:   return Decision(REJECTED, reasons, missing)       # evidence of a problem (always with sources)
    if missing or low: return Decision(CANNOT_VERIFY, reasons, missing + extra + [f"{c} (low match confidence)" for c in low])
    return Decision(CLEARED, reasons, [])
