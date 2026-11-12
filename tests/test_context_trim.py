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
    assert f._budget({"options": {"num_ctx": 32768}}, None) == int(32768 * 0.9) - 4096 - 32768 // 20
    assert f._budget({}, {"info": {"params": {"num_ctx": 8192}}}) == int(8192 * 0.9) - 4096 - 8192 // 20
    assert f._budget({"options": {"num_ctx": 131072}}, None) == int(131072 * 0.9) - 4096 - 6000, "room for tool definitions"
    assert f._budget({}, None) == 200000


def test_budget_capped_by_reread_time():
    f = new_filter(max_reread_seconds=120, read_tokens_per_second=400)
    assert f._budget({"options": {"num_ctx": 262144}}, None) == 48000
    assert f._budget({"options": {"num_ctx": 16384}}, None) == int(16384 * 0.9) - 4096 - 16384 // 20, "the smaller limit wins"
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
    body = {"chat_id": "calib", "messages": [{"role": "assistant", "content": "x", "usage": {"prompt_tokens": int(raw * 1.3)}}]}
    asyncio.run(f.outlet(body))
    assert abs(f._calibration["big"] - 1.3) < 0.01
    # A wildly off sample (RAG injected after us, say) is ignored.
    run(f, msgs, "calib")
    body["messages"][0]["usage"]["prompt_tokens"] = int(raw * 9)
    asyncio.run(f.outlet(body))
    assert abs(f._calibration["big"] - 1.3) < 0.01
    # Tool specs and skill lists added after the filter are a fixed cost; a sample they
    # inflate must not make the whole history look twice its size.
    run(f, msgs, "calib")
    body["messages"][0]["usage"]["prompt_tokens"] = int(raw * 1.9)
    asyncio.run(f.outlet(body))
    assert abs(f._calibration["big"] - 1.3) < 0.01


def test_huge_backlog_is_capped():
    calls.clear()
    f = new_filter(token_budget=20000)
    run(f, convo(200), "huge")  # ~400k tokens dropped at once
    assert 0 < len(calls) <= ct.MAX_SUMMARY_CHUNKS


def agent_chat(turns, result_size=33000):
    """A chat where every turn calls a tool that returns about 10k tokens."""
    msgs = [{"role": "system", "content": "You are helpful."}]
    for i in range(turns):
        msgs.append({"role": "user", "content": f"task {i}: look up item {i}"})
        msgs.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"c{i}", "function": {"name": "fetch_page", "arguments": f'{{"url": "https://example.org/{i}"}}'}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "name": "fetch_page", "content": f"PAGE {i} START " + "x" * result_size + f" PAGE {i} END"})
        msgs.append({"role": "assistant", "content": f"Item {i} costs {i * 7} credits."})
    msgs.append({"role": "user", "content": "and now?"})
    return msgs


def test_tool_results_are_shortened_before_any_turn_is_dropped():
    calls.clear()
    events = []
    f = new_filter(token_budget=60000, max_tool_result_tokens=0)
    msgs = agent_chat(8)  # ~80k tokens, nearly all of it tool output
    out = run(f, msgs, "agent", events=events)
    assert not calls, "no summary needed: the conversation fits once old tool output is shortened"
    assert len(out) == len(msgs), "every turn is still there"
    assert [m["content"] for m in out if m["role"] != "tool"] == [m["content"] for m in msgs if m["role"] != "tool"]
    tools = [m for m in out if m["role"] == "tool"]
    assert all("removed to save context" in t["content"] for t in tools[:-3])
    assert all("removed to save context" not in t["content"] for t in tools[-3:]), "the newest results stay whole"
    assert tools[0]["content"].startswith("PAGE 0 START") and tools[0]["content"].endswith("PAGE 0 END")
    assert tools[0]["tool_call_id"] == "c0" and len(tools[0]["content"]) < 1600
    assert est(f, out) <= 60000 and any("shortened 5 old tool results" in e["data"]["description"] for e in events)


def test_shortened_results_stay_identical_on_later_turns():
    f = new_filter(token_budget=60000, max_tool_result_tokens=0)
    msgs = agent_chat(8)
    first = run(f, msgs, "agent2")
    more = msgs + [{"role": "assistant", "content": "Nothing new."}, {"role": "user", "content": "ok thanks"}]
    second = run(f, more, "agent2")
    assert second[: len(first)] == first, "an unchanged prefix is what keeps the prompt cache"
    # Under budget again, so results that were whole stay whole instead of being shortened early.
    assert sum("removed to save context" in m["content"] for m in second if m["role"] == "tool") == 5


def test_tool_loop_inside_one_turn_keeps_earlier_turns():
    """Open WebUI runs filters again on every tool round, with the growing turn at the end."""
    calls.clear()
    f = new_filter(token_budget=60000, max_tool_result_tokens=0)
    msgs = convo(3)[:-1] + [{"role": "user", "content": "research this"}]
    for i in range(7):
        msgs.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"r{i}", "function": {"name": "fetch_page", "arguments": "{}"}}]})
        msgs.append({"role": "tool", "tool_call_id": f"r{i}", "name": "fetch_page", "content": f"RESULT {i} " + "y" * 33000})
        out = run(f, msgs, "loop")
        assert est(f, out) <= 60000
    assert not calls and out[1]["content"].startswith("question 0"), "earlier turns survive a long tool loop"
    assert all("u" * 3300 in m["content"] for m in out if m["role"] == "user" and m["content"].startswith("question"))


