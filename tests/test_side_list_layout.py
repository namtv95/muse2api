"""Offline regression: the proxy's browser opens the side chat list as a panel whatever the account's own layout.

Run: python tests/test_side_list_layout.py [path/to/engine.py]; no account, network or Chromium.
Measured 2026-11-25: an account whose layout_state keeps side chats as a drop-down ([uid, true, false, true, false])
showed no rows, so none of its chats was deleted (4 of 4); with [uid, true, true, false, false] every one was.
"""
import importlib.util
import json
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
target = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "engine.py")
spec = importlib.util.spec_from_file_location("candidate_engine", target)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def enc(d):
    return urllib.parse.quote(json.dumps(d, separators=(",", ":")), safe="")


def test_cases():
    f = m.MuseEngine._layout_with_side_list
    closed = {"version": 2, "sideChatsPanelWidth": 240, "sideChatsByUser": [["u1", True, False, True, False]]}
    out = json.loads(urllib.parse.unquote(f(enc(closed))))
    assert out == {**closed, "sideChatsByUser": [["u1", True, True, False, False]]}, out
    opened = enc({"version": 2, "sideChatsByUser": [["u1", True, True, False, False]]})
    for name, value in (("already a panel", opened), ("no per-user entry", enc({"version": 2})),
                        ("another version", enc({"version": 3, "sideChatsByUser": [["u", True, False, True, False]]})),
                        ("another shape", enc({"version": 2, "sideChatsByUser": [["u", True]]})),
                        ("not json", "abc"), ("empty", "")):
        assert f(value) == value, (name, f(value))


if __name__ == "__main__":
    test_cases()
    print("ok test_cases")
