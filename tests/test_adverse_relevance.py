import json, sys; sys.path.insert(0, ".")
from pathlib import Path
import core, pipeline, policy
from checks import adverse
from tests.fakes import FakeSources

WEB = json.loads((Path(__file__).parent / "fixtures" / "web_zentrovia.json").read_text())

def test_scam_checker_pages_for_lookalike_domains_are_not_hits_for_the_invented_vendor():
    assert len(WEB["results"]) == 10
    assert adverse.build_hits(WEB["results"], WEB["input"]) == []
    assert adverse.build_hits(WEB["results"], WEB["input"], "zentrovia.in") == []        # a supplied domain does not match "zentroviaco.com" either

def test_full_name_phrase_counts():
    r = {"title": "Acme Logistics fraud alert", "snippet": "customers report fraud", "url": "https://news.example/a"}
    assert adverse.names_target(r["title"], r["snippet"], r["url"], "Acme Logistics Pvt Ltd")
    assert adverse.names_target("M/S ACME LOGISTICS PRIVATE LIMITED sued", "", "", "Acme Logistics")

def test_first_word_and_substring_do_not_count():
    assert not adverse.names_target("Acme fraud", "", "", "Acme Logistics Pvt Ltd")                 # first word only
    assert not adverse.names_target("Acmelogistics scam", "", "", "Acme Logistics")                 # substring of one token
    assert not adverse.names_target("Logistics Acme", "", "", "Acme Logistics")                    # words, wrong order
    assert not adverse.names_target("zentroviaco.com scam", "", "", "Zentrovia Cargo Solutions")

def test_supplied_domain_in_url_or_text_counts_with_boundaries():
    assert adverse.names_target("Complaints", "", "https://www.acme.in/contact", "Different Name", "acme.in")
    assert adverse.names_target("See acme.in reviews", "", "", "Different Name", "https://www.Acme.in/")
    assert not adverse.names_target("bigacme.in reviews", "", "", "Different Name", "acme.in")
    assert not adverse.names_target("acme.info", "", "", "Different Name", "acme.in")

def test_hits_never_carry_a_discriminator_or_verified_source():
    hs = adverse.build_hits([{"title": "Acme Logistics blacklisted", "snippet": "10 April 2024 — x", "url": "https://n.example/a"}], "Acme Logistics")
    assert hs[0]["severity"] == 3 and hs[0]["dated"] and hs[0]["discriminator"] is False and hs[0]["source_ok"] is False

def test_invented_vendor_adverse_is_a_pass_with_limited_coverage_not_a_possible_report():
    sig = {"adverse": {"state": "searched", "searches_run": 2, "results_scanned": 10,
                       "hits": adverse.build_hits(WEB["results"], WEB["input"]), "sources": ["crustdata:/web/search/live"]}}
    assert policy.evaluate(sig)["adverse_media"]["status"] == "pass"
