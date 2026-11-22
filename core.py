"""Core: durable state, evidence ledger, cost ledger, idempotent actions, approvals.
All state lives in SQLite so a killed process resumes where it stopped."""
import hashlib, json, sqlite3, time, uuid
from pathlib import Path

CONFIG = json.loads((Path(__file__).parent / "config.json").read_text())

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, request TEXT, status TEXT, started REAL);
CREATE TABLE IF NOT EXISTS steps(run_id TEXT, name TEXT, result TEXT, PRIMARY KEY(run_id,name));
CREATE TABLE IF NOT EXISTS facts(id INTEGER PRIMARY KEY, run_id TEXT, subject TEXT, claim TEXT,
  value TEXT, source_url TEXT NOT NULL, passage TEXT NOT NULL, source_type TEXT,
  source_date TEXT, retrieved_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS calls(id INTEGER PRIMARY KEY, run_id TEXT, endpoint TEXT, params TEXT,
  status TEXT, credits REAL, ms INTEGER, ts REAL);
CREATE UNIQUE INDEX IF NOT EXISTS facts_uniq ON facts(run_id,subject,claim,source_url,passage);
CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, response TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS request_keys(key TEXT PRIMARY KEY, run_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS actions(key TEXT PRIMARY KEY, run_id TEXT, kind TEXT, payload TEXT,
  status TEXT, created REAL);  -- pending -> approved -> executing -> done | rejected
"""

class LimitExceeded(Exception): pass
class UnsourcedFact(Exception): pass
class UngroundedQuote(UnsourcedFact): pass          # passage not found in the fetched content
class SourceUnreachable(Exception): pass           # retries exhausted: hold for a person, never read as "nothing found"
class TransientError(Exception): pass              # timeout, connection error, 5xx: raise this from fn so it is retried
class RateLimited(Exception):                      # HTTP 429: raise this from fn; retry_after from x-ratelimit-reset
    def __init__(self, retry_after=None): super().__init__("rate limited"); self.retry_after = retry_after

def connect(path="clearance.db"):
    db = sqlite3.connect(path, isolation_level=None)  # autocommit; each write is durable
    db.executescript(SCHEMA)
    return db

def start_run(db, request, run_id=None):
    """Same run_id => resume. Otherwise a new run."""
    run_id = run_id or uuid.uuid4().hex[:12]
    db.execute("INSERT OR IGNORE INTO runs VALUES(?,?,?,?)", (run_id, request, "running", time.time()))
    return run_id

def claim_request(db, key, run_id):
    """Idempotency: the first run to claim a key owns it. Returns the owning run id (== run_id if we just claimed it)."""
    db.execute("INSERT OR IGNORE INTO request_keys VALUES(?,?)", (key, run_id))
    return db.execute("SELECT run_id FROM request_keys WHERE key=?", (key,)).fetchone()[0]

def set_run_status(db, run_id, status): db.execute("UPDATE runs SET status=? WHERE id=?", (status, run_id))

def run_step(db, run_id, name, fn):
    """Run fn once per (run, step). On restart a finished step returns its saved result."""
    row = db.execute("SELECT result FROM steps WHERE run_id=? AND name=?", (run_id, name)).fetchone()
    if row: return json.loads(row[0])
    result = fn()
    db.execute("INSERT OR REPLACE INTO steps VALUES(?,?,?)", (run_id, name, json.dumps(result)))
    return result

# ---------- evidence ledger ----------
def _norm(s): return " ".join(str(s).lower().split())

def quote_in_content(passage, content):
    """Quote-grounding: the passage must literally appear in the fetched content (whitespace and case ignored)."""
    return bool(passage) and _norm(passage) in _norm(content or "")

def add_fact(db, run_id, subject, claim, value, source_url, passage, source_type, retrieved_at, source_date=None, content=None):
    """A fact without a source link and exact passage is refused. No model-memory facts.
    Pass the fetched `content` to also require that the passage really appears in it.
    Re-adding the same fact after a crash is a no-op."""
    if not (source_url and passage and passage.strip() and retrieved_at):
        raise UnsourcedFact(f"refusing unsourced fact: {claim!r}")
    if content is not None and not quote_in_content(passage, content):
        raise UngroundedQuote(f"passage not found in source content: {claim!r}")
    db.execute("INSERT OR IGNORE INTO facts(run_id,subject,claim,value,source_url,passage,source_type,source_date,retrieved_at)"
               " VALUES(?,?,?,?,?,?,?,?,?)",
               (run_id, subject, claim, json.dumps(value), source_url, passage, source_type, source_date, retrieved_at))

def facts(db, run_id, subject=None):
    q, a = "SELECT subject,claim,value,source_url,passage,source_type,source_date,retrieved_at FROM facts WHERE run_id=?", [run_id]
    if subject: q += " AND subject=?"; a.append(subject)
    cols = ["subject","claim","value","source_url","passage","source_type","source_date","retrieved_at"]
    return [dict(zip(cols, r)) for r in db.execute(q, a)]

# ---------- cost ledger + limits ----------
def run_cost(db, run_id):
    return db.execute("SELECT COALESCE(SUM(credits),0) FROM calls WHERE run_id=?", (run_id,)).fetchone()[0]

def tracked_call(db, run_id, endpoint, params, fn, credits=0.0, credits_from=None):
    """Wrap every external call: enforce limits, then log cost and time."""
    started = db.execute("SELECT started FROM runs WHERE id=?", (run_id,)).fetchone()[0]
    if time.time() - started > CONFIG["max_seconds_per_run"]: raise LimitExceeded("time limit")
    if run_cost(db, run_id) + credits > CONFIG["max_cost_credits_per_run"]: raise LimitExceeded("cost limit")
    t0, status = time.time(), "ok"
    try:
        out = fn()
        if credits_from: credits = credits_from(out)   # use the cost the API response reports
        return out
    except Exception: status = "error"; raise
    finally:
        db.execute("INSERT INTO calls(run_id,endpoint,params,status,credits,ms,ts) VALUES(?,?,?,?,?,?,?)",
                   (run_id, endpoint, json.dumps(params), status, credits, int((time.time()-t0)*1000), time.time()))

# ---------- idempotent actions + approvals ----------
def propose_action(db, run_id, kind, payload):
    """Same (run, kind, payload) always gets the same key, so a retry can't create a second action."""
    key = hashlib.sha256(json.dumps([run_id, kind, payload], sort_keys=True).encode()).hexdigest()[:16]
    db.execute("INSERT OR IGNORE INTO actions VALUES(?,?,?,?,?,?)",
               (key, run_id, kind, json.dumps(payload), "pending", time.time()))
    return key

def set_approval(db, key, approve=True):
    db.execute("UPDATE actions SET status=? WHERE key=? AND status='pending'",
               ("approved" if approve else "rejected", key))

def _run_executor(db, key, executor):
    kind, payload = db.execute("SELECT kind,payload FROM actions WHERE key=?", (key,)).fetchone()
    executor(kind, json.loads(payload), key)     # executor MUST be idempotent per key (we only draft or record locally)
    db.execute("UPDATE actions SET status='done' WHERE key=? AND status='executing'", (key,))
    return True

def execute_action(db, key, executor):
    """approved -> executing (claimed, so no second worker runs it) -> done after the executor returns.
    If the process dies in between, the action stays 'executing' and recover_actions finishes it once."""
    claimed = db.execute("UPDATE actions SET status='executing' WHERE key=? AND status='approved'", (key,)).rowcount
    if claimed != 1: return False
    return _run_executor(db, key, executor)

def recover_actions(db, executor):
    """Call at start-up: finish actions a crash left in 'executing'. Returns the keys it finished."""
    keys = [r[0] for r in db.execute("SELECT key FROM actions WHERE status='executing'")]
    for k in keys: _run_executor(db, k, executor)
    return keys

def finalize(db, run_id, decision):
    """Turn a recommendation into a held action. Clearing and rejecting both need a person's approval."""
    kind = {"CLEARED": "onboard_vendor", "REJECTED": "reject_vendor"}.get(decision.verdict)
    if not kind: return None   # CANNOT_VERIFY / HOLD go to a person as-is, nothing to execute
    return propose_action(db, run_id, kind, {"verdict": decision.verdict, "reasons": decision.reasons})

# ---------- per-endpoint throttle, retry, response cache ----------
import collections
_windows = collections.defaultdict(collections.deque)
_seeded = set()
_clock = {"now": time.time, "sleep": time.sleep}   # replaceable in tests

def _group(endpoint):
    for g in ("company", "person", "job", "web"):
        if endpoint.startswith("/" + g): return g
    return "other"

def _limit(endpoint):
    lim = CONFIG["rate_limits_per_min"]
    return lim.get(endpoint, lim.get(_group(endpoint), lim["default"]))

def _seed(db, name, where, args):
    """After a restart the in-memory window is empty: rebuild it from the calls table so we do not burst."""
    if db is None or name in _seeded: return
    _seeded.add(name)
    now = _clock["now"]()
    for (ts,) in db.execute(f"SELECT ts FROM calls WHERE ts>? {where} ORDER BY ts", (now - 60, *args)):
        _windows[name].append(ts)

def throttle(endpoint, db=None):
    """Sliding 60s window: per exact endpoint (limits in config, from GET /account/endpoints) and account-wide (account_rpm)."""
    _seed(db, endpoint, "AND endpoint=?", (endpoint,)); _seed(db, "*", "", ())
    limit, acct = _limit(endpoint), CONFIG.get("account_rpm")
    while True:
        now = _clock["now"]()
        for name in (endpoint, "*"):
            w = _windows[name]
            while w and now - w[0] >= 60: w.popleft()
        e, a = _windows[endpoint], _windows["*"]
        if len(e) < limit and (not acct or len(a) < acct):
            e.append(now); a.append(now); return
        wait = max([60 - (now - e[0]) if len(e) >= limit else 0, 60 - (now - a[0]) if acct and len(a) >= acct else 0])
        _clock["sleep"](wait + 0.05)

def call_with_retry(fn, attempts=None, backoff=None):
    """Retry rate limits and transient errors; after the last attempt raise SourceUnreachable (the check reports 'unreachable')."""
    r = CONFIG.get("retry", {})
    attempts, backoff = attempts or r.get("attempts", 3), backoff or r.get("backoff_seconds", 2)
    last = None
    for i in range(attempts):
        try: return fn()
        except RateLimited as e: last = e; _clock["sleep"](e.retry_after or backoff * (i + 1))
        except TransientError as e: last = e; _clock["sleep"](backoff * (2 ** i))
    raise SourceUnreachable(f"gave up after {attempts} attempts: {last}")

def _ttl(endpoint):
    t = CONFIG.get("cache_ttl_seconds") or {}
    return t.get(endpoint, t.get(_group(endpoint), t.get("default")))

def cached_call(db, run_id, endpoint, params, fn, credits_from=None):
    """Same request is never paid for twice (also across restarts), unless it is older than the TTL (off by default).
    fn must return only successful responses and raise RateLimited / TransientError for 429 / timeout / 5xx."""
    key = hashlib.sha256(json.dumps([endpoint, params], sort_keys=True).encode()).hexdigest()
    row = db.execute("SELECT response, ts FROM cache WHERE key=?", (key,)).fetchone()
    ttl = _ttl(endpoint)
    if row and not (ttl and _clock["now"]() - row[1] > ttl): return json.loads(row[0])
    def go():
        def attempt():
            throttle(endpoint, db)
            return fn()
        return call_with_retry(attempt)
    out = tracked_call(db, run_id, endpoint, params, go, credits_from=credits_from)
    db.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?)", (key, json.dumps(out), _clock["now"]()))
    return out

def purge_cache(db, older_than_seconds=0):
    """Delete cached responses older than the given age (0 = everything). For privacy and freshness. Returns the count."""
    return db.execute("DELETE FROM cache WHERE ts<=?", (_clock["now"]() - older_than_seconds,)).rowcount
