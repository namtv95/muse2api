"""Offline regression: the by-hand Reset Muse flow confirms only what the person typed, and a dry run never confirms.

Run: python tests/test_reset_muse.py [path/to/engine.py]; no account, network or Chromium.
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
E = m.MuseEngine
clock = [0.0]
m.time = SimpleNamespace(time=lambda: clock[0], monotonic=lambda: clock[0],
                         sleep=lambda s: clock.__setitem__(0, clock[0] + s))


def run(name="Muse", dry=False, inputs=1, missing=None):
    """(result or error text, steps clicked, names typed). missing: the step whose control never appears."""
    clicked, typed, closed = [], [], []
    steps = {E._QUOTA_SETTINGS_JS: "settings", E._QUOTA_MENU_JS: "menu", E._RESET_CLICK_JS % E._RESET_TAB: "data",
             E._RESET_CLICK_JS % E._RESET_OPEN: "open", E._RESET_CLICK_JS % E._RESET_CONFIRM: "confirm"}

    def click(expr, error, timeout=8.0):
        if steps[expr] == missing or (steps[expr] == "confirm" and typed[-1:] != ["Muse"]):
            raise m.MuseGenerationError(error)
        clicked.append(steps[expr])

    def js(expr, *a, **k):
        if expr == E._RESET_TOP_JS:
            return json.dumps({"dialogs": 2, "inputs": inputs, "buttons": ["Close", "Reset (off)"]})
        if expr.startswith(E._RESET_NAME_JS.split("%s")[0]):
            typed.append(name)
            return True
        return True
    e = object.__new__(E)
    e.page = SimpleNamespace(js=js)
    e.ensure_page = lambda *a, **k: e.page
    e._quota_click = click
    e._close_page = lambda: closed.append(1)
    try:
        out = e.reset_muse({}, name=name, dry=dry)
    except m.MuseGenerationError as ex:
        out = str(ex)
    assert len(closed) == 2, closed          # the page is closed before and after, also on a failure
    return out, clicked, typed


def test_cases():
    out, clicked, typed = run()
    assert out == {"ok": True, "dry": False} and clicked == ["settings", "menu", "data", "open", "confirm"] and typed == ["Muse"]
    out, clicked, typed = run(dry=True)
    assert out["dry"] is True and "confirm" not in clicked and typed == [], (out, clicked, typed)
    out, clicked, typed = run(name="wrong")
    assert "nothing was reset" in out and "confirm" not in clicked, (out, clicked)
    out, clicked, typed = run(inputs=0)
    assert "no name box" in out and typed == [] and "confirm" not in clicked, (out, clicked, typed)
    out, clicked, typed = run(missing="data")
    assert "Data controls" in out and clicked == ["settings", "menu"], (out, clicked)


def test_the_confirm_click_skips_a_button_that_is_off():
    assert "!e.disabled" in E._RESET_CLICK_JS and "aria-disabled" in E._RESET_CLICK_JS


if __name__ == "__main__":
    for n, fn in sorted(globals().items()):
        if n.startswith("test_") and callable(fn):
            fn()
            print("ok", n)
