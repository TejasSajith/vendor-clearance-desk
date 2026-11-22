"""Purpose-limited request schema: only the four fields the checks use are accepted. Anything else is refused, naming the field,
so no extra data (emails, phone numbers, registry IDs no check uses yet, notes) is taken in or stored.

  vendor_name       required; must contain a letter or digit in any script (used as given, no transliteration)
  website           optional; a domain or URL, reduced to the bare domain
  risk_tier         optional; low | medium | high (default low)
  claimed_director  optional; used at run time only: never stored, logged or printed (only a salted hash and the match result)
Limits are PROPOSED in ops_config.json request_limits (D53)."""
import re, unicodedata
from checks import normalize
from clearance import ops

FIELDS = ("vendor_name", "website", "risk_tier", "claimed_director")
TIERS = ("low", "medium", "high")
_DOMAIN = re.compile(r"[^\s/@:?#]+\.[^\s/@:?#.]+")

class SchemaError(ValueError):
    def __init__(self, field, message): super().__init__(f"{field}: {message}"); self.field, self.message = field, message

def _lim(k): return (ops.OPS.get("request_limits") or {}).get(k)

def _has_word_char(s): return any(unicodedata.category(ch)[0] in "LN" for ch in s)

def clean_request(req):
    if not isinstance(req, dict): raise SchemaError("request", "must be an object with vendor_name")
    extra = sorted(k for k in req if k not in FIELDS)
    if extra: raise SchemaError(extra[0], "not accepted: only " + ", ".join(FIELDS) + " are used by the checks, so nothing else is taken in")
    name = req.get("vendor_name")
    if not isinstance(name, str) or not name.strip(): raise SchemaError("vendor_name", "required: the vendor name is empty or missing")
    name = " ".join(name.split())
    if len(name) > _lim("vendor_name_max_chars"): raise SchemaError("vendor_name", f"longer than {_lim('vendor_name_max_chars')} characters")
    if not _has_word_char(name): raise SchemaError("vendor_name", "has no letters or digits")
    site = req.get("website")
    domain = ""
    if site not in (None, ""):
        if not isinstance(site, str): raise SchemaError("website", "must be text")
        if len(site) > 2000: raise SchemaError("website", "too long")
        domain = normalize.normalize_domain(site)
        if domain and (len(domain) > _lim("website_max_chars") or not _DOMAIN.fullmatch(domain)):
            raise SchemaError("website", "is not a domain or web address")
    tier = req.get("risk_tier") or "low"
    if tier not in TIERS: raise SchemaError("risk_tier", "must be low, medium or high")
    claimed = req.get("claimed_director")
    if claimed is not None and not isinstance(claimed, str): raise SchemaError("claimed_director", "must be text")
    claimed = " ".join(claimed.split()) if claimed and claimed.strip() else None
    if claimed and len(claimed) > _lim("claimed_director_max_chars"):
        raise SchemaError("claimed_director", f"longer than {_lim('claimed_director_max_chars')} characters")   # the value is never echoed
    return {"vendor_name": name, "website": domain or None, "risk_tier": tier, "claimed_director": claimed}
