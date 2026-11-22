import sys; sys.path.insert(0, ".")
import pytest
import decision, policy
from checks import adverse as A

def feat(title, url, snippet="", name="Stripe", domain="", **over):
    f = A.result_features({"title": title, "snippet": snippet, "url": url, "position": 1, "source": "web"}, name, domain); f.update(over); return f
def sigs(feats, name="Stripe", params=None, headcount=None, searches=4):
    return A.derive_signals([{"source": "web", "results": feats[i::searches]} for i in range(searches)] if False else [{"source": "web", "results": feats}] * 1 + [{"source": "news", "results": []}] * (searches - 1),
                            name, params, headcount)

OBIT = feat("Obituary: Maria Lopez, 84, loved gardening and her stripe cat", "https://www.legacy-obits.example/maria", "She passed away peacefully. Survived by her family. stripe")
FORUM = feat("Stripe holding my merchant funds, no response for 3 weeks", "https://www.reddit.com/r/smallbusiness/comments/x", "Stripe froze my payments and merchant funds. fraud?")
FORBES = feat("Stripe | Forbes company overview", "https://www.forbes.com/companies/stripe/", "Stripe is a payments company founded in 2010.")

def test_stripe_obituary_is_never_a_hit():
    assert OBIT["obit"] and OBIT["phrase"]
    s = sigs([OBIT]); assert s["hits"] == [] and s["excluded"]["obituary"] == 1

def test_stripe_forum_complaint_is_chatter_not_counted():
    assert FORUM["cls"] == "aggregator_or_ugc" and FORUM["industry"]          # a short name with an industry term passes the collision rule
    s = sigs([FORUM]); assert s["hits"] == [] and s["chatter"] == 1
    assert policy.evaluate({"adverse": s})["adverse_media"]["status"] == "pass"   # nothing counted, so searched-and-nothing-found (limited coverage)

def test_forum_complaint_counts_when_source_class_rule_is_off():
    s = sigs([FORUM], params={"rule_source_classes": False}); assert len(s["hits"]) == 1 and s["chatter"] == 0
    assert policy.evaluate({"adverse": s})["adverse_media"]["status"] == "unknown"

def test_stripe_forbes_overview_is_reputable_but_not_adverse():
    assert FORBES["cls"] == "news_outlet" and FORBES["severity"] == 1
    s = sigs([FORBES]); assert len(s["hits"]) == 1 and s["hits"][0]["source_class"] == "news_outlet"
    assert policy.evaluate({"adverse": s})["adverse_media"]["status"] == "pass"       # severity 1 is below the concern bar

def test_short_name_without_a_discriminator_is_not_a_hit():
    f = feat("Stripe pattern shirts review", "https://www.timesofindia.indiatimes.com/x", "striped shirts and a stripe tie scam")
    assert A.is_short_name("Stripe") and not f["domain_hit"] and not f["suffix"] and not f["industry"]
    assert sigs([f])["excluded"]["collision"] == 1 and sigs([f])["hits"] == []
    assert len(sigs([f], params={"rule_name_collision": False})["hits"]) == 1

def test_discriminators_domain_suffix_industry():
    assert feat("stripe.com outage", "https://news.example/a", "", domain="stripe.com")["domain_hit"]
    assert feat("Stripe Inc sued", "https://news.example/a")["suffix"] and feat("Stripe, Inc. sued", "https://news.example/a")["suffix"]
    assert not feat("Stripe sued", "https://news.example/a")["suffix"]
    assert feat("Stripe payments fraud", "https://news.example/a")["industry"]

def test_long_names_need_no_discriminator():
    f = feat("Acme Freight Services fraud case", "https://www.livemint.com/x", name="Acme Freight Services")
    assert not A.is_short_name("Acme Freight Services Pvt Ltd") and len(sigs([f], name="Acme Freight Services")["hits"]) == 1

def test_person_pages_are_never_hits():
    f = feat("Jane Roe - Director - Stripe | LinkedIn", "https://in.linkedin.com/in/jane-roe", "Stripe payments")
    assert f["person"] and sigs([f])["excluded"]["person_page"] == 1

