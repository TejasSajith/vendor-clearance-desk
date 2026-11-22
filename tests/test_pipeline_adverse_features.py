import sys, pytest; sys.path.insert(0, ".")
import core, pipeline
from checks import adverse as A
from tests.fakes import FakeSources

@pytest.fixture
def db(tmp_path): return core.connect(str(tmp_path / "t.db"))

class FeatureSources(FakeSources):
    """Returns per-result features like the live module; the pipeline must derive the signals."""
    def __init__(self, results, headcount=400, **kw):
        super().__init__(**kw); self.results = results
        self.profile_sig = {**self.profile_sig, "headcount_total": headcount}
    def adverse(self, ctx, name, domain=None):
        feats = [A.result_features(r, name, domain or "") for r in self.results]
        return self._call(ctx, "/web/search/live", {"q": name}, {"per_search": [{"source": "web", "results": feats}, {"source": "news", "results": []}], "sources": ["crustdata:/web/search/live"]})

REQ = {"vendor_name": "Acme Logistics Pvt Ltd", "website": "acme.in", "claimed_director": "D"}
FORUM = {"title": "Acme Logistics scam, lost my parcel", "snippet": "fraud", "url": "https://www.reddit.com/r/x/1", "position": 1, "source": "web"}

def test_chatter_is_noted_not_counted_and_clean_vendor_can_be_cleared(db):
    res = pipeline.run_request(db, REQ, FeatureSources([FORUM]))
    assert res["checks"]["adverse_media"]["status"] == "pass" and res["verdict"] == "CLEARED"
    assert any("unverified chatter" in n for n in res["checks"]["adverse_media"]["notes"])

def test_reputable_report_raises_a_concern_for_a_small_firm_but_not_an_established_one(db):
    news = {"title": "Acme Logistics Pvt Ltd fraud inquiry", "snippet": "an inquiry", "url": "https://www.livemint.com/a", "position": 1, "source": "web"}
    small = pipeline.run_request(db, REQ, FeatureSources([news], headcount=50))
    assert small["checks"]["adverse_media"]["status"] == "unknown" and small["verdict"] == "CANNOT_VERIFY"
    db2 = core.connect(":memory:")
    big = pipeline.run_request(db2, REQ, FeatureSources([news], headcount=5000))
    assert big["checks"]["adverse_media"]["status"] == "pass" and any("established company" in n for n in big["checks"]["adverse_media"]["notes"])

def test_director_state_is_only_match_no_match_or_cant_verify(db):
    assert pipeline.run_request(db, REQ, FeatureSources([]))["director_state"] == "match"
    db2 = core.connect(":memory:")
    assert pipeline.run_request(db2, {**REQ, "claimed_director": None}, FeatureSources([]))["director_state"] == "can't verify"
    contradicted = {"found": True, "company_id_match": True, "start_date_plausible": True, "discriminators_agree": True, "contradicted": True, "sources": ["https://r.example/x"]}
    db3 = core.connect(":memory:")
    assert pipeline.run_request(db3, REQ, FeatureSources([], director=contradicted))["director_state"] == "no match"
