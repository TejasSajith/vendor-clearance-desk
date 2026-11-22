"""Build evaluation/cases_real.json from the Crustdata probe (probe/raw/, probe/sample.json).

Signal extraction only. It does NOT choose labels: "expected" stays empty for Tejas, and "proposed_expected" is
an agent suggestion written by hand in PROPOSED below. No person names, profile URLs or snippet text are written:
companies get pseudonymous ids, and adverse hits keep only flags and the URL host.
    python evaluation/build_real_cases.py            # reads probe/raw (gitignored), writes cases_real.json
"""
import json, re, sys
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
AS_OF = date(2026, 11, 22)          # probe date; keeps the output deterministic
TREND_DAYS = 180
SEVERE = re.compile(r"\b(fir|blacklist\w*|default\w*|arrest\w*|insolven\w*|fraudster)\b", re.I)
MILD = re.compile(r"\b(fraud|scam)\b", re.I)
DATE_PREFIX = re.compile(r"^\s*(\d{1,2}\s+\S+\s+\d{4}|\d+\s+\S+\s+(?:पहले|ago))\s+[—-]")

def _norm(s): return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()
def name_similarity(a, b): return round(SequenceMatcher(None, _norm(a), _norm(b)).ratio(), 3)
def token(name): return _norm(name).split()[0] if _norm(name) else ""

def identify_signals(input_name, input_domain, by_name, by_domain, status):
    """by_name / by_domain: the raw /company/identify responses (top-level list, first entry)."""
    m = (by_name[0]["matches"] if by_name else [])
    if not m: return {"found": False, "status": None, "name_similarity": 0.0, "top_ties": 0, "domain_match": None, "sources": ["crustdata:/company/identify"]}
    top = m[0]["confidence_score"]
    chosen = m[0]["company_data"]["basic_info"]
    dm = None
    if input_domain and by_domain:
        dmatch = by_domain[0]["matches"]
        dm = bool(dmatch) and dmatch[0]["company_data"]["basic_info"]["crustdata_company_id"] == chosen["crustdata_company_id"]
    return {"found": True, "status": status, "name_similarity": name_similarity(input_name, chosen.get("name")),
            "top_ties": sum(1 for x in m if x["confidence_score"] == top), "domain_match": dm,
            "sources": ["crustdata:/company/identify"]}

def headcount_trend(ts, days=TREND_DAYS):
    """Percent change from the point nearest `days` before the newest point to the newest point."""
    pts = sorted((date.fromisoformat(p["date"]), p["employee_count"]) for p in (ts or []) if p.get("employee_count"))
    if len(pts) < 2: return None
    last_d, last_v = pts[-1]
    older = [p for p in pts if (last_d - p[0]).days >= days]
    if not older: return None
    base = older[-1][1]
    return round((last_v - base) / base * 100, 1) if base else None

def series_age_days(ts, as_of=AS_OF):
    ds = [date.fromisoformat(p["date"]) for p in (ts or []) if p.get("date")]
    return (as_of - max(ds)).days if ds else None

def profile_signals(cd, jobs90):
    h = cd.get("headcount") or {}; ts = h.get("timeseries") or []
    wt = (cd.get("web_traffic") or {}).get("domain_traffic") or {}
    return {"headcount_total": h.get("total"), "headcount_trend_pct": headcount_trend(ts),
            "series_age_days": series_age_days(ts), "jobs_90d": jobs90,
            "traffic_present": any(v.get("monthly_visitors") for v in wt.values()),
            "sources": ["crustdata:/company/enrich", "crustdata:/job/search"]}

def director_signals(person_data, company_id, company_name, same_name=None, as_of=AS_OF):
    if not person_data:
        return {"found": False, "probed": False, "company_id_match": False, "start_date_plausible": False,
                "same_name_candidates": None, "discriminators_agree": False, "contradicted": False, "sources": []}
    cur = (person_data.get("experience") or {}).get("employment_details", {}).get("current") or []
    role = next((r for r in cur if r.get("crustdata_company_id") == company_id), None)
    start = None
    if role and role.get("start_date"): start = datetime.fromisoformat(role["start_date"]).date()
    headline = (person_data.get("basic_profile") or {}).get("headline") or ""
    return {"found": role is not None, "probed": True, "company_id_match": role is not None,
            "start_date_plausible": bool(start and date(1950, 1, 1) <= start <= as_of),
            "same_name_candidates": same_name,
            "discriminators_agree": token(company_name) in _norm(headline),   # headline names this company
            "contradicted": False,                                             # no dated record contradicts, in any case
            "sources": ["crustdata:/person/enrich"]}