@pytest.mark.parametrize("url,cls", [("https://www.sebi.gov.in/enforcement/orders/x", "regulator_or_court"), ("https://economictimes.indiatimes.com/x", "news_outlet"),
         ("https://www.scamadviser.com/check-website/x", "aggregator_or_ugc"), ("https://www.google.com/goto?url=CAES", "unknown"), ("https://blog.example.org/x", "unknown"),
         ("https://www.trustpilot.com/review/x", "aggregator_or_ugc"), ("https://news.example.org/x", "unknown")])
def test_source_classes(url, cls): assert A.classify_source(url) == cls

def test_unknown_class_counts_toward_suspicious_only_never_failed():
    f = feat("Stripe Inc fraud verdict", "https://blog.example.org/a", "12 April 2024 — Stripe Inc fined for fraud", verified=True)
    s = sigs([f]); h = s["hits"][0]
    assert h["source_class"] == "unknown" and h["discriminator"] is False and h["source_ok"] is False
    assert policy.evaluate({"adverse": s})["adverse_media"]["status"] == "unknown"          # Suspicious, never Failed

def test_reputable_resolved_dated_verified_severe_hit_can_fail():
    f = feat("Stripe Inc fined for fraud", "https://www.reuters.com/a", "12 April 2024 — Stripe Inc blacklisted after a fraud order", verified=True)
    s = sigs([f]); assert s["hits"][0]["discriminator"] and s["hits"][0]["source_ok"] and s["hits"][0]["dated"] and s["hits"][0]["severity"] == 3
    assert policy.evaluate({"adverse": s})["adverse_media"]["status"] == "fail"

def two_news(): return [feat("Stripe payments fraud probe", "https://www.reuters.com/a", "fraud inquiry"), feat("Stripe payments scam claims", "https://www.livemint.com/b", "scam claims")]

def test_established_company_needs_two_independent_reputable_sources():
    one = [two_news()[0]]
    assert policy.evaluate({"adverse": sigs(one, headcount=100)})["adverse_media"]["status"] == "unknown"          # small firm: one source is enough to raise a concern
    s = sigs(one, headcount=8000)
    assert s["hits"] == [] and s["suppressed_established"] == 1 and policy.evaluate({"adverse": s})["adverse_media"]["status"] == "pass"
    assert policy.evaluate({"adverse": sigs(two_news(), headcount=8000)})["adverse_media"]["status"] == "unknown"   # two distinct reputable hosts: still Suspicious
    same_host = [two_news()[0], feat("Stripe payments fraud again", "https://www.reuters.com/c", "fraud")]
    assert sigs(same_host, headcount=8000)["hits"] == []                                                            # not independent

def test_established_rule_never_turns_a_failed_into_a_passed():
    f = feat("Stripe Inc fined for fraud", "https://www.reuters.com/a", "12 April 2024 — Stripe Inc blacklisted after a fraud order", verified=True)
    for hc in (None, 10, 500, 10**6):
        assert policy.evaluate({"adverse": sigs([f], headcount=hc)})["adverse_media"]["status"] == "fail", hc
    # and the rule can only reduce what is raised: with it on, no setting yields more hits than with it off
    for feats in ([two_news()[0]], two_news(), [FORUM, FORBES, OBIT]):
        off = len(sigs(feats, headcount=8000, params={"established_headcount_min": 10**9})["hits"]); on = len(sigs(feats, headcount=8000)["hits"])
        assert on <= off

def test_established_threshold_is_a_parameter():
    one = [two_news()[0]]
    assert len(sigs(one, headcount=800, params={"established_headcount_min": 1000})["hits"]) == 1
    assert len(sigs(one, headcount=800, params={"established_headcount_min": 500})["hits"]) == 0

def test_no_code_relies_on_people_cxos():
    import pathlib
    for p in list(pathlib.Path("checks").glob("*.py")) + [pathlib.Path("pipeline.py"), pathlib.Path("policy.py"), pathlib.Path("decision.py")]:
        assert "cxos" not in p.read_text(), p
