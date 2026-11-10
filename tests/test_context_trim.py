"""Tests for functions/context_trim.py. Run: python tests/test_context_trim.py

Open WebUI is not needed: the two modules the filter imports from it are stubbed.
"""

import asyncio
import importlib.util
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = tempfile.mkdtemp(prefix="context_trim_test_")

# --- stub open_webui ---------------------------------------------------------
calls = []


async def fake_completion(request, form, user=None, bypass_filter=False):
    calls.append(form)
    return {"choices": [{"message": {"content": f"<think>hm</think>SUMMARY#{len(calls)}"}}]}


def _mod(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m


_mod("open_webui")
_mod("open_webui.env", DATA_DIR=TMP)
_mod("open_webui.utils")
_mod("open_webui.utils.chat", generate_chat_completion=fake_completion)
_mod("open_webui.models")
_mod(
    "open_webui.models.users",
    Users=types.SimpleNamespace(get_user_by_id=lambda i: {"id": i}),
)

spec = importlib.util.spec_from_file_location("context_trim", ROOT / "functions" / "context_trim.py")
ct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ct)


def request():
    state = types.SimpleNamespace(
        MODELS={"big": {"owned_by": "ollama"}, "tiny": {"owned_by": "ollama"}},
        config=types.SimpleNamespace(TASK_MODEL="tiny", TASK_MODEL_EXTERNAL=""),
    )
    return types.SimpleNamespace(app=types.SimpleNamespace(state=state))


def convo(turns, size=3300):
    msgs = [{"role": "system", "content": "You are helpful."}]
    for i in range(turns):
        msgs.append({"role": "user", "content": f"question {i} " + "u" * size})
        msgs.append({"role": "assistant", "content": f"answer {i} " + "a" * size})
    msgs.append({"role": "user", "content": "latest question"})
    return msgs


def run(f, msgs, chat_id="c1", req=True, events=None, **extra):
    body = {"model": "big", "messages": [dict(m) for m in msgs], **extra}

    async def emit(e):
        if events is not None:
            events.append(e)

    out = asyncio.run(
        f.inlet(
            body,
            __user__={"id": "u1"},
            __metadata__={"chat_id": chat_id},
            __request__=request() if req else None,
            __event_emitter__=emit,
        )
    )
    return out["messages"]


def new_filter(**valves):
    f = ct.Filter()
    for k, val in valves.items():
        setattr(f.valves, k, val)
    return f


def est(f, msgs):
    return sum(f._raw_tokens(m) for m in msgs)


# --- tests -------------------------------------------------------------------


def test_under_budget_untouched():
    f = new_filter(token_budget=100000)
    msgs = convo(5)
    assert run(f, msgs, "under") == msgs


def test_trims_summarizes_and_keeps_turns_whole():
    calls.clear()
    f = new_filter(token_budget=20000)
    msgs = convo(15)  # ~30k tokens
    events = []
    out = run(f, msgs, "trim", events=events)
    assert est(f, out) <= 20000 * 0.7 + 50, est(f, out)
    assert out[0]["role"] == "system" and "SUMMARY#" in out[0]["content"]
    assert "<think>" not in out[0]["content"]
    assert out[0]["content"].startswith("You are helpful.")
    assert out[1]["role"] == "user", "history must start on a user turn"
    assert out[-1]["content"] == "latest question"
    assert calls and all(c["model"] == "big" for c in calls), "the chat model summarizes by default"
    assert calls[0]["options"] == {"think": False}, "no context size is sent to the chat model"
    assert any(e["data"]["done"] for e in events)


def test_cut_point_is_stable_between_trims():
    calls.clear()
    f = new_filter(token_budget=20000)
    msgs = convo(15)
    out1 = run(f, msgs, "stable")
    n = len(calls)
    msgs = msgs + [
        {"role": "assistant", "content": "short answer"},
        {"role": "user", "content": "next"},
    ]
    out2 = run(f, msgs, "stable")
    assert len(calls) == n, "no new summary while under budget"
    assert out2[: len(out1)] == out1, "prefix must be identical so the prompt cache holds"


def test_rolling_summary_extends_previous():
    calls.clear()
    f = new_filter(token_budget=20000)
    msgs = convo(15)
    run(f, msgs, "roll")
    first = len(calls)
    msgs = msgs[:-1] + convo(8)[1:]  # grow well past the budget again
    out = run(f, msgs, "roll")
    assert len(calls) > first
    assert f"SUMMARY#{first}" in calls[first]["messages"][1]["content"], "old summary fed back in"
    assert est(f, out) <= 20000


def test_edited_history_resets_state():
    calls.clear()
    f = new_filter(token_budget=20000)
    msgs = convo(15)
    run(f, msgs, "edit")
    msgs[1] = {"role": "user", "content": "completely different first message"}
    n = len(calls)
    out = run(f, msgs, "edit")
    assert len(calls) > n, "edited prefix must be re-summarized"
    assert est(f, out) <= 20000


def test_state_survives_restart():
    calls.clear()
    msgs = convo(15)
    out1 = run(new_filter(token_budget=20000), msgs, "persist")
    n = len(calls)
    out2 = run(new_filter(token_budget=20000), msgs, "persist")
    assert out1 == out2 and len(calls) == n


def test_summary_failure_falls_back_to_dropping():
    f = new_filter(token_budget=20000)
    out = run(f, convo(15), "nosummary", req=False)
    assert est(f, out) <= 20000 * 0.7 + 50
    assert "No summary is available" in out[0]["content"]


