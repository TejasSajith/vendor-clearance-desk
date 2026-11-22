"""Executors for approved actions. LOCAL ONLY: an approved action is recorded in this database and nothing is sent anywhere.
There is no email, SMS, chat, webhook or payment code in this repo (tests/test_outbound_safety.py checks the whole tree).
Idempotent per action key (INSERT OR IGNORE), as core.execute_action and core.recover_actions require."""
import time

TABLE = "CREATE TABLE IF NOT EXISTS clearance_effects(key TEXT PRIMARY KEY, kind TEXT, note TEXT, ts REAL)"
NOTE = "recorded locally; nothing was sent to the vendor or any third party"
LOCAL_ONLY = True        # every executor factory in this module sets this on the function it returns

def install(db): db.execute(TABLE)

def local_record(db):
    install(db)
    def run(kind, payload, key):
        db.execute("INSERT OR IGNORE INTO clearance_effects VALUES(?,?,?,?)", (key, kind, NOTE, time.time()))
    run.local_only = True
    return run
