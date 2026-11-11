"""Tests for the Memory tool and the Auto Memory filter, which share one store. Run: python tests/test_memory.py"""

import asyncio
import importlib.util
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# --- stub open_webui ---------------------------------------------------------
calls = []
replies = []


async def fake_completion(request, form, user=None, bypass_filter=False):
    calls.append(form)
    return {"choices": [{"message": {"content": replies.pop(0) if replies else "NONE"}}]}


async def folder_id_of(chat_id, user_id):
    return {"chat-p": "f1", "chat-p2": "f1", "chat-q": "f2"}.get(chat_id)


async def folder_by_id(folder_id, user_id):
    return types.SimpleNamespace(name={"f1": "Home Lab", "f2": "Thesis"}[folder_id])


async def user_by_id(i):
    return {"id": i}


def _mod(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m


_mod("open_webui")
_mod("open_webui.env", DATA_DIR=tempfile.mkdtemp(prefix="memory_test_"))
_mod("open_webui.utils")
_mod("open_webui.utils.chat", generate_chat_completion=fake_completion)
_mod("open_webui.models")
_mod("open_webui.models.users", Users=types.SimpleNamespace(get_user_by_id=user_by_id))
_mod("open_webui.models.chats", Chats=types.SimpleNamespace(get_chat_folder_id=folder_id_of))
_mod("open_webui.models.folders", Folders=types.SimpleNamespace(get_folder_by_id_and_user_id=folder_by_id))


def load(folder, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / folder / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


REQUEST = types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(MODELS={"qwen": {"owned_by": "ollama"}})))
LONG = "My home server is called atlas and runs Debian 13 on a Ryzen 5600 with 64 GB of RAM. " * 3


def chat(F, chat_id, text, user="u1", history=None):
    """One turn through inlet and outlet. Returns the body the model would see."""

    async def go():
        msgs = list(history or []) + [{"role": "user", "content": text}]
        seen = await F.inlet({"messages": [dict(m) for m in msgs], "options": {"num_ctx": 8192, "temperature": 1}},
                             __user__={"id": user}, __metadata__={"chat_id": chat_id})
        done = msgs + [{"role": "assistant", "content": "Noted."}]
        await F.outlet({"chat_id": chat_id, "model": "qwen", "messages": done}, __user__={"id": user},
                       __metadata__={"chat_id": chat_id}, __request__=REQUEST)
        task = F._tasks.get(chat_id)
        if task:
            await task
        return seen, done

    return asyncio.run(go())


def test_tool_scopes_and_search():
    T = load("tools", "memory").Tools()
    run = asyncio.run
    u = {"id": "tool-user"}
    assert "Saved memory #1 to global" in run(T.remember("The user prefers answers in metric units.", __user__=u))
    assert "project 'Garden'" in run(T.remember("The greenhouse sensor is a BME280 on GPIO 4.", project="Garden", __user__=u))
    assert "already existed" in run(T.remember("The user prefers answers in metric units!", __user__=u))
    assert run(T.remember("short", __user__=u)).startswith("Error")

    assert "BME280" in run(T.recall("sensor", project="Garden", __user__=u))
    assert "BME280" not in run(T.recall("sensor", __user__=u)), "another project's memory must not leak into a chat without a project"
    assert "BME280" in run(T.recall("sensor", project="all", __user__=u))
    assert "metric" in run(T.recall("", project="Garden", __user__=u)), "global memories are visible inside a project"
    assert "Memory is empty" in run(T.recall("x", __user__={"id": "someone-else"}))

    listing = run(T.list_memory_projects(__user__=u))
    assert "Garden: 1" in listing and "global: 1" in listing
    assert "Forgot memory #2" in run(T.forget(2, __user__=u)) and run(T.forget(2, __user__=u)).startswith("Error")


def test_idle_pass_saves_and_later_chat_sees_it():
    F = load("functions", "auto_memory").Filter()
    F.valves.idle_seconds = 0
    replies[:] = ["GLOBAL: The user's home server is called atlas and runs Debian 13.\n- GLOBAL: The password is: hunter2\nsome chatter"]
    calls.clear()
    seen, _ = chat(F, "chat-a", LONG)
    assert "[Memory from earlier chats." not in str(seen["messages"]), "nothing saved yet, so nothing to inject"
    assert len(calls) == 1
    assert calls[0]["options"] == {"num_ctx": 8192, "think": False, "temperature": 0.2}, "same load options as the chat, thinking off"
    assert "atlas" in calls[0]["messages"][1]["content"]

    seen, _ = chat(F, "chat-b", "What do you know about my server?")
    system = seen["messages"][0]
    assert system["role"] == "system" and "atlas" in system["content"] and "hunter2" not in system["content"]
    assert len(calls) == 1, "a short message is not worth a pass"


