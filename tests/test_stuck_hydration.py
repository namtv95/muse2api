"""Offline regression: a page stuck before hydration is loaded again instead of waited out.

Run: python tests/test_stuck_hydration.py [path/to/engine.py]; no account, network or Chromium.
Measured 2026-11-25 (3 of 3 failures): document complete, composer present, data-hatch-shell-hydration-state "server"
for the whole login_wait (60 s), then an account switch, and a 502 when the second account's page did the same. A
normal load takes ~6 s.
"""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
target = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "engine.py")
spec = importlib.util.spec_from_file_location("candidate_engine", target)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

clock = [0.0]
m.time = SimpleNamespace(time=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + s))


def run(ready_after_reloads, stuck=True, login_wait=60):
    clock[0] = 0.0
    reloads = []

    def send(method, params=None):
        assert method == "Page.navigate" and params["url"] == "https://muse.ai/thread/new", (method, params)
        reloads.append(clock[0])
        return {}
    e = object.__new__(m.MuseEngine)
    e.cfg = SimpleNamespace(login_wait=login_wait)

    def wait(page, timeout=15.0):
        if len(reloads) >= ready_after_reloads:
            clock[0] += 5
            return True
        clock[0] += timeout
        return False
    e._wait_ws_ready = wait
    page = SimpleNamespace(send=send, js=lambda expr, *a, **k: stuck)
    return e._wait_page_ready(page), reloads, clock[0]


def test_cases():
    for name, args, want_ok, want_reloads, want_time in (
            ("a normal load is not reloaded", (0,), True, 0, 5),
            ("a stuck page is reloaded and then ready", (1,), True, 1, 20),
            ("a page stuck forever still ends at login_wait", (99,), False, 3, 60),
            ("a slow page that is not stuck is never reloaded", (99, False), False, 0, 60),
            ("a short login_wait is kept", (99, True, 10), False, 0, 10)):
        ok, reloads, t = run(*args)
        assert ok is want_ok and len(reloads) == want_reloads and abs(t - want_time) < 1, (name, ok, reloads, t)


if __name__ == "__main__":
    test_cases()
    print("ok test_cases")
