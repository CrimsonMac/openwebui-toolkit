"""Tests for the smaller functions. Run: python tests/test_functions.py"""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
run = asyncio.run

# --- stub open_webui ---------------------------------------------------------
calls = []
replies = []


async def fake_completion(request, form, user=None, bypass_filter=False):
    calls.append(form)
    return {"choices": [{"message": {"content": replies.pop(0) if replies else "REPLY"}}]}


def _mod(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m


_mod("open_webui")
_mod("open_webui.utils")
_mod("open_webui.utils.chat", generate_chat_completion=fake_completion)
_mod("open_webui.models")
_mod("open_webui.models.users", Users=types.SimpleNamespace(get_user_by_id=lambda i: {"id": i}))


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "functions" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_date_context():
    F = load("date_context").Filter()
    F.valves.timezone = "Asia/Tokyo"
    body = run(F.inlet({"messages": [{"role": "user", "content": "hi"}]}))
    assert body["messages"][0]["role"] == "system" and "[Current date:" in body["messages"][0]["content"]
    assert body["messages"][1]["content"] == "hi"

    body = {"messages": [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "hi"}]}
    once = run(F.inlet(body))["messages"][0]["content"]
    assert once.startswith("Be brief.\n\n[Current date:")
    assert run(F.inlet(body))["messages"][0]["content"] == once, "must not stack on repeated calls"

    F.valves.include_time = True
    body = run(F.inlet({"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}, {"role": "user", "content": "now?"}]}))
    assert "[Sent at " in body["messages"][-1]["content"] and "Sent at" not in body["messages"][1]["content"]

    F.valves.timezone = "Not/AZone"
    assert "[Current date:" in run(F.inlet({"messages": [{"role": "user", "content": "x"}]}))["messages"][0]["content"]
    untouched = {"messages": [{"role": "user", "content": "x"}]}
    assert run(F.inlet(untouched, __metadata__={"task": "title_generation"})) == {"messages": [{"role": "user", "content": "x"}]}


def test_output_cleanup():
    F = load("output_cleanup").Filter()
    c = F.clean
    assert c("Hello there.<|im_end|>") == "Hello there."
    assert c("Answer.<end_of_turn>\n<start_of_turn>model\n") == "Answer."
    assert c("Fine.<|eot_id|><|start_header_id|>assistant<|end_header_id|>") == "Fine."
    assert c("Done.<|im_end|>\n<|im_start|>assistant\n") == "Done."
    code = "Use this:\n```\n<|im_start|>user\nhi<|im_end|>\n```\nand inline `<|im_end|>` too."
    assert c(code) == code, "tokens inside code must stay"
    assert c("The user asked.\nassistant is a word here.") == "The user asked.\nassistant is a word here."
    assert c("a\n\n\n\n\nb") == "a\n\nb"
    assert c("```\na\n\n\n\nb\n```") == "```\na\n\n\n\nb\n```"

    para = "This sentence keeps coming back again and again."
    out = c("Intro.\n\n" + "\n\n".join([para] * 6))
    assert out.count(para) == 1 and "5 repeated block(s) removed" in out
    out = c("Intro.\n\n" + "\n\n".join([para] * 5) + "\n\n" + para[:17])
    assert out.count(para) == 1 and para[:17] + "\n" not in out, out
    lines = "Intro\n" + "\n".join(["- the same list item over and over"] * 8)
    assert c(lines).count("the same list item") == 1
    normal = "Step one.\n\nStep two.\n\nStep one.\n\nStep two."
    assert c(normal) == normal
    short = "| a | b |\n" + "\n".join(["|---|---|"] * 7)
    assert c(short) == short, "short repeated lines such as table rules are left alone"
    two = "Yes.\n\n" + para + "\n\n" + para
    assert c(two) == two, "two in a row is not a loop"

    body = {"messages": [{"role": "user", "content": "q<|im_end|>"}, {"role": "assistant", "content": "A.<|im_end|>"}]}
    out = run(F.outlet(body))["messages"]
    assert out[1]["content"] == "A." and out[0]["content"] == "q<|im_end|>"
    listy = {"messages": [{"role": "assistant", "content": [{"type": "text", "text": "x<|im_end|>"}]}]}
    assert run(F.outlet(listy)) == listy


def test_cache_watch():
    F = load("cache_watch").Filter()
    F.valves.read_tokens_per_second = 200
    events = []

    async def emit(e):
        events.append(e["data"]["description"])

    def turn(msgs, chat="c"):
        events.clear()
        run(F.inlet({"model": "m", "messages": msgs}, __metadata__={"chat_id": chat}, __event_emitter__=emit))
        return list(events)

    big = "x" * 33000  # about 10k tokens
    sys_, u1, a1, u2, a2, u3 = (
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "q1 " + big},
        {"role": "assistant", "content": "a1 " + big},
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "q3"},
    )
    assert turn([sys_, u1]) == [], "first sighting: nothing to compare"
    assert turn([sys_, u1, a1, u2]) == [], "growing at the end keeps the cache"
    assert turn([sys_, u1, a1, u2]) == [], "regenerate keeps the cache"
    assert turn([sys_, u1, a1, u2, a2, u3]) == []

    out = turn([{"role": "system", "content": "Be brief. Today is Tuesday."}, u1, a1, u2, a2, u3])
    assert len(out) == 1 and "system prompt changed" in out[0] and "20k tokens" in out[0] and "roughly 2 min" in out[0], out

    turn([sys_, u1, a1, u2, a2, u3])
    out = turn([sys_, a1, u2, a2, u3])
    assert "1 earlier message(s) were removed" in out[0], out

    turn([sys_, u1, a1, u2, a2, u3], chat="edit")
    out = turn([sys_, {"role": "user", "content": "q1 edited " + big}, a1, u2, a2, u3], chat="edit")
    assert "message 2 (user) is different" in out[0], out

    turn([sys_, u1, a1, u2], chat="tail")
    assert turn([sys_, u1, a1, {"role": "user", "content": "q2 [Sent at 12:00]"}, a2, u3], chat="tail") == [], "a small change near the end is not worth a warning"

    F.valves.report_hits = True
    turn([sys_, u1], chat="hit")
    assert "Prompt cache reused" in turn([sys_, u1, a1, u2], chat="hit")[0]
    assert turn([sys_, u1], chat="") == [] and turn([sys_, u1, a1, u2], chat="") == [], "no chat id, no tracking"


def test_quick_answer():
    F = load("quick_answer").Filter()
    assert F.toggle is True and F.icon.startswith("data:image/svg+xml;base64,")
    ollama = {"owned_by": "ollama"}
    body = run(F.inlet({"messages": [], "options": {"num_ctx": 8192}}, __model__=ollama))
    assert body["options"] == {"num_ctx": 8192, "think": False}
    assert run(F.inlet({"messages": []}, __model__=ollama))["options"] == {"think": False}
    assert "options" not in run(F.inlet({"messages": []}, __model__={"owned_by": "openai"})), "other backends are left alone"
    assert "options" not in run(F.inlet({"messages": []}, __model__=ollama, __metadata__={"task": "title_generation"}))
    F.valves.temperature, F.valves.top_p = 0.7, 0.8
    assert run(F.inlet({"messages": []}, __model__=ollama))["options"] == {"think": False, "temperature": 0.7, "top_p": 0.8}


def test_handoff_brief():
    A = load("handoff_brief").Action()
    calls.clear()
    replies[:] = ["<think>plan</think>## Goal\nShip it.\n```py\nx=1\n```"]
    events = []

    async def emit(e):
        events.append(e)

    body = {
        "model": "big",
        "messages": [
            {"role": "user", "content": "Build a thing"},
            {"role": "assistant", "content": '<details type="reasoning">secret thoughts</details>Sure, here it is.'},
        ],
    }
    run(A.action(body, __user__={"id": "u"}, __request__=object(), __event_emitter__=emit))
    prompt = calls[0]["messages"][1]["content"]
    assert calls[0]["model"] == "big" and "USER: Build a thing" in prompt and "secret thoughts" not in prompt
    msg = next(e for e in events if e["type"] == "message")["data"]["content"]
    assert "## Goal" in msg and "<think>" not in msg and "````markdown" in msg, "outer fence must be longer than inner ones"
    assert events[-1]["data"]["done"]

    A.valves.max_input_chars = 5000
    long_body = {"model": "big", "messages": [{"role": "user", "content": "x" * 4000} for _ in range(20)]}
    assert len(A._transcript(long_body["messages"])) < 30000

    events.clear()
    run(A.action({"messages": []}, __event_emitter__=emit))
    assert events[-1]["data"]["description"] == "Nothing to summarize yet"

    events.clear()
    replies[:] = [""]
    run(A.action(body, __user__={"id": "u"}, __request__=object(), __event_emitter__=emit))
    assert "failed" in events[-1]["data"]["description"] and not any(e["type"] == "message" for e in events)


def test_second_opinion():
    P = load("second_opinion").Pipe()
    body = {"messages": [{"role": "user", "content": "What is 2+2?"}]}
    assert "not configured" in run(P.pipe(body))

    P.valves.answer_model, P.valves.review_model = "big", "other"
    calls.clear()
    replies[:] = ["It is 5.", "- 2+2 is 4, not 5.", "It is 4."]
    out = run(P.pipe(body, __user__={"id": "u"}, __request__=object()))
    assert [c["model"] for c in calls] == ["big", "other", "big"]
    assert out.startswith("It is 4.") and "2+2 is 4, not 5" in out and "It is 5." in out
    assert "<draft_reply>\nIt is 5." in calls[1]["messages"][1]["content"]
    assert calls[2]["messages"][-2] == {"role": "assistant", "content": "It is 5."}

    calls.clear()
    replies[:] = ["It is 4.", "NO ISSUES."]
    out = run(P.pipe(body, __user__={"id": "u"}, __request__=object()))
    assert len(calls) == 2 and out.startswith("It is 4.") and "found no issues" in out

    P.valves.show_work = False
    replies[:] = ["It is 4.", "no issues"]
    assert run(P.pipe(body, __user__={"id": "u"}, __request__=object())) == "It is 4."

    replies[:] = [""]
    assert run(P.pipe(body, __user__={"id": "u"}, __request__=object())).startswith("Second Opinion failed")


def test_steady_vision():
    F = load("steady_vision").Filter()
    img = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
    ollama = {"owned_by": "ollama"}

    text_only = {"messages": [{"role": "user", "content": "hi"}], "options": {"temperature": 1}}
    assert run(F.inlet({"messages": [{"role": "user", "content": "hi"}], "options": {"temperature": 1}}, __model__=ollama)) == text_only

    body = run(F.inlet({"messages": [{"role": "user", "content": [{"type": "text", "text": "what is this?"}, img]}], "options": {"temperature": 1, "num_ctx": 8192}}, __model__=ollama))
    assert body["options"] == {"temperature": 0.2, "num_ctx": 8192, "presence_penalty": 0.0, "think": False}
    parts = body["messages"][0]["content"]
    assert parts[1] == img and parts[2]["text"].startswith("[Image rules:")
    assert run(F.inlet(body, __model__=ollama))["messages"][0]["content"] == parts, "must not stack on repeated calls"

    # A follow-up without an image is still about the image; the old image message keeps its rules.
    follow = {"messages": [{"role": "user", "content": "look", "images": ["AAAA"]}, {"role": "assistant", "content": "a cat"}, {"role": "user", "content": "what colour?"}]}
    out = run(F.inlet(follow, __model__=ollama))
    assert out["options"]["temperature"] == 0.2 and "[Image rules:" in out["messages"][0]["content"] and out["messages"][2]["content"] == "what colour?"

    F.valves.lookback_messages = 2
    far = {"messages": [{"role": "user", "content": "look", "images": ["AAAA"]}] + [{"role": "user", "content": "x"}] * 4}
    assert "options" not in run(F.inlet(far, __model__=ollama)), "an image far back no longer matters"

    F = load("steady_vision").Filter()
    F.valves.seed, F.valves.temperature, F.valves.thinking = 7, -1, "leave"
    out = run(F.inlet({"messages": [{"role": "user", "content": "look", "images": ["AAAA"]}]}, __model__=ollama))
    assert out["options"] == {"seed": 7}, "with thinking left on, the presence penalty is not removed"

    # A Think set in the model's Advanced Params wins over the filter: say so, and do not make the loop worse.
    F = load("steady_vision").Filter()
    seen = []

    async def emit(e):
        seen.append(e["data"]["description"])

    forced = {"owned_by": "ollama", "info": {"params": {"think": True}}}
    out = run(F.inlet({"messages": [{"role": "user", "content": "look", "images": ["AAAA"]}]}, __model__=forced, __event_emitter__=emit))
    assert out["options"] == {"think": False} and len(seen) == 1 and "Advanced Params" in seen[0]
    seen.clear()
    unset = {"owned_by": "ollama", "info": {"params": {"think": False, "temperature": 1}}}
    out = run(F.inlet({"messages": [{"role": "user", "content": "look", "images": ["AAAA"]}]}, __model__=unset, __event_emitter__=emit))
    assert out["options"] == {"temperature": 0.2, "presence_penalty": 0.0, "think": False} and not seen
    other = run(F.inlet({"messages": [{"role": "user", "content": "look", "images": ["AAAA"]}]}, __model__={"owned_by": "openai"}))
    assert "options" not in other and "[Image rules:" in other["messages"][0]["content"]
    task = {"messages": [{"role": "user", "content": "look", "images": ["AAAA"]}]}
    assert run(F.inlet(dict(task), __metadata__={"task": "title_generation"})) == task


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok    {name}")
            except Exception as e:  # noqa: BLE001
                failed += 1
                import traceback

                traceback.print_exc()
                print(f"FAIL  {name}: {type(e).__name__}: {e}")
    sys.exit(1 if failed else 0)
