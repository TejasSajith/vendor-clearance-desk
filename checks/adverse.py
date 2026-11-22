"""Adverse-media relevance and hit building. Pure functions, no network.
A result names the target only if the FULL normalised company name appears as a phrase (whole words, in order) in the title or snippet,
or the supplied domain appears in the URL or text. First-word and substring matches do not count."""
import re
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
