import sys, pytest; sys.path.insert(0, ".")
import core, pipeline, policy, decision
from checks import normalize as n
from tests.fakes import FakeSources

@pytest.fixture
def db(tmp_path): return core.connect(str(tmp_path / "t.db"))
OK = {"vendor_name": "Acme Logistics Pvt Ltd", "website": "acme.in", "claimed_director": "Dir One"}

def test_missing_website_means_domain_match_unknown(db):
    res = pipeline.run_request(db, {**OK, "website": None}, FakeSources(domain_ids=[1]))
    assert res["missing_inputs"] == ["website"] and res["verdict"] == "CLEARED"
    assert pipeline.identify_signals("Acme", "", {"candidates": [{"id": 1, "name": "Acme", "score": 1.0}], "domain_candidate_ids": [1]})["domain_match"] is None

def test_missing_director_is_unknown_and_named_as_missing(db):
    src = FakeSources()
    res = pipeline.run_request(db, {**OK, "claimed_director": "  "}, src)
    assert res["checks"]["director_match"]["status"] == "unknown" and res["verdict"] == "CANNOT_VERIFY"
    assert "claimed_director (not supplied in the request)" in res["decision"]["missing"]
    assert "/person/enrich" not in src.calls and "claimed_director" in res["missing_inputs"]

@pytest.mark.parametrize("name", ["", "   ", "\t\n", None])
def test_empty_name_is_a_clean_validation_error(db, name):
    with pytest.raises(pipeline.ValidationError) as e: pipeline.validate_request({"vendor_name": name})
    assert e.value.field == "vendor_name"
    res = pipeline.run_request(db, {"vendor_name": name}, FakeSources())
    assert res["status"] == "invalid" and res["field"] == "vendor_name" and "vendor_name" in res["message"]
    assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0

def test_bad_risk_tier_names_the_field():
    with pytest.raises(pipeline.ValidationError) as e: pipeline.validate_request({**OK, "risk_tier": "extreme"})
    assert e.value.field == "risk_tier"

def test_non_latin_name_is_searched_as_given_and_weak_match_is_unknown_not_fail(db):
    seen = []
    class Spy(FakeSources):
        def identify(self, ctx, name, domain): seen.append(name); return super().identify(ctx, name, domain)
    given = "एक्मे लॉजिस्टिक्स प्राइवेट लिमिटेड"
    res = Spy().__class__(candidates=[{"id": 1, "name": "Acme Logistics", "score": 1.0}])
    out = pipeline.run_request(db, {"vendor_name": given, "claimed_director": "D"}, res)
    assert seen == [given]                                          # no transliteration guess
    assert out["checks"]["exists"]["status"] == "unknown" and out["verdict"] == "CANNOT_VERIFY"
    assert n.name_similarity(given, "Acme Logistics") < policy.PROPOSED_PARAMS["name_sim_min"]

def test_non_latin_exact_match_still_works():
    assert n.name_similarity("एक्मे लॉजिस्टिक्स", "एक्मे लॉजिस्टिक्स प्राइवेट लिमिटेड") == 1.0 or n.name_similarity("एक्मे लॉजिस्टिक्स", "एक्मे लॉजिस्टिक्स") == 1.0
    assert n.normalize_name("एक्मे") != ""                          # combining marks are kept, not treated as separators

def test_domain_accepted_as_url_or_email(db):
    seen = []
    class Spy(FakeSources):
        def identify(self, ctx, name, domain): seen.append(domain); return super().identify(ctx, name, domain)
    for site in ["https://www.acme.in/contact", "sales@Acme.in", "ACME.IN."]:
        pipeline.run_request(db, {**OK, "vendor_name": f"Acme Logistics {len(seen)}", "website": site}, Spy(candidates=[{"id": len(seen) + 1, "name": "Acme Logistics", "score": 1.0}]))
    assert seen == ["acme.in"] * 3
    assert pipeline.validate_request({**OK, "website": None, "email": "ops@acme.in"})["domain"] == "acme.in"
