"""Guards around the check sources. They sit between a source (checks/live.py, app/demo.py, test fakes) and core.cached_call,
so every call still goes through cached_call (throttle, cache, caps, retry, ledger). Nothing here changes a verdict rule:
a guard can only make a stage `unreachable` (HOLD_FOR_APPROVAL) or `not_run` (CANNOT_VERIFY), never a pass.

  daily cap        refuse a paid call once today's ledger total reaches ops max_cost_credits_per_day (raises core.LimitExceeded)
  circuit breaker  after N consecutive transient failures on one endpoint, stop calling it for the rest of this run attempt
  malformed        a body that is not JSON or is empty is a transient error (retried, never cached); a response the source
                   cannot parse makes the stage unreachable, and the unusable cache rows written in that stage are removed
  alerts           a run that hits the per-run cost or time cap or the daily cap gets one row in `alerts` and a line on stderr
  cache hits       every cache hit is logged in `cache_hits` with the credits the original call cost (for the cost report)

    sources = GuardedSources(LiveSources(), Guard(db))
    pipeline.run_request(db, req, sources)
"""
import hashlib, json, sys, time
from datetime import datetime
import core
from clearance import ops

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY, ts REAL, run_id TEXT, kind TEXT, message TEXT, UNIQUE(run_id, kind));
CREATE TABLE IF NOT EXISTS cache_hits(id INTEGER PRIMARY KEY, ts REAL, run_id TEXT, endpoint TEXT, credits_saved REAL);
"""
STAGES = ("identify", "profile", "director", "adverse")
MALFORMED = (ValueError, KeyError, IndexError, TypeError, AttributeError)

class BreakerOpen(core.SourceUnreachable):
    """The endpoint failed too often in this run attempt; it is not called again (the check is unreachable, so HOLD)."""

def install(db): db.executescript(SCHEMA)

def cache_key(db, endpoint, params, sensitive=False):
    """The key core.cached_call uses for this request (kept in step with core; tests check they agree)."""
    body = json.dumps([endpoint, params], sort_keys=True)
    return hashlib.sha256(((core.salt(db) + body) if sensitive else body).encode()).hexdigest()

def day_start(now=None):
    d = datetime.fromtimestamp(now if now is not None else time.time())
    return d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

def spent_today(db, now=None):
    return db.execute("SELECT COALESCE(SUM(credits),0) FROM calls WHERE ts>=?", (day_start(now),)).fetchone()[0]

def alert(db, run_id, kind, message, stream=None):
    """One alert per run and kind. Returns True if this call created it."""
    install(db)
    new = db.execute("INSERT OR IGNORE INTO alerts(ts,run_id,kind,message) VALUES(?,?,?,?)",
                     (time.time(), run_id, kind, message)).rowcount == 1
    if new: print(f"ALERT [{kind}] run {run_id}: {message}", file=stream or sys.stderr)
    return new

def _kind(exc):
    m = str(exc)
    return "daily_cap" if "daily" in m else "run_time_cap" if "time" in m else "run_cost_cap"

def _empty(out):
    if out is None or out == {} or out == [] or out == "": return True
    return isinstance(out, dict) and "body" in out and out["body"] in (None, "", {}, [])

class Guard:
    def __init__(self, db, daily_cap="ops", breaker_n="ops", on_call=None):
        install(db)
        self.db = db
        self.daily_cap = ops.OPS.get("max_cost_credits_per_day") if daily_cap == "ops" else daily_cap
        self.breaker_n = ops.OPS.get("breaker_consecutive_failures") if breaker_n == "ops" else breaker_n
        self.failures, self.open = {}, set()           # per endpoint, for this Guard (one run attempt)
        self.written = []                              # cache keys written by the current stage
        self.on_call = on_call                         # test and demo hook, called after each call returns
        self.n_calls = 0

    def call(self, ctx, endpoint, params, fn, credits_from=None, sensitive=False):
        db, run = ctx.db, ctx.run_id
        key = cache_key(db, endpoint, params, sensitive)
        row = db.execute("SELECT ts FROM cache WHERE key=?", (key,)).fetchone()
        ttl = core._ttl(endpoint)
        hit = row is not None and not (ttl and core._clock["now"]() - row[0] > ttl)
        if not hit:
            if endpoint in self.open: raise BreakerOpen(f"circuit open for {endpoint}: {self.breaker_n} consecutive failures in this run")
            if self.daily_cap is not None and spent_today(db) >= self.daily_cap:
                exc = core.LimitExceeded(f"daily cap: {spent_today(db):g} of {self.daily_cap:g} credits spent today")
                alert(db, run, "daily_cap", str(exc)); raise exc
        def guarded():
            try:
                out = fn()
                if _empty(out): raise core.TransientError("empty body")
            except core.TransientError: self._fail(endpoint); raise
            except ValueError as e:                    # not JSON (json.JSONDecodeError is a ValueError): retry, never cache
                self._fail(endpoint); raise core.TransientError(f"malformed body: {type(e).__name__}")
            self.failures[endpoint] = 0
            return out
        try:
            out = ctx.call(endpoint, params, guarded, credits_from=credits_from, sensitive=sensitive)
        except core.LimitExceeded as e:
            alert(db, run, _kind(e), f"stopped at cap: {e}; spent {core.run_cost(db, run):g} credits"); raise
        if hit:
            logged = {"redacted": key[:16]} if sensitive else params
            r = db.execute("SELECT credits FROM calls WHERE endpoint=? AND params=? AND status='ok' ORDER BY id LIMIT 1",
                           (endpoint, json.dumps(logged))).fetchone()
            db.execute("INSERT INTO cache_hits(ts,run_id,endpoint,credits_saved) VALUES(?,?,?,?)",
                       (time.time(), run, endpoint, r[0] if r else None))
        else:
            self.written.append(key)
        self.n_calls += 1
        if self.on_call: self.on_call(self, endpoint, hit)
        return out

    def _fail(self, endpoint):
        self.failures[endpoint] = self.failures.get(endpoint, 0) + 1
        if self.breaker_n and self.failures[endpoint] >= self.breaker_n:
            self.open.add(endpoint)
            raise BreakerOpen(f"circuit open for {endpoint}: {self.failures[endpoint]} consecutive failures in this run")

class GuardCtx:
    """What a source sees as ctx: same .db, .run_id and .call as pipeline.Ctx, with the guard in front."""
    def __init__(self, ctx, guard): self._ctx, self._g, self.db, self.run_id = ctx, guard, ctx.db, ctx.run_id
    def call(self, endpoint, params, fn, credits_from=None, sensitive=False):
        return self._g.call(self._ctx, endpoint, params, fn, credits_from=credits_from, sensitive=sensitive)

class GuardedSources:
    """Wraps a sources object. A response the source cannot parse makes the stage unreachable (HOLD), never 'nothing found'."""
    def __init__(self, inner, guard): self.inner, self.guard = inner, guard
    def __getattr__(self, name):
        attr = getattr(self.inner, name)
        if name not in STAGES or not callable(attr): return attr
        def stage(ctx, *args, **kw):
            self.guard.written = []
            try:
                return attr(GuardCtx(ctx, self.guard), *args, **kw)
            except core.LimitExceeded: raise
            except core.SourceUnreachable: raise
            except core.TransientError: raise
            except MALFORMED as e:
                for k in self.guard.written: ctx.db.execute("DELETE FROM cache WHERE key=?", (k,))   # unusable: do not reuse on resume
                raise core.SourceUnreachable(f"malformed response in {name}: {type(e).__name__}")
        return stage