def test_images_stripped_from_old_messages_only():
    f = new_filter(token_budget=100000, keep_images_in_last=2)
    img = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
    msgs = [
        {"role": "user", "content": [{"type": "text", "text": "old"}, img]},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": [{"type": "text", "text": "new"}, img]},
    ]
    original = [dict(m) for m in msgs]
    out = run(f, msgs, "img")
    assert ct._image_count(out[0]) == 0
    assert out[0]["content"][-1]["text"] == ct.IMAGE_PLACEHOLDER
    assert ct._image_count(out[2]) == 1
    assert msgs == original


def test_images_count_toward_budget():
    f = new_filter(token_budget=3000, keep_images_in_last=10, summarize=False)
    img = {"type": "image_url", "image_url": {"url": "x"}}
    msgs = []
    for i in range(6):
        msgs.append({"role": "user", "content": [{"type": "text", "text": f"pic {i}"}, img]})
        msgs.append({"role": "assistant", "content": "seen"})
    msgs.append({"role": "user", "content": "and now?"})
    out = run(f, msgs, "imgbudget")
    assert sum(ct._image_count(m) for m in out) <= 2


def test_oversized_last_turn_is_squeezed():
    f = new_filter(token_budget=5000, summarize=False)
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "HEAD " + "x" * 60000 + " TAIL"},
    ]
    out = run(f, msgs, "squeeze")
    assert est(f, out) <= 5000, est(f, out)
    assert out[-1]["content"].startswith("HEAD") and out[-1]["content"].endswith("TAIL")


def test_budget_auto_detects_num_ctx():
    f = new_filter()
    assert f._budget({"options": {"num_ctx": 32768}}, None) == int(32768 * 0.9) - 4096
    assert f._budget({}, {"info": {"params": {"num_ctx": 8192}}}) == int(8192 * 0.9) - 4096
    assert f._budget({}, None) == 200000


def test_budget_capped_by_reread_time():
    f = new_filter(max_reread_seconds=120, read_tokens_per_second=400)
    assert f._budget({"options": {"num_ctx": 262144}}, None) == 48000
    assert f._budget({"options": {"num_ctx": 16384}}, None) == int(16384 * 0.9) - 4096, "the smaller limit wins"
    f = new_filter(token_budget=100000, max_reread_seconds=60, read_tokens_per_second=200)
    assert f._budget({}, None) == 12000
    assert new_filter(max_reread_seconds=120)._budget({}, None) == 200000, "needs a speed to apply"


def test_summary_model_choices():
    calls.clear()
    f = new_filter(token_budget=20000, summary_model="task")
    run(f, convo(15), "taskmodel")
    assert calls and all(c["model"] == "tiny" for c in calls)
    assert calls[0]["options"] == {"num_ctx": 16384, "think": False}

    calls.clear()
    f = new_filter(token_budget=20000, summary_model="missing-model")
    run(f, convo(15), "missingmodel")
    assert calls and all(c["model"] == "big" for c in calls), "unknown model falls back to the chat model"

    calls.clear()
    f = new_filter(token_budget=20000)
    run(f, convo(15), "samemodel2", options={"num_ctx": 32768, "num_batch": 2048, "temperature": 0.3})
    assert calls and all(c["options"] == {"num_ctx": 32768, "num_batch": 2048, "think": False} for c in calls), "reuse the chat's load settings"


def test_tool_messages_never_orphaned():
    f = new_filter(token_budget=6000, summarize=False)
    msgs = []
    for i in range(10):
        msgs.append({"role": "user", "content": f"q{i} " + "u" * 1500})
        msgs.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"t{i}", "function": {"name": "f", "arguments": "{}"}}]})
        msgs.append({"role": "tool", "tool_call_id": f"t{i}", "content": "r" * 1500})
        msgs.append({"role": "assistant", "content": "done " + "a" * 1500})
    msgs.append({"role": "user", "content": "last"})
    out = run(f, msgs, "tools")
    assert out[1]["role"] == "user"
    assert len(out) < len(msgs)


def test_task_requests_skipped():
    f = new_filter(token_budget=100)
    body = {"model": "big", "messages": convo(5)}
    out = asyncio.run(f.inlet(dict(body), __metadata__={"task": "title_generation"}))
    assert out["messages"] == body["messages"]


def test_calibration_learns_from_usage():
    f = new_filter(token_budget=100000)
    msgs = convo(5)
    run(f, msgs, "calib")
    raw = f._pending["calib"][1]
    body = {"chat_id": "calib", "messages": [{"role": "assistant", "content": "x", "usage": {"prompt_tokens": int(raw * 1.5)}}]}
    asyncio.run(f.outlet(body))
    assert abs(f._calibration["big"] - 1.5) < 0.01
    # A wildly off sample (RAG injected after us, say) is ignored.
    run(f, msgs, "calib")
    body["messages"][0]["usage"]["prompt_tokens"] = int(raw * 9)
    asyncio.run(f.outlet(body))
    assert abs(f._calibration["big"] - 1.5) < 0.01


def test_huge_backlog_is_capped():
    calls.clear()
    f = new_filter(token_budget=20000)
    run(f, convo(200), "huge")  # ~400k tokens dropped at once
    assert 0 < len(calls) <= ct.MAX_SUMMARY_CHUNKS


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok    {name}")
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"FAIL  {name}: {type(e).__name__}: {e}")
    sys.exit(1 if failed else 0)
