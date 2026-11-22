"""Adverse-media relevance and hit building. Pure functions, no network.
A result names the target only if the FULL normalised company name appears as a phrase (whole words, in order) in the title or snippet,
or the supplied domain appears in the URL or text. First-word and substring matches do not count."""
import hashlib, json, re
from pathlib import Path
from urllib.parse import urlparse
from checks import normalize

SEVERE = re.compile(r"\b(fir|blacklist\w*|default\w*|arrest\w*|insolven\w*)\b", re.I)
MILD = re.compile(r"\b(fraud|scam)\b", re.I)
DATE_PREFIX = re.compile(r"^\s*(\d{1,2}\s+\S+\s+\d{4}|\d+\s+\S+\s+(?:पहले|ago))\s+[—-]")

def _phrase_in(phrase, text_tokens):
    n = len(phrase)
    return n > 0 and any(text_tokens[i:i + n] == phrase for i in range(len(text_tokens) - n + 1))

def names_target(title, snippet, url, company_name, domain=""):
    text = f"{title or ''} {snippet or ''}"
    if _phrase_in(normalize.normalize_name(company_name).split(), normalize.normalize_name(text).split()): return True
    d = normalize.normalize_domain(domain)
    return bool(d) and re.search(rf"(?<![a-z0-9-]){re.escape(d)}(?![a-z0-9-])", f"{url or ''} {text}".lower()) is not None

def severity(text): return 3 if SEVERE.search(text) else 2 if MILD.search(text) else 1

def build_hits(results, company_name, domain=""):
    """results: Crustdata web/news results. Returns hits for the policy. `discriminator` and `source_ok` stay False: nothing here
    separates the target from a namesake or verifies the page text, so a hit can never support a rejection on its own."""
    hits = []
    for r in results or []:
        if not names_target(r.get("title"), r.get("snippet"), r.get("url"), company_name, domain): continue
        text = f"{r.get('title', '')} {r.get('snippet', '')}"
        hits.append({"dated": bool(DATE_PREFIX.match(r.get("snippet", ""))), "names_target": True, "discriminator": False, "source_ok": False,
                     "severity": severity(text), "url_host": urlparse(r.get("url", "")).hostname})
    return hits


# ---------------------------------------------------------------------------------------------------------------------
# Source classes, name-collision rules and the established-company rule. All PROPOSED. Features per search result are stored
# (never the text), so the rules can be re-run offline under other settings (evaluation/tuning.py).
# ---------------------------------------------------------------------------------------------------------------------
RULES_FILE = Path(__file__).resolve().parent.parent / "source_classes.json"
RULE_PARAMS = {"rule_source_classes": True,          # PROPOSED: only regulator_or_court / news_outlet count toward Suspicious or Failed
               "rule_name_collision": True,          # PROPOSED: short names need a discriminator
               "established_headcount_min": 500}     # PROPOSED: at or above it, Suspicious needs >= 2 independent reputable-class sources
REPUTABLE = ("regulator_or_court", "news_outlet")
_rules_cache = {}

def load_rules(path=None):
    p = str(path or RULES_FILE)
    if p not in _rules_cache: _rules_cache[p] = json.loads(Path(p).read_text(encoding="utf-8"))
    return _rules_cache[p]

def host_of(url):
    h = (urlparse(url or "").hostname or "").lower()
    return h[4:] if h.startswith("www.") else h

def classify_source(url, rules=None):
    """regulator_or_court | news_outlet | aggregator_or_ugc | unknown. A google.com redirect hides the real site, so it is unknown."""
    rules = rules or load_rules(); h = host_of(url)
    if not h or h.endswith("google.com") or h.endswith("googleusercontent.com"): return "unknown"
    def hit(suffixes): return any(h == x or h.endswith("." + x) for x in suffixes)
    cl = rules["classes"]
    if hit(cl["regulator_or_court"]["host_suffixes"]): return "regulator_or_court"
    if hit(cl["aggregator_or_ugc"]["host_suffixes"]) or any(k in h for k in cl["aggregator_or_ugc"].get("host_keywords", [])): return "aggregator_or_ugc"
    if hit(cl["news_outlet"]["host_suffixes"]): return "news_outlet"
    return "unknown"

def is_obituary(text, rules=None):
    t = (text or "").lower()
    return any(k in t for k in (rules or load_rules())["obituary_terms"])

def is_person_page(url, title, rules=None):
    """Profile pages of individuals (LinkedIn /in/, social handles, '<Name> - <Role> | LinkedIn'): never evidence about a company."""
    u = (url or "").lower().replace("https://", "").replace("http://", "").replace("www.", "")
    if any(u.startswith(p) or ("." + p) in u for p in (rules or load_rules())["person_page_url_patterns"]): return True
    t = title or ""
    return bool(re.search(r"\|\s*LinkedIn\s*$", t)) and " - " in t

def is_short_name(name): return len(normalize.normalize_name(name).split()) < 3