def test_block_stays_put_within_a_chat():
    F = load("functions", "auto_memory").Filter()
    F.valves.idle_seconds = 0
    T = load("tools", "memory").Tools()
    u = {"id": "u2"}
    asyncio.run(T.remember("The user writes Rust and dislikes ORMs.", __user__=u))
    first, done = chat(F, "chat-c", "hello", user="u2")
    asyncio.run(T.remember("The user's editor is Helix.", __user__=u))
    second, _ = chat(F, "chat-c", "and again", user="u2", history=done)
    assert first["messages"][0]["content"] == second["messages"][0]["content"], "a changed system prompt would throw away the prompt cache"
    fresh, _ = chat(F, "chat-d", "hello", user="u2")
    assert "Helix" in fresh["messages"][0]["content"]

    F.valves.refresh_after_minutes = 0
    third, _ = chat(F, "chat-c", "much later", user="u2", history=done)
    assert "Helix" in third["messages"][0]["content"], "after a long pause the block is rebuilt"


def test_projects_follow_the_chat_folder():
    F = load("functions", "auto_memory").Filter()
    F.valves.idle_seconds = 0
    replies[:] = ["PROJECT: The lab switch is a 2.5 GbE unit on VLAN 30.\nGLOBAL: The user lives by the metric system."]
    chat(F, "chat-p", LONG, user="u3")
    inside, _ = chat(F, "chat-p2", "hi", user="u3")
    other, _ = chat(F, "chat-q", "hi", user="u3")
    loose, _ = chat(F, "chat-z", "hi", user="u3")
    assert 'Project "Home Lab"' in inside["messages"][0]["content"] and "VLAN 30" in inside["messages"][0]["content"]
    for seen in (other, loose):
        text = seen["messages"][0]["content"]
        assert "VLAN 30" not in text and "metric" in text

    # The tool, called from the project chat without naming a project, lands in the same project.
    T = load("tools", "memory").Tools()
    out = asyncio.run(T.remember("The lab NAS exports /tank over NFS.", __user__={"id": "u3"}, __metadata__={"chat_id": "chat-p"}))
    assert "project 'Home Lab'" in out
    assert "NFS" in asyncio.run(T.recall("nas", __user__={"id": "u3"}, __metadata__={"chat_id": "chat-p"}))
    assert "NFS" not in asyncio.run(T.recall("nas", __user__={"id": "u3"}, __metadata__={"chat_id": "chat-q"}))


def test_remember_command_and_update():
    F = load("functions", "auto_memory").Filter()
    F.valves.idle_seconds = 0
    seen, _ = chat(F, "chat-r", "/remember I am allergic to peanuts", user="u4")
    last = seen["messages"][-1]["content"]
    assert last.startswith("I am allergic to peanuts") and "saved to global memory" in last
    T = load("tools", "memory").Tools()
    assert "peanuts" in asyncio.run(T.recall("allergic", __user__={"id": "u4"}))

    replies[:] = ["UPDATE 1: The user is allergic to peanuts and shellfish.\nUPDATE 99: The user also keeps bees in the garden.\nPROJECT: no project here, so this goes global."]
    chat(F, "chat-s", LONG, user="u4")
    got = asyncio.run(T.recall("", __user__={"id": "u4"}))
    assert "shellfish" in got and "goes global" in got and got.count("allergic") == 1
    assert "bees" in got, "an update that names a missing id is kept as a new memory"


def test_never_in_the_way():
    F = load("functions", "auto_memory").Filter()
    F.valves.idle_seconds = 0
    task = {"messages": [{"role": "user", "content": "title?"}]}
    assert asyncio.run(F.inlet(dict(task), __metadata__={"task": "title_generation"})) == task
    calls.clear()
    chat(F, "local:temp", LONG, user="u5")
    assert not calls, "temporary chats are not read for memories"
    replies[:] = ["I could not find anything."]
    chat(F, "chat-t", LONG, user="u5")
    assert "Memory is empty" in asyncio.run(load("tools", "memory").Tools().recall("", __user__={"id": "u5"}))

    # A message that arrives before the idle time is up cancels the pass.
    F.valves.idle_seconds = 30
    calls.clear()

    async def interrupted():
        msgs = [{"role": "user", "content": LONG}, {"role": "assistant", "content": "ok"}]
        await F.outlet({"chat_id": "chat-u", "model": "qwen", "messages": msgs}, __user__={"id": "u5"}, __request__=REQUEST)
        pending = F._tasks["chat-u"]
        await F.inlet({"messages": msgs + [{"role": "user", "content": "more"}]}, __user__={"id": "u5"}, __metadata__={"chat_id": "chat-u"})
        await asyncio.sleep(0)
        return pending.cancelled() or pending.done()

    assert asyncio.run(interrupted()) and not calls


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
