"""Tests for the Tool Coach filter. Run: python tests/test_coach.py"""

import asyncio
import copy
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
run = asyncio.run

SPECS = {
    "calc_time": [
        {"name": "calculate", "description": "Exact arithmetic. Use it for any calculation instead of mental math."},
        {"name": "date_diff", "description": "Days between two dates."},
    ],
    "web_reader": [{"name": "fetch_page", "description": "Fetch a web page from a URL and return it as readable text."}],
    "memory": [
        {"name": "remember", "description": "Save one fact to long-term memory so it is known in later chats."},
        {"name": "recall", "description": "Search long-term memory for something from an earlier chat."},
    ],
    "sec_tools": [{"name": "cve_lookup", "description": "Look up a CVE in the vulnerability database."}],
}
SKILLS = [
    types.SimpleNamespace(name="regex-builder", is_active=True, description="Build, explain or fix a regular expression and prove it works on examples. Use when the user asks for a regex or pattern."),
    types.SimpleNamespace(name="docker-troubleshooting", is_active=True, description="Debug containers and Compose setups that will not start, crash or cannot reach each other."),
    types.SimpleNamespace(name="sql-writing", is_active=False, description="Write, fix and speed up SQL queries."),
]
lookups = []


async def get_tool_by_id(tid):
    lookups.append(tid)
    return types.SimpleNamespace(specs=SPECS[tid]) if tid in SPECS else None


async def get_skills(user_id=None):
    return SKILLS


def _mod(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m


_mod("open_webui")
_mod("open_webui.models")
_mod("open_webui.models.tools", Tools=types.SimpleNamespace(get_tool_by_id=get_tool_by_id))
_mod("open_webui.models.skills", Skills=types.SimpleNamespace(get_skills=get_skills))

spec = importlib.util.spec_from_file_location("tool_coach", ROOT / "functions" / "tool_coach.py")
coach = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coach)

ALL = list(SPECS)


def ask(F, text, tool_ids=ALL, history=None):
    body = {"messages": list(history or []) + [{"role": "user", "content": text}], "tool_ids": tool_ids}
    return run(F.inlet(body, __user__={"id": "u"}, __model__={}))["messages"]


def hint(F, text, **kw):
    last = ask(F, text, **kw)[-1]["content"]
    return last.split("[Hint:")[1] if "[Hint:" in last else ""


def test_hints_name_what_fits():
    F = coach.Filter()
    assert "calculate" in hint(F, "what is 1234 * 5678?")
    assert "fetch_page" in hint(F, "summarize https://example.org/post for me")
    assert "remember" in hint(F, "remember that my cat is called Miso")
    assert "recall" in hint(F, "what was the name of the server I told you about last time?")
    assert "cve_lookup" in hint(F, "is CVE-2024-3094 serious?")
    h = hint(F, "I need a regex that matches a date pattern")
    assert "skills regex-builder (load with view_skill first)" in h
    assert "docker-troubleshooting" in hint(F, "my docker compose containers crash on start")
    assert "sql-writing" not in hint(F, "write a SQL query to speed up"), "inactive skills are not offered"


def test_no_hint_when_nothing_fits():
    F = coach.Filter()
    for text in ("hi there", "write me a short poem about autumn", "thanks, that helps!", "why is the sky blue?"):
        assert hint(F, text) == "", text


def test_rules_added_once_and_only_with_tools():
    F = coach.Filter()
    msgs = ask(F, "hello", history=[{"role": "system", "content": "Be brief."}])
    assert msgs[0]["content"].startswith("Be brief.\n\n[Using tools and skills]")
    again = run(F.inlet({"messages": copy.deepcopy(msgs), "tool_ids": ALL}, __user__={"id": "u"}))["messages"]
    assert again[0]["content"].count("[Using tools and skills]") == 1

    F2 = coach.Filter()
    F2.valves.include_skills = False
    plain = {"messages": [{"role": "user", "content": "what is 2 * 3?"}]}
    assert run(F2.inlet(copy.deepcopy(plain), __user__={"id": "u"})) == plain, "no tools, no skills: leave the request alone"
    task = {"messages": [{"role": "user", "content": "what is 2 * 3?"}], "tool_ids": ALL}
    assert run(F.inlet(copy.deepcopy(task), __metadata__={"task": "title_generation"})) == task


def test_earlier_messages_keep_their_hints():
    """What the model saw on turn 1 must be byte-identical on turn 2, or the prompt cache is lost."""
    F = coach.Filter()
    first = ask(F, "what is 1234 * 5678?")
    history = [{"role": "user", "content": "what is 1234 * 5678?"}, {"role": "assistant", "content": "7006652"}]
    second = ask(F, "thanks", history=history)
    assert second[0] == first[0] and second[1] == first[1]
    assert "[Hint:" in second[1]["content"] and "[Hint:" not in second[-1]["content"]


def test_only_enabled_tools_and_cached_catalog():
    F = coach.Filter()
    assert hint(F, "what is 1234 * 5678?", tool_ids=["web_reader"]) == ""
    lookups.clear()
    ask(F, "one", tool_ids=["calc_time"])
    ask(F, "two", tool_ids=["calc_time"])
    assert lookups == ["calc_time"], "tool specs are read once, then cached"
    # Images and other parts are kept; the hint is added as its own text part.
    body = {"messages": [{"role": "user", "content": [{"type": "text", "text": "what is 12 * 12?"}, {"type": "image_url", "image_url": {"url": "data:x"}}]}], "tool_ids": ["calc_time"]}
    parts = run(F.inlet(body, __user__={"id": "u"}))["messages"][-1]["content"]
    assert parts[1]["type"] == "image_url" and "calculate" in parts[2]["text"]


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
