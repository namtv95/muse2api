"""Offline regression: after a fresh text chat's reply is read, the proxy deletes that side chat through its row menu.

Run: python tests/test_delete_chat.py [path/to/engine.py]; no account, network or Chromium.
Measured 2026-11-25: a kept side chat's text reaches the next new chat through the "Recent Chats" excerpt muse adds by
itself (a planted code was read back 2 of 2); a side chat deleted right after its reply was not (0 of 2). Deleting
(row "More thread actions" -> Delete -> confirm Delete) takes ~2.5 s. A failed delete must never fail the request.
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


def make_engine(cfg):
    state = {"cnt": 0, "txt": "", "sent": [], "deleted": 0}

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
    e.reset_thread = lambda for_chat=False: None
    e._send = send

    def delete():
        state["deleted"] += 1
        state["deleted_after"] = list(state["sent"])
        return True
    e._delete_current_thread = delete
    return e, state


def test_the_side_chat_is_deleted_after_the_reply():
    clock[0] = 0.0
    e, st = make_engine(SimpleNamespace(chat_timeout=60, fresh_chat=True, fresh_preamble="", delete_chat=True))
    out = "".join(e.chat_stream({}, "translate"))
    assert out == "reply to translate", repr(out)
    assert st["deleted"] == 1 and st["deleted_after"] == ["translate"], st


def test_the_side_chat_is_deleted_when_the_reply_fails_or_the_client_stops():
    cfg = SimpleNamespace(chat_timeout=60, fresh_chat=True, fresh_preamble="", delete_chat=True)
    clock[0] = 0.0
    e, st = make_engine(cfg)
    g = e.chat_stream({}, "p")
    next(g)
    g.close()                                     # the client went away after the first text
    assert st["deleted"] == 1, st

    def fail(prompt, timeout, stop_event=None):
        raise m.MuseGenerationError("no first token")
        yield
    e, st = make_engine(cfg)
    e._stream_reply = fail
    try:
        "".join(e.chat_stream({}, "p"))
    except m.MuseGenerationError as ex:
        assert "no first token" in str(ex)
    else:
        raise AssertionError("the failure must reach the caller")
    assert st["deleted"] == 1, st


def test_no_delete_when_off_or_when_threads_are_reused():
    for cfg in (SimpleNamespace(chat_timeout=60, fresh_chat=True, fresh_preamble="", delete_chat=False),
                SimpleNamespace(chat_timeout=60, fresh_chat=False, fresh_preamble="", delete_chat=True)):
        clock[0] = 0.0
        e, st = make_engine(cfg)
        "".join(e.chat_stream({}, "p"))
        assert st["deleted"] == 0, cfg


def fake_page(path, answers):
    """A page whose js() returns location.pathname for that query and the next answer for every other script."""
    calls = []

    def js(expr, *a, **k):
        calls.append(expr)
        if expr.strip() == "location.pathname":
            return path
        if isinstance(answers, Exception):
            raise answers
        return answers.pop(0) if answers else False
    return SimpleNamespace(js=js), calls


def test_delete_clicks_row_menu_then_confirm():
    clock[0] = 0.0
    e = object.__new__(m.MuseEngine)
    e.page, calls = fake_page("/thread/abc", [True, True, True, True, True])
    assert e._delete_current_thread() is True
    joined = "\n".join(calls)
    assert calls[-1] == m.MuseEngine._ROW_GONE_JS, calls[-1]   # done only once the row has left the list
    assert 'aria-current="page"' in joined and "More thread actions" in joined and "Delete" in joined, joined[:300]


def test_delete_never_raises_and_skips_non_threads():
    clock[0] = 0.0
    e = object.__new__(m.MuseEngine)
    e.page, _ = fake_page("/thread/abc", RuntimeError("page gone"))
    assert e._delete_current_thread() is False
    for path in ("/", "/thread/new"):
        e.page, calls = fake_page(path, [True, True, True])
        assert e._delete_current_thread() is False and len(calls) == 1, (path, calls)
    e.page = None
    assert e._delete_current_thread() is False


def test_a_closed_side_chat_list_is_opened_through_the_main_chat():
    """Measured: a page that went straight to /thread/new has the side chat list closed (0 rows); after one visit to the
    main chat the list stays open on later loads. So: no row -> open /, then the thread again, then delete."""
    clock[0] = 0.0
    nav = []
    state = {"path": "/thread/abc"}

    def js(expr, *a, **k):
        if expr.strip() == "location.pathname":
            return state["path"]
        if expr == m.MuseEngine._ROW_MENU_JS:
            return "https://muse.ai/" in nav and state["path"] == "/thread/abc"
        if expr == m.MuseEngine._SIDE_LIST_JS:
            return "https://muse.ai/" in nav
        return True

    def send(method, params=None):
        if method == "Page.navigate":
            nav.append(params["url"])
            state["path"] = params["url"].replace("https://muse.ai", "") or "/"
        return {}
    e = object.__new__(m.MuseEngine)
    e.page = SimpleNamespace(js=js, send=send)
    assert e._delete_current_thread() is True
    assert nav == ["https://muse.ai/", "https://muse.ai/thread/abc"], nav


def test_the_config_default_deletes():
    import config
    assert config.Config().delete_chat is True


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
