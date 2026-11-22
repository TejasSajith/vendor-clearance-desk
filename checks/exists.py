"""Candidate matching for the exists check. We compute name similarity ourselves on normalised names (token-sort ratio) and ignore
Crustdata's confidence score for the choice. Pure functions, no network."""
from difflib import SequenceMatcher
from checks import normalize

def token_sort_ratio(a, b):
    ta, tb = " ".join(sorted(normalize.normalize_name(a).split())), " ".join(sorted(normalize.normalize_name(b).split()))
    return round(SequenceMatcher(None, ta, tb).ratio(), 3) if ta and tb else 0.0

def _domain_matches(c, domain, domain_ids):
    return bool(domain) and (normalize.normalize_domain(c.get("domain")) == domain or (domain_ids is not None and c["id"] in domain_ids))

def match(name, domain, candidates, domain_ids, floor):
    """candidates: [{"id","name","domain"?,...}]; domain: normalised supplied domain or ''; domain_ids: ids Identify returned for that domain (or None).
    outcome: "none" (nothing at or above the floor), "one", "tie_broken_by_domain", or "ambiguous" (still tied after the domain)."""
    above = sorted(({**c, "sim": token_sort_ratio(name, c["name"])} for c in candidates), key=lambda c: -c["sim"])
    above = [c for c in above if c["sim"] >= floor]
    if not above: return {"outcome": "none", "chosen": None, "above": [], "domain_match": None, "domain_note": None}
    chosen, outcome = None, "one"
    if len(above) == 1: chosen = above[0]
    else:
        hit = [c for c in above if _domain_matches(c, domain, domain_ids)]
        if len(hit) == 1: chosen, outcome = hit[0], "tie_broken_by_domain"
        else: return {"outcome": "ambiguous", "chosen": None, "above": above, "domain_match": None, "domain_note": None}
    dm, note = None, None
    if domain:
        if _domain_matches(chosen, domain, domain_ids): dm = True
        elif chosen.get("domain") or domain_ids is not None:
            dm = False
            note = f"domain_mismatch: supplied domain {domain} differs from the record's domain {normalize.normalize_domain(chosen.get('domain')) or '(none)'}"
    return {"outcome": outcome, "chosen": chosen, "above": above, "domain_match": dm, "domain_note": note}
