"""Offline regression: every text chat opens a new thread; a fresh_preamble, when set, goes first.

Run: python tests/test_fresh_chat.py [path/to/engine.py]; no account, network or Chromium.
Before: reset_thread(for_chat=True) kept typing into the open thread while it had < 24 bubbles, so up to ~12
requests in a row shared one Muse conversation and later answers saw earlier ones (a client re-sending the same
request got different lines, a fix round got the old line back). Now: reset_thread(for_chat=False) (a new
/thread/new unless the page already is an empty one), then the preamble as its own message, then the prompt; only
the prompt's reply is returned.
"""
import importlib.util
import json
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
PRE = "Làm việc hoàn toàn fresh trong phạm vi chat này."


def make_engine(cfg):
    """A page whose assistant bubble count grows by one per message sent; each reply is 'reply to <text>'."""
    state = {"cnt": 0, "txt": "", "sent": [], "resets": []}

    def js(expr, *a, **k):
        if expr == m.MuseEngine._POLL_CHAT_JS:
            return json.dumps({"cnt": state["cnt"], "total": state["cnt"], "txt": state["txt"], "raw": state["txt"],
                               "stop": False})
        return ""

    def send(prompt):
        state["sent"].append(prompt)
        state["cnt"] += 1
        state["txt"] = "reply to " + prompt
        return "clicked"

    e = object.__new__(m.MuseEngine)
    e.cfg = cfg
    e.page = SimpleNamespace(js=js)
    e.ensure_page = lambda *a, **k: e.page
    e.reset_thread = lambda for_chat=False: state["resets"].append(for_chat)
    e._send = send
    return e, state


def test_a_new_thread_and_the_preamble_first():
    clock[0] = 0.0
    e, st = make_engine(SimpleNamespace(chat_timeout=60, fresh_chat=True, fresh_preamble=PRE))
    out = "".join(e.chat_stream({}, "translate these lines"))
    assert st["resets"] == [False], st["resets"]          # never the reuse of an open thread
    assert st["sent"] == [PRE, "translate these lines"], st["sent"]
    assert out == "reply to translate these lines", repr(out)   # the preamble's reply is not returned


def test_fresh_off_keeps_the_old_flow():
    clock[0] = 0.0
    e, st = make_engine(SimpleNamespace(chat_timeout=60, fresh_chat=False, fresh_preamble=""))
    out = "".join(e.chat_stream({}, "p"))
    assert st["resets"] == [True] and st["sent"] == ["p"] and out == "reply to p", (st, out)


def test_the_config_defaults_are_fresh():
    import config
    c = config.Config()
    # no preamble by default (measured 2026-11-25: same re-send noise and no leak without it, ~20 s faster)
    assert c.fresh_chat is True and c.fresh_preamble == "", c.fresh_preamble[:40]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
