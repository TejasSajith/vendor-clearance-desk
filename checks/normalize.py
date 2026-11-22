"""Input normalisation for vendor requests: names, domains, and idempotency keys. Pure functions, no network."""
import hashlib, json, re, unicodedata
from difflib import SequenceMatcher

_STOP = {"pvt", "private", "ltd", "limited", "llp", "inc"}

def normalize_name(name):
    """Lowercase; drop M/s, Messrs, Pvt, Private, Ltd, Limited, LLP, Inc and punctuation; '&' becomes 'and'; collapse spaces.
    Unicode letters are kept as given (no transliteration)."""
    s = (name or "").lower().replace("&", " and ")
    s = re.sub(r"\bm\s*/\s*s\b", " ", s)
    s = re.sub(r"\bmessrs\b", " ", s)
    s = unicodedata.normalize("NFKC", s)
    s = "".join(ch if unicodedata.category(ch)[0] in "LMN" else " " for ch in s)     # keep letters, marks, digits in any script
    return " ".join(t for t in s.split() if t not in _STOP)

def normalize_domain(value):
    """Domain from a bare domain, a URL, or an email address: no scheme, www, path, port or trailing dot. '' if none."""
    s = (value or "").strip().lower()
    if not s: return ""
    if "@" in s and "//" not in s: s = s.rsplit("@", 1)[1]
    s = re.sub(r"^[a-z][a-z0-9+.-]*://", "", s)
    s = re.split(r"[/?#]", s, maxsplit=1)[0]
    s = s.rsplit("@", 1)[-1].split(":", 1)[0].rstrip(".")
    return s[4:] if s.startswith("www.") else s

def name_similarity(a, b):
    """0..1 on normalised names. Empty (e.g. nothing comparable) is 0, never a match."""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb: return 0.0
    return round(SequenceMatcher(None, na, nb).ratio(), 3)

def request_key(kind, name=None, domain=None, company_id=None, extra=""):
    """Idempotency key. After resolution: the crustdata company id plus the request kind.
    Before resolution: the normalised name plus the normalised domain."""
    basis = ["id", company_id] if company_id is not None else ["name", normalize_name(name), normalize_domain(domain)]
    if extra: basis.append(extra)           # e.g. a salted fingerprint of the claimed director: a different claim is a different question
    return hashlib.sha256(json.dumps([kind, *basis]).encode()).hexdigest()
