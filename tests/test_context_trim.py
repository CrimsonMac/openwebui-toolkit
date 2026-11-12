"""Tests for functions/context_trim.py. Run: python tests/test_context_trim.py

Open WebUI is not needed: the modules the filter imports from it are stubbed, and a small
simulator replays how Open WebUI 0.13 calls a filter: `inlet` then `request` on the first
request of a turn, and `request` again on every tool round, each time with the messages
as the filter left them at the start of the turn plus the new tool messages.
"""

import asyncio
import importlib.util
import json
import sys
import tempfile
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = tempfile.mkdtemp(prefix="context_trim_test_")

# --- stub open_webui ---------------------------------------------------------
calls = []
fail_summaries = False


async def fake_completion(request, form, user=None, bypass_filter=False):
    if fail_summaries:
        raise RuntimeError("model down")
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


def request(urls=()):
    state = types.SimpleNamespace(
        MODELS={"big": {"owned_by": "ollama"}, "tiny": {"owned_by": "ollama"}, "cloud": {"owned_by": "openai"}},
        config=types.SimpleNamespace(TASK_MODEL="tiny", TASK_MODEL_EXTERNAL="", OLLAMA_BASE_URLS=list(urls)),
    )
    return types.SimpleNamespace(app=types.SimpleNamespace(state=state))


def convo(turns, size=3000):
    msgs = [{"role": "system", "content": "You are helpful."}]
    for i in range(turns):
        msgs.append({"role": "user", "content": f"question {i} " + "u" * size})
        msgs.append({"role": "assistant", "content": f"answer {i} " + "a" * size})
    msgs.append({"role": "user", "content": "latest question"})
    return msgs


def call(f, hook, msgs, chat_id="c1", req=True, events=None, model="big", **extra):
    body = {"model": model, "messages": [dict(m) for m in msgs], **extra}

    async def emit(e):
        if events is not None:
            events.append(e)

    out = asyncio.run(
        getattr(f, hook)(
            body,
            __user__={"id": "u1"},
            __metadata__={"chat_id": chat_id},
            __request__=(req if not isinstance(req, bool) else request()) if req else None,
            __event_emitter__=emit,
        )
    )
    return out["messages"]


def run(f, msgs, chat_id="c1", **kw):
    return call(f, "inlet", msgs, chat_id, **kw)


def new_filter(**valves):
    f = ct.Filter()
    for k, val in valves.items():
        setattr(f.valves, k, val)
    return f


def est(f, msgs):
    return sum(f._raw_tokens(m) for m in msgs)


def text_of(msgs):
    return "\n".join(ct._text(m.get("content")) for m in msgs)