def _phrase_regex(name):
    toks = normalize.normalize_name(name).split()
    return r"\b" + r"[\W_]+".join(re.escape(t) for t in toks) + r"\b" if toks else None

def legal_suffix_attached(text, name, rules=None):
    rx = _phrase_regex(name)
    if not rx: return False
    sfx = "|".join(re.escape(x) for x in (rules or load_rules())["legal_suffixes"])
    return re.search(rx + r"[\s,\.]*(?:" + sfx + r")\b", (text or "").lower()) is not None

def industry_term_present(text, rules=None):
    t = (text or "").lower()
    return any(re.search(r"\b" + re.escape(k) + r"\b", t) for k in (rules or load_rules())["industry_terms"])

def result_features(r, name, domain="", rules=None):
    """Everything the rules need from one search result, without keeping its text."""
    rules = rules or load_rules()
    title, snippet, url = r.get("title") or "", r.get("snippet") or "", r.get("url") or ""
    text = f"{title} {snippet}"
    d = normalize.normalize_domain(domain)
    m = DATE_PREFIX.match(snippet)
    return {"rank": r.get("position"), "source": r.get("source"), "host": host_of(url) or None, "cls": classify_source(url, rules),
            "phrase": _phrase_in(normalize.normalize_name(name).split(), normalize.normalize_name(text).split()),
            "domain_hit": bool(d) and re.search(rf"(?<![a-z0-9-]){re.escape(d)}(?![a-z0-9-])", f"{url} {text}".lower()) is not None,
            "suffix": legal_suffix_attached(text, name, rules), "industry": industry_term_present(text, rules),
            "obit": is_obituary(text, rules), "person": is_person_page(url, title, rules), "severity": severity(text),
            "dated": bool(m), "date_text": m.group(1) if m else None, "url_id": hashlib.sha256(url.encode()).hexdigest()[:10],
            "url": url}      # live use only (a Failed must cite its URL); the stored evaluation signals drop it

def derive_signals(per_search, name, params=None, headcount=None, rules=None, sources=None):
    """Policy-ready adverse signals from stored per-result features. per_search: [{"source", "results": [features]}].
    Counting rules (each can be switched off for the sweep):
      always: obituaries and person pages are never hits; a hit needs the full name phrase or the supplied domain.
      rule_name_collision: a name under 3 tokens also needs the domain, an attached legal suffix, or an industry term.
      rule_source_classes: aggregator_or_ugc is chatter (shown, not counted); unknown counts toward Suspicious only (it is never "resolved"),
                           regulator_or_court and news_outlet can also count toward Failed.
      established_headcount_min: at or above it, a merely-suspicious flag needs >= 2 distinct reputable-class sources, otherwise it is suppressed.
                           A hit that could support a Failed is never suppressed, so this can only make a Suspicious flag harder."""
    p = {**RULE_PARAMS, **(params or {})}
    results = [f for s in per_search for f in s.get("results", [])]
    short = is_short_name(name)
    hits, chatter, excl = [], 0, {"obituary": 0, "person_page": 0, "collision": 0}
    for f in results:
        if not (f["phrase"] or f["domain_hit"]): continue
        if f["obit"]: excl["obituary"] += 1; continue
        if f["person"]: excl["person_page"] += 1; continue
        if p["rule_name_collision"] and short and not (f["domain_hit"] or f["suffix"] or f["industry"]): excl["collision"] += 1; continue
        cls = f["cls"]
        if p["rule_source_classes"] and cls == "aggregator_or_ugc": chatter += 1; continue
        reputable = cls in REPUTABLE
        resolved = bool(f["domain_hit"] or f["suffix"]) and reputable and p["rule_source_classes"]     # unknown and chatter are never "resolved"
        hits.append({"dated": f["dated"], "names_target": True, "discriminator": resolved, "source_ok": bool(f.get("verified", False)) and reputable,
                     "severity": f["severity"], "url_host": f["host"], "source_class": cls, "date_text": f["date_text"], "url_id": f["url_id"],
                     "url": f.get("url")})
    suppressed = 0
    if p["rule_source_classes"] and headcount is not None and headcount >= p["established_headcount_min"]:
        min_sev = p.get("adverse_min_severity", 2)
        independent = {h["url_host"] for h in hits if h["source_class"] in REPUTABLE and h["severity"] >= min_sev}
        if len(independent) < 2:
            can_fail = lambda h: h["dated"] and h["discriminator"] and h["source_ok"] and h["severity"] >= p.get("reject_min_severity", 3)
            kept = [h for h in hits if can_fail(h)]; suppressed = len(hits) - len(kept); hits = kept
    return {"state": "searched", "searches_run": len(per_search), "results_scanned": len(results), "hits": hits, "chatter": chatter,
            "suppressed_established": suppressed, "excluded": excl, "rules_version": (rules or load_rules())["version"],
            "sources": sources or ["crustdata:/web/search/live"]}
