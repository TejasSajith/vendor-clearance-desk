"""Decision schema + abstain rules. Wrong answers cost more than CANNOT_VERIFY, so abstain when unsure."""
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
    """checks: dict name -> {"status": "pass"|"fail"|"unknown", "reason": str, "sources": [url], "confidence": float}
    Required checks: exists, active, director_match, adverse_media."""
    required = ["exists", "active", "director_match", "adverse_media"]
    missing = [c for c in required if checks.get(c, {}).get("status", "unknown") == "unknown"]
    low = [c for c in required if checks.get(c, {}).get("confidence", 1.0) < CONFIG["min_match_confidence"]
           and checks.get(c, {}).get("status") != "unknown"]
    fails = [c for c in required if checks.get(c, {}).get("status") == "fail"]
    reasons = [{"text": f"{c}: {checks[c]['reason']}", "sources": checks[c].get("sources", [])}
               for c in required if c in checks]
    if fails:   return Decision(REJECTED, reasons, missing)       # evidence of a problem (always with sources)
    if missing or low: return Decision(CANNOT_VERIFY, reasons, missing + [f"{c} (low match confidence)" for c in low])
    return Decision(CLEARED, reasons, [])