def hit_from_result(res, company_name):
    text = f"{res.get('title','')} {res.get('snippet','')}"
    sev = 3 if SEVERE.search(text) else 2 if MILD.search(text) else 1
    return {"dated": bool(DATE_PREFIX.match(res.get("snippet", ""))), "names_target": token(company_name) in _norm(text),
            "discriminator": False,     # nothing here separates the target from namesakes
            "source_ok": False,         # page text was not retrieved and quote-checked
            "severity": sev, "url_host": urlparse(res.get("url", "")).hostname}

def adverse_signals(search_responses, company_name):
    if not search_responses: return {"state": "searched", "searches_run": 0, "hits": [], "sources": []}
    hits = [hit_from_result(r, company_name) for s in search_responses for r in (s.get("results") or [])]
    hits = [h for h in hits if h["names_target"]]
    return {"state": "searched", "searches_run": len(search_responses), "hits": hits, "sources": ["crustdata:/web/search/live"]}

# Hand-written suggestions for Tejas to confirm or overturn. NOT labels; "expected" stays empty.
PROPOSED = {
 5798: ("CANNOT_VERIFY", "large, strong activity and director data, but only 1 adverse search ran and its hits are undated complaints; no registry record"),
 5967: ("CANNOT_VERIFY", "exists and active, but the director's headline names another firm while a 2015 role is still current"),
 2037562: ("CANNOT_VERIFY", "two records tie at 1.0 for the name and Crustdata has no domain to settle it"),
 8276: ("CANNOT_VERIFY", "only 1 adverse search (results were namesakes); exists and active signals are fine; no registry record"),
 1552: ("CANNOT_VERIFY", "no director data and no adverse search were run for this company"),
 20487: ("CANNOT_VERIFY", "no adverse search was run; exists, active and director signals are fine"),
 6100573: ("CANNOT_VERIFY", "small firm, one activity signal at most; no director or adverse data collected"),
 3917119: ("CANNOT_VERIFY", "small firm; director headline does not name the company; only 1 adverse search with an unrelated result"),
 13006146: ("CANNOT_VERIFY", "lookalike of a larger company: 4 staff, no domain; real status needs registry"),
 11584: ("CANNOT_VERIFY", "Crustdata marks it deleted and the name and domain resolve to other companies; needs registry confirmation"),
}

def build(raw=ROOT / "probe" / "raw", sample=ROOT / "probe" / "sample.json"):
    load = lambda n: json.loads((raw / n).read_text()) if (raw / n).exists() else None
    adverse_tag = {5798: "delhivery", 5967: "ecomexpress", 2037562: "dtdc", 8276: "everestfleet", 3917119: "lorrycare"}
    cases = []
    for i, c in enumerate(json.loads(sample.read_text()), 1):
        k = c["id"]
        enrich = load(f"step2_enrich_{k}.json")[0]["matches"][0]["company_data"]
        pdata = load(f"step4_person_enrich_{k}.json")
        pdata = pdata[0]["matches"][0]["person_data"] if pdata and pdata[0]["matches"] else None
        searches = [x for x in [load(f"step5_search_{adverse_tag[k]}.json") if k in adverse_tag else None] if x]
        if k == 2037562 and load("step5_extra_news_dtdc.json"): searches.append(load("step5_extra_news_dtdc.json"))
        jobs = load(f"step3_jobs90_{k}.json")
        exp, basis = PROPOSED[k]
        cases.append({
            "id": f"real_{i:02d}_{c['bucket'].split()[0]}", "crustdata_company_id": k,
            "expected": "", "proposed_expected": exp, "basis": basis, "risk_tier": "low", "synthetic": False,
            "signals": {
                "identify": identify_signals(c["name"], c["domain"], load(f"step2_identify_name_{k}.json"),
                                             load(f"step2_identify_domain_{k}.json"), (enrich.get("basic_info") or {}).get("status")),
                "profile": profile_signals(enrich, (jobs or {}).get("total_count")),
                "director": director_signals(pdata, k, c["name"], same_name=372 if k == 3917119 else None),
                "adverse": adverse_signals(searches, c["name"]),
            }})
    return cases

if __name__ == "__main__":
    out = ROOT / "evaluation" / "cases_real.json"
    out.write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {out} ({len(build())} cases)")