class Sim:
    """Replays Open WebUI's calls for an agentic chat."""

    def __init__(self, f, chat_id, system="You are an agent.", true_tokens=None, **kw):
        self.f, self.chat_id, self.kw = f, chat_id, kw
        self.system = {"role": "system", "content": system}
        self.history = []  # what the frontend sends back on the next turn
        self.sent = []  # every prompt that went to the model
        self.events = []
        self.true_tokens = true_tokens
        self.n = 0

    def _send(self, hook, msgs):
        out = call(self.f, hook, msgs, self.chat_id, events=self.events, **self.kw)
        return out

    def _model_reads(self, prompt):
        self.sent.append(prompt)
        if self.true_tokens:
            self.f.stream({"usage": {"prompt_tokens": self.true_tokens(prompt)}}, __metadata__={"chat_id": self.chat_id})

    def turn(self, question, rounds, result_size=6000, parallel=1, final="done"):
        self.history.append({"role": "user", "content": question})
        base = self._send("inlet", [self.system] + self.history)
        base = self._send("request", base)
        self._model_reads(base)
        new = []
        for _ in range(rounds):
            ids = []
            for _ in range(parallel):
                self.n += 1
                ids.append(f"call_{self.n}")
            new.append(
                {
                    "role": "assistant",
                    "content": f"step for {ids[0]}",
                    "tool_calls": [{"id": i, "type": "function", "function": {"name": "fetch", "arguments": json.dumps({"q": i})}} for i in ids],
                }
            )
            for i in ids:
                new.append({"role": "tool", "tool_call_id": i, "name": "fetch", "content": f"RESULT {i} START " + ("the page says many things here " * (result_size // 31)) + f" RESULT {i} END"})
            # Open WebUI keeps its own untrimmed list of this turn and hands all of it over each round.
            self._model_reads(self._send("request", base + new))
        new.append({"role": "assistant", "content": f"{final} ({question})"})
        self.history.extend(new)
        return self


def breaks(sent):
    """How often a prompt did not start with the whole previous prompt (= the backend must re-read)."""
    count = 0
    for a, b in zip(sent, sent[1:]):
        if b[: len(a)] != a:
            count += 1
    return count


# --- tests -------------------------------------------------------------------


def test_under_budget_untouched():
    f = new_filter(token_budget=100000)
    msgs = convo(5)
    assert run(f, msgs, "under") == msgs
    assert call(f, "request", msgs, "under") == msgs


def test_has_a_request_hook_for_tool_rounds():
    f = new_filter()
    assert callable(getattr(f, "request", None)), "Open WebUI 0.13 calls `request`, not `inlet`, on tool rounds"
    assert callable(getattr(f, "stream", None))


def test_long_tool_loop_stays_inside_the_budget():
    calls.clear()
    f = new_filter(token_budget=40000, overhead_tokens=0)
    sim = Sim(f, "loop").turn("Audit the whole site and write the report", rounds=60)
    for prompt in sim.sent:
        assert est(f, prompt) <= 40000 * 1.02, est(f, prompt)
        assert any(m["role"] == "user" and "Audit the whole site" in m["content"] for m in prompt), "the request must stay"
        assert prompt[0]["role"] == "system" and prompt[0]["content"].count(ct.NOTE_OPEN) <= 1
        # A tool message is never left without the assistant message that called it.
        for i, m in enumerate(prompt):
            if m["role"] == "tool":
                assert prompt[i - 1]["role"] in ("tool", "assistant") and i > 0
                j = i
                while prompt[j]["role"] == "tool":
                    j -= 1
                assert any(c["id"] == m["tool_call_id"] for c in prompt[j].get("tool_calls", []))
    last = sim.sent[-1]
    assert "RESULT call_60 START" in last[-1]["content"] and len(last[-1]["content"]) > 6000, "newest result is whole"
    assert ct.NOTE_OPEN in last[0]["content"] and "SUMMARY#" in last[0]["content"]
    assert calls, "the removed part of the turn was summarized"
    # The summary is told what the assistant is working on.
    assert "Audit the whole site" in calls[-1]["messages"][1]["content"]


def test_prompt_cache_survives_between_trims():
    f = new_filter(token_budget=40000, overhead_tokens=0)
    sim = Sim(f, "cache").turn("Do the long job", rounds=60)
    trims = sum("shortened" in e["data"]["description"] or "Context trimmed" in e["data"]["description"] for e in sim.events)
    assert breaks(sim.sent) <= trims, (breaks(sim.sent), trims)
    assert trims <= 8, f"{trims} trims in 60 rounds is too many"


def test_next_turn_continues_where_the_loop_stopped():
    calls.clear()
    f = new_filter(token_budget=12000, overhead_tokens=0)
    sim = Sim(f, "nextturn").turn("First job", rounds=40, result_size=3000)
    state = dict(f._get_state("nextturn"))
    summaries = len(calls)
    assert state.get("anchor") and state.get("summary")
    before = sim.sent[-1]
    sim.turn("Second job", rounds=1, result_size=200)
    first = sim.sent[len(sim.sent) - 2]
    assert first[: len(before)] == before, "the new turn must start with exactly what the model last read"
    assert len(calls) == summaries, "nothing is summarized again"
    after = f._get_state("nextturn")
    assert after.get("anchor") == state["anchor"] and after.get("summary") == state["summary"], "state must not be reset"
    assert "First job" in text_of(first) and "Second job" in text_of(first)


def test_many_turns_keep_a_rolling_summary():
    calls.clear()
    f = new_filter(token_budget=30000, overhead_tokens=0)
    sim = Sim(f, "rolling")
    for i in range(8):
        sim.turn(f"Job number {i}", rounds=12)
    assert len(calls) >= 2
    # Each summary call is handed the previous note.
    assert "SUMMARY#" in calls[-1]["messages"][1]["content"].split("<current_request>")[0]
    for prompt in sim.sent:
        assert est(f, prompt) <= 30000 * 1.02
    assert "Job number 7" in text_of(sim.sent[-1])


def test_running_twice_changes_nothing():
    f = new_filter(token_budget=20000, overhead_tokens=0)
    once = run(f, convo(20), "idem")
    assert ct.NOTE_OPEN in once[0]["content"]
    twice = call(f, "request", once, "idem")
    assert twice == once
    assert call(f, "request", twice, "idem") == once


def test_note_stays_in_place_when_another_filter_writes_after_it():
    f = new_filter(token_budget=20000, overhead_tokens=0)
    once = run(f, convo(20), "order")
    # A filter that runs later (memory, date) appends its own block to the system prompt.
    once[0] = {**once[0], "content": once[0]["content"] + "\n\n<memory>likes tea</memory>"}
    again = call(f, "request", once, "order")
    assert again == once, "the prompt must not change, or the backend re-reads the whole chat"
    # With content given as a list of parts.
    g = new_filter(token_budget=20000, overhead_tokens=0)
    msgs = convo(20)
    msgs[0] = {"role": "system", "content": [{"type": "text", "text": "You are helpful."}]}
    first = run(g, msgs, "orderlist")
    assert ct.NOTE_OPEN in first[0]["content"][-1]["text"]
    assert call(g, "request", first, "orderlist") == first


def test_trims_whole_turns_and_summarizes():
    calls.clear()
    f = new_filter(token_budget=20000, overhead_tokens=0)
    events = []
    msgs = convo(20)
    out = run(f, msgs, "plain", events=events)
    assert out[0]["role"] == "system" and out[0]["content"].startswith("You are helpful.")
    assert "SUMMARY#" in out[0]["content"] and "<think>" not in out[0]["content"]
    assert out[1]["role"] == "user" and out[-1]["content"] == "latest question"
    assert est(f, out) <= 20000 * 0.75, "trims well below the budget, not just under it"
    assert any("Context trimmed" in e["data"]["description"] for e in events)
    # The original list is not modified.
    assert msgs[0]["content"] == "You are helpful."


def test_edited_history_resets_state():
    f = new_filter(token_budget=20000, overhead_tokens=0)
    run(f, convo(20), "edit")
    assert f._get_state("edit").get("anchor")
    other = [{"role": "system", "content": "You are helpful."}, {"role": "user", "content": "a new branch"}]
    out = run(f, other, "edit")
    assert out == other
    assert not f._get_state("edit").get("anchor")


def test_state_survives_restart_and_old_state_is_ignored():
    f = new_filter(token_budget=20000, overhead_tokens=0)
    msgs = convo(20)
    first = run(f, msgs, "restart")
    again = run(new_filter(token_budget=20000, overhead_tokens=0), msgs, "restart")
    assert again == first

    g = new_filter(token_budget=20000, overhead_tokens=0)
    g._put_state("legacy", {"cut": 12, "fp": "abc", "summary": "old style", "prune": 12})
    h = new_filter(token_budget=20000, overhead_tokens=0)
    out = run(h, convo(3), "legacy")
    assert out == convo(3), "position-based state from before 3.0 must not be applied"


def test_note_is_kept_when_state_is_lost():
    f = new_filter(token_budget=20000, overhead_tokens=0, persist_state=False)
    once = run(f, convo(20), "lost")
    fresh = new_filter(token_budget=20000, overhead_tokens=0, persist_state=False)
    again = call(fresh, "request", once, "lost")
    assert again[0]["content"].count(ct.NOTE_OPEN) == 1 and "SUMMARY#" in again[0]["content"]


def test_summary_failure_falls_back_to_dropping():
    global fail_summaries
    fail_summaries = True
    try:
        f = new_filter(token_budget=20000, overhead_tokens=0)
        events = []
        out = run(f, convo(20), "fail", events=events)
    finally:
        fail_summaries = False
    assert est(f, out) <= 20000
    assert "No summary is available" in out[0]["content"]
    assert any("summary failed" in e["data"]["description"] for e in events)


def test_images_stripped_from_old_messages_only():
    f = new_filter(token_budget=100000, keep_images_in_last=2)
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "old", "images": ["AAAA"]},
        {"role": "assistant", "content": "a"},
        {"role": "user", "content": [{"type": "text", "text": "mid"}, {"type": "image_url", "image_url": {"url": "data:x"}}]},
        {"role": "assistant", "content": "b"},
        {"role": "user", "content": "new", "images": ["BBBB"]},
    ]
    out = run(f, msgs, "img")
    assert "images" not in out[1] and ct.IMAGE_PLACEHOLDER in out[1]["content"]
    assert all(p.get("type") != "image_url" for p in out[3]["content"])
    assert out[5]["images"] == ["BBBB"]
    assert call(f, "request", out, "img") == out


def test_budget_from_context_size():
    f = new_filter()
    assert f._budget(131072) == int(131072 * 0.9) - 8192
    assert f._budget(4096) == int(4096 * 0.9) - 1024
    assert f._budget(0) == 200000 and f._budget(0, ollama=True) == 28000
    f = new_filter(max_reread_seconds=30, read_tokens_per_second=2000)
    assert f._budget(131072) == 60000
    # num_ctx on the request wins.
    f = new_filter(overhead_tokens=0)
    out = run(f, convo(20), "numctx", options={"num_ctx": 16384})
    assert est(f, out) <= 16384 * 0.9 - 4096


class FakeOllama(BaseHTTPRequestHandler):
    loaded = [{"name": "big:latest", "model": "big:latest", "context_length": 24576}]
    shown = {"parameters": "num_batch                      2048\nnum_ctx                        20480\n"}

    def _reply(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._reply({"models": type(self).loaded})

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._reply(type(self).shown)

    def log_message(self, *a):
        pass


def test_context_size_is_asked_from_ollama():
    server = HTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        # The request carries no num_ctx (it lives in the Modelfile): a loaded model says what it runs with.
        f = new_filter(overhead_tokens=0)
        assert asyncio.run(f._context_size({"model": "big"}, None, request([url]))) == 24576
        out = run(f, convo(20), "ps", req=request([url]))
        assert 3000 < est(f, out) <= 24576 * 0.9 - 6144, est(f, out)
        # Not loaded: the Modelfile parameters are read.
        FakeOllama.loaded = []
        f = new_filter(overhead_tokens=0)
        assert asyncio.run(f._context_size({"model": "big"}, None, request([url]))) == 20480
        # A custom Open WebUI model is looked up under its base model.
        f = new_filter(overhead_tokens=0)
        wrapped = {"id": "my-agent", "info": {"base_model_id": "big"}}
        assert asyncio.run(f._context_size({"model": "my-agent"}, wrapped, request([url]))) == 20480
        # The valve overrides Open WebUI's connection list.
        f = new_filter(overhead_tokens=0, ollama_url=url)
        assert asyncio.run(f._context_size({"model": "big"}, None, request())) == 20480
    finally:
        FakeOllama.loaded = [{"name": "big:latest", "model": "big:latest", "context_length": 24576}]
        server.shutdown()


def test_unknown_ollama_context_uses_a_small_budget_and_says_so():
    events = []
    f = new_filter(overhead_tokens=0)
    out = run(f, convo(30), "unknown", events=events)  # no Ollama reachable
    assert est(f, out) <= 28000
    assert sum("could not find the context size" in e["data"]["description"] for e in events) == 1
    # A model that is not served by Ollama keeps the large default.
    events.clear()
    out = run(f, convo(30), "cloudchat", events=events, model="cloud")
    assert out == convo(30) and not events


def test_summary_model_choices():
    calls.clear()
    f = new_filter(token_budget=20000, summary_model="task")
    run(f, convo(20), "taskmodel")
    assert calls and all(c["model"] == "tiny" for c in calls)
    assert calls[0]["options"] == {"num_ctx": 32768, "think": False}

    calls.clear()
    f = new_filter(token_budget=20000, summary_model="missing-model")
    run(f, convo(20), "missingmodel")
    assert calls and all(c["model"] == "big" for c in calls), "unknown model falls back to the chat model"

    calls.clear()
    f = new_filter(token_budget=20000)
    run(f, convo(20), "samemodel2", options={"num_ctx": 65536, "num_batch": 2048, "temperature": 0.3})
    assert calls and all(c["options"] == {"num_ctx": 65536, "num_batch": 2048, "think": False} for c in calls), "reuse the chat's load settings"


def test_task_requests_skipped():
    f = new_filter(token_budget=2000)
    body = {"model": "big", "messages": convo(20)}
    out = asyncio.run(f.inlet(dict(body), __metadata__={"chat_id": "t", "task": "title_generation"}))
    assert out["messages"] == body["messages"]
    out = asyncio.run(f.request(dict(body), __metadata__={"chat_id": "t", "task": "title_generation"}))
    assert out["messages"] == body["messages"]


def test_estimate_follows_real_token_counts():
    # The backend counts 30 % more than the estimate, plus 9000 tokens of tool definitions.
    f = new_filter(overhead_tokens=2000)

    def true(prompt):
        return int(est(f, prompt) * 1.3 + 9000)

    ctx = 60000
    sim = Sim(f, "calib", true_tokens=true, options={"num_ctx": ctx})
    sim.turn("Long job", rounds=50, result_size=20000)
    over = [true(p) for p in sim.sent[3:] if true(p) > ctx - 4096]
    assert not over, f"prompts would overflow the context: {over}"
    assert 1.15 <= f._k("big") <= 1.45, f._k("big")
    st = f._get_state("calib")
    assert 6000 <= f._overhead(st, "big") <= 14000, f._overhead(st, "big")
    # The learned factor is stored for the next start.
    assert 1.15 <= new_filter()._k("big") <= 1.45


def test_usage_from_a_cut_prompt_is_not_trusted():
    f = new_filter()
    f._pending["cutoff"] = ("big", 50000.0, False, 60000)
    f.stream({"usage": {"prompt_tokens": 59990}}, __metadata__={"chat_id": "cutoff"})
    assert not f._get_state("cutoff").get("sample")
    # Events without usage, or odd shapes, pass through untouched.
    assert f.stream({"choices": []}, __metadata__={"chat_id": "x"}) == {"choices": []}
    assert f.stream("text") == "text"


def test_unread_results_are_never_shortened():
    f = new_filter(token_budget=30000, overhead_tokens=0)
    sim = Sim(f, "parallel").turn("Fetch many pages", rounds=6, parallel=6, result_size=6000)
    last = sim.sent[-1]
    newest = [m for m in last if m["role"] == "tool"][-6:]
    assert all(len(m["content"]) > 6000 for m in newest), "results the model has not answered yet stay whole"


def test_token_estimate_depends_on_what_the_text_is():
    # Real counts from a Qwen tokenizer: prose about 4 characters per token, logs and numbers about 1.5.
    prose = "The filter keeps long chats inside the context window and never loses the thread of the work. " * 100
    log = "\n".join(f"nov 12 03:{i % 60:02d}:17 host proc[{4100 + i}]: task {i * 37} | n_tokens = {90000 + i * 13}, sha256-{i * 2654435761 % 2**64:016x}" for i in range(100))
    numbers = "\n".join(",".join(f"{(i * j * 7.31) % 1000:.3f}" for j in range(1, 9)) for i in range(1, 120))
    assert 3.6 <= len(prose) / ct._count_tokens(prose) <= 5.2
    assert 1.2 <= len(log) / ct._count_tokens(log) <= 2.0
    assert 0.9 <= len(numbers) / ct._count_tokens(numbers) <= 1.4
    # So a tool result full of numbers is cut to fewer characters than one full of prose.
    f = new_filter(token_budget=500000, max_tool_result_tokens=2000)
    def capped(text):
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "go"},
                {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": "t", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "c1", "content": text * 20}]
        return run(f, msgs, "dense" + str(len(text)))[3]["content"]
    assert len(capped(numbers)) < len(capped(prose)) / 2
    assert ct._count_tokens(capped(numbers)) < 2600 and ct._count_tokens(capped(prose)) < 2600


def test_every_field_counts_toward_the_estimate():
    f = new_filter()
    plain = {"role": "assistant", "content": "ok"}
    heavy = {"role": "assistant", "content": "ok", "reasoning_content": "r" * 30000}
    assert f._raw_tokens(heavy) > f._raw_tokens(plain) + 9000
    pic = {"role": "user", "content": "x", "images": ["A" * 300000]}
    assert f._raw_tokens(pic) < 1200, "base64 image data is not text"


def load_tool():
    spec = importlib.util.spec_from_file_location("chat_history", ROOT / "tools" / "chat_history.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.Tools()


def test_huge_tool_result_is_cut_on_arrival_and_stays_readable():
    f = new_filter(token_budget=200000, max_tool_result_tokens=2000)
    page = "PAGE START " + "x" * 50000 + " NEEDLE-4711 " + "y" * 50000 + " PAGE END"
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "fetch it"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": "fetch", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "fetch", "content": page},
    ]
    out = run(f, msgs, "huge")
    short = out[3]["content"]
    assert len(short) < 7000 and short.startswith("PAGE START") and short.endswith("PAGE END")
    number = int(ct._PRUNED_RE.search(short).group(1))
    assert call(f, "request", out, "huge") == out, "a shortened result is left alone when seen again"
    tool = load_tool()
    meta = {"chat_id": "huge"}
    found = asyncio.run(tool.search_chat_history("NEEDLE-4711", __metadata__=meta))
    assert "NEEDLE-4711" in found and f"Message {number}" in found
    part = asyncio.run(tool.read_chat_message(number, __metadata__=meta))
    assert part.split(":\n", 1)[1].startswith("PAGE START")


def test_shortening_gives_the_same_text_from_either_starting_point():
    f = new_filter(max_tool_result_tokens=2000, pruned_tool_chars=1200)
    m = {"role": "tool", "tool_call_id": "c9", "name": "fetch", "content": "HEAD " + "z" * 80000 + " TAIL"}
    capped = f._shorten("same", m, 6000)
    direct = f._shorten("same", m, 1200)
    via_capped = f._shorten("same", capped, 1200)
    assert direct["content"] == via_capped["content"]
    assert f._shorten("same", direct, 1200) is direct


def test_removed_messages_stay_searchable():
    f = new_filter(token_budget=20000, overhead_tokens=0)
    msgs = convo(20)
    msgs[1]["content"] = "The door code is 918273. " + msgs[1]["content"]
    out = run(f, msgs, "search")
    assert "918273" not in text_of(out[1:])
    tool = load_tool()
    found = asyncio.run(tool.search_chat_history("door code", __metadata__={"chat_id": "search"}))
    assert "918273" in found


def test_warns_once_when_builtin_compaction_is_active():
    events = []
    f = new_filter(token_budget=100000)
    msgs = [{"role": "system", "content": "Be brief.\n\n[CONVERSATION SUMMARY]\nearlier stuff"}, {"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}, {"role": "user", "content": "more"}]
    run(f, msgs, "builtin", events=events)
    run(f, msgs, "builtin", events=events)
    assert sum("own context compaction" in e["data"]["description"] for e in events) == 1
    events.clear()
    run(f, convo(2), "plain2", events=events)
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
