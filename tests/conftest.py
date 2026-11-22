import sys, pytest
sys.path.insert(0, ".")
import core

@pytest.fixture(autouse=True)
def fast_clock(monkeypatch):
    """Tests never really sleep: a fake clock that advances when the code sleeps (throttle, retry back-off)."""
    t = {"v": 1_000_000.0}
    monkeypatch.setitem(core._clock, "now", lambda: t["v"])
    monkeypatch.setitem(core._clock, "sleep", lambda s: t.__setitem__("v", t["v"] + s))
    core._windows.clear(); core._seeded.clear()
    yield t
