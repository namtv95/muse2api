"""Offline regression: chat replies use the model's raw markdown, not the rendered innerText.

Run: python tests/test_raw_chat_text.py [path/to/engine.py]; no account, network or Chromium.
网页把 markdown 渲染成 HTML 后 innerText 会丢 TAB 与 <Bold>..</> 这类标签；
原文在 React fiber 的 props.msg.content 上（_POLL_CHAT_JS 取出为 raw）。
"""
import importlib.util
import json
import logging
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

RAW = "1\tapple\n2\t<Bold>pear</> and <b>x</b>\n  indented <i>y</i>\n"
INNER = "1 apple\n2 pear</> and x\nindented y"


def make_engine(polls):
    """polls: list of dicts returned by _POLL_CHAT_JS in order; the last one repeats."""
    seq = list(polls)
    calls = []

    def js(expr, *a, **k):
        if expr == m.MuseEngine._POLL_CHAT_JS:
            calls.append(1)
            d = seq.pop(0) if len(seq) > 1 else seq[0]
            return json.dumps(d)
        return ""

    e = object.__new__(m.MuseEngine)
    e.cfg = SimpleNamespace(chat_timeout=60)
    e.page = SimpleNamespace(js=js)
    e.ensure_page = lambda *a, **k: e.page
    e.reset_thread = lambda *a, **k: None
    e._send = lambda prompt: "clicked"
    return e


def poll(raw, inner, stop, cnt=1):
    return {"cnt": cnt, "total": cnt, "txt": inner, "raw": raw, "stop": stop}


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())


def run(polls):
    clock[0] = 0.0
    e = make_engine(polls)
    chunks = list(e.chat_stream({}, "p"))
    return e, chunks


def test_raw_returned_byte_exact():
    base = poll(None, "", False, cnt=0)
    polls = [base, poll(RAW[:6], INNER[:7], True), poll(RAW[:20], INNER[:12], True),
             poll(RAW, INNER, True), poll(RAW, INNER, False)]
    e, chunks = run(polls)
    out = "".join(chunks)
    assert out == RAW, repr(out)
    assert "\t" in out and "<Bold>pear</>" in out and "\n  indented" in out
    # 非流式 chat() 与流式拼接结果一致
    clock[0] = 0.0
    e2 = make_engine(polls)
    assert e2.chat({}, "p") == RAW


def test_leading_space_kept():
    raw = "  lead\tx"
    _, chunks = run([poll(None, "", False, cnt=0), poll(raw, "lead x", True), poll(raw, "lead x", False)])
    assert "".join(chunks) == raw


def test_fallback_inner_text_with_single_warning():
    cap = Capture()
    m.log.addHandler(cap)
    try:
        polls = [poll(None, "", False, cnt=0), poll(None, "  " + INNER[:7], True),
                 poll(None, INNER, True), poll(None, INNER, False)]
        _, chunks = run(polls)
        assert "".join(chunks) == INNER, repr("".join(chunks))
        _, chunks2 = run(polls)
        assert "".join(chunks2) == INNER
    finally:
        m.log.removeHandler(cap)
    warns = [r for r in cap.records if "innerText" in r]
    assert len(warns) == 1, cap.records


def test_hot_tab_previous_reply_is_baseline():
    """热标签页：上一条回复（raw）作为基线，不会被当成新回复吐出。"""
    old = "old\treply"
    polls = [poll(old, "old reply", False, cnt=1), poll(old, "old reply", True, cnt=1),
             poll("new\t<b>", "new", True, cnt=2), poll("new\t<b>z</b>", "new z", False, cnt=2)]
    _, chunks = run(polls)
    assert "".join(chunks) == "new\t<b>z</b>", chunks


class TimedPage:
    """按假时钟给出 poll 结果：fn(t) -> dict。"""
    def __init__(self, fn):
        self.fn = fn

    def js(self, expr, *a, **k):
        if expr == m.MuseEngine._POLL_CHAT_JS:
            return json.dumps(self.fn(clock[0]))
        return ""


def timed_engine(fn):
    clock[0] = 0.0
    e = make_engine([poll(None, "", False, cnt=0)])
    e.page = TimedPage(fn)
    return e


def test_long_thinking_with_stop_button_waits_past_40s():
    """长提示词：模型思考 ~55s 才出首字，期间 Stop 按钮一直在（实测 request_0008）。不得 40s 判超时。"""
    def fn(t):
        if t < 1:
            return poll(None, "", False, cnt=0)
        if t < 55:   # 思考中：助手气泡已出现但为空，Stop 在
            return poll(None, "", True, cnt=0)
        if t < 57:
            return poll(RAW[:10], INNER[:8], True)
        return poll(RAW, INNER, False)
    out = "".join(timed_engine(fn).chat_stream({}, "p"))
    assert out == RAW, repr(out)


def test_no_stop_button_still_times_out_at_40s():
    """没有 Stop 按钮（消息没发出去 / 卡住）仍在约 40s 判首字超时，不拖到总超时。"""
    e = timed_engine(lambda t: poll(None, "", False, cnt=0))
    try:
        list(e.chat_stream({}, "p"))
    except m.MuseGenerationError as exc:
        assert "首字" in str(exc)
        assert 39 <= clock[0] <= 46, clock[0]
    else:
        raise AssertionError("expected first-token timeout")


def test_poll_js_reads_fiber_msg_content():
    js = m.MuseEngine._POLL_CHAT_JS
    assert "__reactFiber$" in js and "memoizedProps" in js and ".content" in js
    assert "assistant" in js and "raw:" in js


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print("ok", t.__name__)
    print(f"{len(tests)} passed")