def test_summary_records_tool_work_and_scales_with_budget():
    calls.clear()
    f = new_filter(token_budget=30000, prune_tool_results=False)
    run(f, agent_chat(6), "work")
    prompt = calls[0]["messages"][1]["content"]
    assert "[called tool fetch_page with" in prompt and "example.org/0" in prompt
    assert "TOOL RESULT (fetch_page): PAGE 0 START" in prompt and "Item 0 costs 0 credits." in prompt
    assert "Work done" in prompt and "Current state" in prompt
    assert f._summary_cap(30000) == 1200 and f._summary_cap(110000) == 2750 and f._summary_cap(400000) == 3000
    f.valves.summary_max_tokens = 500
    assert f._summary_cap(110000) == 500


def load_tool():
    spec = importlib.util.spec_from_file_location("chat_history", ROOT / "tools" / "chat_history.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Tools()


def test_huge_tool_result_is_cut_on_arrival_and_stays_readable():
    f = new_filter(token_budget=100000)
    page = "FIRST LINE " + "z" * 60000 + " the secret code is ZEBRA-4471 " + "z" * 60000 + " LAST LINE"
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "fetch it"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "a", "function": {"name": "fetch_page", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "a", "name": "fetch_page", "content": page},
    ]
    out = run(f, msgs, "cap")
    got = out[-1]["content"]
    assert len(got) < 8000 * 3.3 + 400 and got.startswith("FIRST LINE") and got.endswith("LAST LINE")
    assert "read_chat_message(number=3)" in got, "the note says how to get the rest"
    again = run(f, msgs + [{"role": "assistant", "content": "done"}, {"role": "user", "content": "next"}], "cap")
    assert again[3]["content"] == got, "cut the same way on every turn"

    T = load_tool()
    meta = {"chat_id": "cap"}
    found = asyncio.run(T.search_chat_history("secret code", __metadata__=meta))
    assert "Message 3, tool result (fetch_page)" in found and "ZEBRA-4471" in found
    first = asyncio.run(T.read_chat_message(3, __metadata__=meta))
    assert first.startswith("Message 3") and "FIRST LINE" in first and "part 1 of 21" in first
    assert "LAST LINE" in asyncio.run(T.read_chat_message(3, part=21, __metadata__=meta))
    assert "is not stored" in asyncio.run(T.read_chat_message(1, __metadata__=meta))


def test_removed_turns_stay_searchable():
    calls.clear()
    f = new_filter(token_budget=20000)
    msgs = convo(30)
    msgs[1]["content"] = "my router is a Turris Omnia at 10.11.12.1 " + "u" * 3300
    out = run(f, msgs, "arch")
    assert "Turris" not in str(out[1:]), "the first turn is gone from the context"
    assert "messages 1 to" in out[0]["content"] and "search_chat_history" in out[0]["content"]
    T = load_tool()
    meta = {"chat_id": "arch"}
    assert "Message 1, user" in asyncio.run(T.search_chat_history("router Turris", __metadata__=meta))
    assert "10.11.12.1" in asyncio.run(T.read_chat_message(1, __metadata__=meta))
    assert "No stored message" in asyncio.run(T.search_chat_history("xylophone", __metadata__=meta))
    assert "Nothing from this chat" in asyncio.run(T.search_chat_history("router", __metadata__={"chat_id": "other"}))
    # Editing the history before the cut invalidates message numbers, so the archive starts over.
    msgs[1]["content"] = "edited"
    run(f, msgs[:20], "arch")
    assert "Turris" not in asyncio.run(T.search_chat_history("router Turris", __metadata__=meta))


def test_trim_leaves_headroom_instead_of_sitting_at_the_limit():
    """After a trim the chat must be well under the budget, or the next turn trims again."""
    calls.clear()
    f = new_filter(token_budget=60000, max_tool_result_tokens=0, keep_full_tool_results=5)
    out = run(f, agent_chat(8), "room")  # shortening 3 results leaves ~51k: under budget but too close
    assert calls, "so older turns are folded away as well"
    assert est(f, out) <= 60000 * 0.7 + 200


def test_warns_once_when_builtin_compaction_is_active():
    events = []
    f = new_filter(token_budget=100000)
    msgs = [{"role": "system", "content": "Be brief.\n\n[CONVERSATION SUMMARY]\nearlier stuff"}, {"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}, {"role": "user", "content": "more"}]
    run(f, msgs, "builtin", events=events)
    run(f, msgs, "builtin", events=events)
    assert sum("own context compaction" in e["data"]["description"] for e in events) == 1
    events.clear()
    run(f, convo(2), "plain", events=events)
    assert not events


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
