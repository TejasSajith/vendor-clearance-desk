"""Fake sources for pipeline tests: no network, no credits. Every call goes through ctx.call like the real modules."""
import core

class FakeSources:
    def __init__(self, candidates=None, status="active", domain_ids=None, profile=None, director=None, adverse=None,
                 cost=0.2, identify_exc=None):
        self.candidates = candidates if candidates is not None else [{"id": 1, "name": "Acme Logistics Pvt Ltd", "score": 1.0}]
        self.status, self.domain_ids, self.cost, self.identify_exc = status, domain_ids, cost, identify_exc
        self.profile_sig = profile or {"headcount_total": 400, "headcount_trend_pct": 2.0, "series_age_days": 6, "jobs_90d": 5,
                                       "traffic_present": True, "sources": ["crustdata:/company/enrich"]}
        self.director_sig = director or {"found": True, "company_id_match": True, "start_date_plausible": True,
                                         "same_name_candidates": 1, "discriminators_agree": True, "contradicted": False,
                                         "sources": ["crustdata:/person/enrich"]}
        self.adverse_sig = adverse or {"state": "searched", "searches_run": 3, "hits": [], "sources": ["crustdata:/web/search/live"]}
        self.calls = []
    def _call(self, ctx, endpoint, params, value):
        def fn():
            self.calls.append(endpoint)
            if self.identify_exc and endpoint == "/company/identify": raise self.identify_exc
            return {"credits": self.cost, "value": value}
        return ctx.call(endpoint, params, fn, credits_from=lambda o: o["credits"])["value"]
    def identify(self, ctx, name, domain):
        v = self._call(ctx, "/company/identify", {"name": name, "domain": domain},
                       {"candidates": self.candidates, "status": self.status, "domain_candidate_ids": self.domain_ids})
        return v
    def profile(self, ctx, cid): return self._call(ctx, "/company/enrich", {"id": cid}, self.profile_sig)
    def director(self, ctx, cid, claimed): return self._call(ctx, "/person/enrich", {"id": cid, "claimed": claimed}, self.director_sig)
    def adverse(self, ctx, name): return self._call(ctx, "/web/search/live", {"q": name}, self.adverse_sig)
