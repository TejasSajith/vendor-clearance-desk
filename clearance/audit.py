"""Append-only audit log: who approved or rejected what, when, and the evidence they were shown; every action status change
from any code path (trigger on `actions`); every model call (trigger on `calls` for /llm/generate); contests, re-checks, purges.

Append-only is enforced in the database: triggers abort any UPDATE or DELETE on audit_log, so no code path in this repo can
edit or remove a row through SQL (tests/test_audit.py). Someone with the file and a SQLite shell can still drop the triggers;
this protects against the app, not against the machine's owner.
`actor` is a staff ID or role ("analyst-7", "risk-head"), never a person's name; it is limited to 64 characters.
"""
import hashlib, json, time
import core

LLM_ENDPOINT = "/llm/generate"
NOW = "((julianday('now') - 2440587.5) * 86400.0)"
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, actor TEXT NOT NULL, event TEXT NOT NULL,
  run_id TEXT, action_key TEXT, detail TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_model_call AFTER INSERT ON calls WHEN NEW.endpoint = '{LLM_ENDPOINT}' BEGIN
  INSERT INTO audit_log(ts, actor, event, run_id, action_key, detail)
  VALUES(NEW.ts, 'model', 'model_call', NEW.run_id, NULL,
         json_object('call_id', NEW.id, 'params', NEW.params, 'status', NEW.status, 'ms', NEW.ms, 'credits', NEW.credits));
END;
CREATE TRIGGER IF NOT EXISTS audit_action_status AFTER UPDATE OF status ON actions WHEN NEW.status IS NOT OLD.status BEGIN
  INSERT INTO audit_log(ts, actor, event, run_id, action_key, detail)
  VALUES({NOW}, 'engine', 'action_' || NEW.status, NEW.run_id, NEW.key, json_object('from', OLD.status, 'to', NEW.status));
END;
CREATE TRIGGER IF NOT EXISTS audit_action_created AFTER INSERT ON actions BEGIN
  INSERT INTO audit_log(ts, actor, event, run_id, action_key, detail)
  VALUES({NOW}, 'engine', 'action_pending', NEW.run_id, NEW.key, json_object('kind', NEW.kind, 'payload', NEW.payload));
END;
"""

class AuditError(ValueError): pass

def install(db): db.executescript(SCHEMA)

def _actor(actor):
    if not isinstance(actor, str) or not actor.strip() or len(actor) > 64: raise AuditError("actor: a staff ID or role (1 to 64 characters) is required")
    return actor.strip()

def append(db, actor, event, run_id=None, action_key=None, detail=None):
    install(db)
    db.execute("INSERT INTO audit_log(ts,actor,event,run_id,action_key,detail) VALUES(?,?,?,?,?,?)",
               (time.time(), _actor(actor), event, run_id, action_key, json.dumps(detail or {}, ensure_ascii=False, sort_keys=True)))

def entries(db, run_id=None, action_key=None, limit=None):
    install(db)
    q, a = "SELECT id, ts, actor, event, run_id, action_key, detail FROM audit_log WHERE 1=1", []
    if run_id: q += " AND run_id=?"; a.append(run_id)
    if action_key: q += " AND action_key=?"; a.append(action_key)
    q += " ORDER BY id" + (f" LIMIT {int(limit)}" if limit else "")
    cols = ("id", "ts", "actor", "event", "run_id", "action_key", "detail")
    return [{**dict(zip(cols, r)), "detail": json.loads(r[6])} for r in db.execute(q, a)]

def decide_action(db, key, approve, actor, evidence_shown, executor=None):
    """A person approves or rejects a pending action. The audit row records who, when, the decision and the evidence shown
    (and its hash). Only a pending action can be decided; anything else is recorded as a refused attempt and changes nothing.
    On approval, the executor (local only) runs once through core.execute_action."""
    actor = _actor(actor)
    row = db.execute("SELECT run_id, status FROM actions WHERE key=?", (key,)).fetchone()
    if not row: raise AuditError(f"no such action: {key}")
    run_id, status = row
    shown = json.dumps(evidence_shown, ensure_ascii=False, sort_keys=True)
    detail = {"evidence_shown": evidence_shown, "evidence_sha256": hashlib.sha256(shown.encode()).hexdigest(), "status_before": status}
    if status != "pending":
        append(db, actor, "decision_refused", run_id, key, {**detail, "reason": f"action is {status}, not pending"})
        return {"key": key, "status": status, "changed": False}
    append(db, actor, "approved" if approve else "rejected", run_id, key, detail)
    core.set_approval(db, key, approve=approve)
    if approve and executor is not None: core.execute_action(db, key, executor)
    return {"key": key, "status": db.execute("SELECT status FROM actions WHERE key=?", (key,)).fetchone()[0], "changed": True}
