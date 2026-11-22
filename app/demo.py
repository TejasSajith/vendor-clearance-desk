"""No-cost demo mode: replays recorded fixtures through the real pipeline, policy and decision code. Never live data.
Every call still goes through ctx.call (ledger) with 0 credits, on the endpoint /demo/replay, so it is clearly labelled.

Scenarios (matched on the normalised vendor name):
  Ecom Express Ltd                   identify RECORDED (tests/fixtures/identify_ecom_express.json); activity, director, adverse SYNTHETIC
  Zentrovia Cargo Solutions Pvt Ltd  identify and web search RECORDED (tests/fixtures/*zentrovia.json): no record, possible adverse reports
  Acme Logistics Pvt Ltd             SYNTHETIC: every check passes (shows the approval step)
  Slowpoke Freight Pvt Ltd           SYNTHETIC: the adverse-media source times out (shows Held for approval)
  anything else                      no record found (Can't verify)
"""
import json
from pathlib import Path
import core
from checks import adverse, normalize

FIX = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
LABEL = ("DEMO MODE: replayed fixtures, not a live check. Recorded Crustdata responses where marked, synthetic signals "
         "elsewhere. No credits spent.")
ENDPOINT = "/demo/replay"

def _load(name): return json.loads((FIX / name).read_text(encoding="utf-8"))

_GOOD_PROFILE = {"headcount_total": 420, "headcount_trend_pct": 3.0, "series_age_days": 9, "jobs_90d": 6, "traffic_present": True,
                 "status": "active", "sources": ["demo:synthetic/company/enrich"]}
_GOOD_DIRECTOR = {"found": True, "company_id_match": True, "start_date_plausible": True, "same_name_candidates": 1,
                  "discriminators_agree": True, "contradicted": False, "sources": ["demo:synthetic/person/search"]}
_CLEAN_ADVERSE = {"state": "searched", "searches_run": 2, "results_scanned": 18, "hits": [], "sources": ["demo:synthetic/web/search"]}

def _scenario(name):
    n = normalize.normalize_name(name or "")
    if n == normalize.normalize_name("Ecom Express Ltd"):
        x = _load("identify_ecom_express.json")
        return {"identify": {"candidates": x["candidates"], "status": None, "domain_candidate_ids": x.get("domain_ids")},
                "profile": _GOOD_PROFILE, "director": _GOOD_DIRECTOR, "adverse": _CLEAN_ADVERSE, "recorded": ["identify"]}
    if n == normalize.normalize_name("Zentrovia Cargo Solutions Pvt Ltd"):
        x, w = _load("identify_zentrovia.json"), _load("web_zentrovia.json")
        hits = adverse.build_hits(w["results"], w["input"], "zentroviaco.com")
        return {"identify": {"candidates": x["candidates"], "status": None, "domain_candidate_ids": None},
                "adverse": {"state": "searched", "searches_run": 2, "results_scanned": len(w["results"]), "hits": hits,
                            "sources": ["demo:recorded/web/search/live"]}, "recorded": ["identify", "adverse"]}
    if n == normalize.normalize_name("Acme Logistics Pvt Ltd"):
        return {"identify": {"candidates": [{"id": 900001, "name": "Acme Logistics Pvt Ltd", "score": 1.0, "domain": "acmelogistics.in"}],
                             "status": None, "domain_candidate_ids": [900001]},
                "profile": _GOOD_PROFILE, "director": _GOOD_DIRECTOR, "adverse": _CLEAN_ADVERSE, "recorded": []}
    if n == normalize.normalize_name("Slowpoke Freight Pvt Ltd"):
        return {"identify": {"candidates": [{"id": 900002, "name": "Slowpoke Freight Pvt Ltd", "score": 1.0, "domain": None}],
                             "status": None, "domain_candidate_ids": None},
                "profile": _GOOD_PROFILE, "director": _GOOD_DIRECTOR, "adverse": "timeout", "recorded": []}
    return {"identify": {"candidates": [], "status": None, "domain_candidate_ids": None}, "recorded": []}

_BY_CID = {5967: "Ecom Express Ltd", 900001: "Acme Logistics Pvt Ltd", 900002: "Slowpoke Freight Pvt Ltd"}

class DemoSources:
    """Stateless (safe to share across requests and across a resumed run)."""
    def _replay(self, ctx, kind, key, value):
        def fn():
            if value == "timeout": raise core.TransientError("demo: simulated timeout")
            return {"credits": 0.0, "value": value}
        return ctx.call(ENDPOINT, {"kind": kind, "key": key}, fn, credits_from=lambda o: 0.0)["value"]
    def identify(self, ctx, name, domain):
        return self._replay(ctx, "identify", normalize.normalize_name(name), _scenario(name)["identify"])
    def profile(self, ctx, cid):
        return self._replay(ctx, "profile", cid, _scenario(_BY_CID.get(cid)).get("profile") or {"sources": []})
    def director(self, ctx, cid, claimed):     # the claimed name is not used or stored in demo mode
        return self._replay(ctx, "director", cid, _scenario(_BY_CID.get(cid)).get("director") or {"found": False, "sources": []})
    def adverse(self, ctx, name, domain=""):
        dflt = {"state": "searched", "searches_run": 2, "results_scanned": 0, "hits": [], "sources": ["demo:synthetic/web/search"]}
        return self._replay(ctx, "adverse", normalize.normalize_name(name), _scenario(name).get("adverse", dflt))
