---
name: openwebui-extension-author
description: Write or fix Open WebUI extensions in Python - Tools, Filter functions, Pipe functions and Action functions. Use when the user asks for a tool, function, filter, pipe or action for Open WebUI, or pastes one that fails to load or run.
---

# Writing Open WebUI extensions

Every extension is ONE Python file. It starts with a metadata docstring, then one class with a fixed name.

```python
"""
title: Short Name
author: name
version: 1.0.0
description: One sentence on what it does.
requirements: httpx, beautifulsoup4
"""
```

Leave `requirements` out when only the standard library and pydantic are used.

## Pick the type

| The user wants | Type | Class name |
|---|---|---|
| The model to be able to call something (search, calculate, fetch) | Tool | `Tools` |
| To change every request or reply (inject, trim, redact, log) | Filter function | `Filter` |
| A new entry in the model list (proxy, agent, custom backend) | Pipe function | `Pipe` |
| A button under a message | Action function | `Action` |

## Rules for all types

- Settings go in a nested `class Valves(BaseModel)` with `Field(default, description=...)`, and `self.valves = self.Valves()` in `__init__`. Never hardcode keys or URLs.
- Make methods `async`. Use `httpx.AsyncClient` or `aiohttp`, never blocking `requests`, inside them.
- Optional injected arguments are requested by name, with a default of `None`: `__user__`, `__event_emitter__`, `__event_call__`, `__metadata__`, `__request__`, `__model__`, `__messages__`, `__files__`.
- Show progress with `await __event_emitter__({"type": "status", "data": {"description": "Fetching…", "done": False}})` and finish with `"done": True`.
- Catch exceptions and return a readable error string. An uncaught exception breaks the chat.

## Tool

```python
class Tools:
    def __init__(self):
        self.valves = self.Valves()

    async def get_weather(self, city: str, days: int = 1) -> str:
        """
        Get the weather forecast for a city.

        :param city: City name, for example "Lisbon".
        :param days: Number of days, 1 to 7.
        :return: Forecast as plain text.
        """
```

- The model sees ONLY the method name, type hints and docstring. Write the docstring for the model: say when to use it and give an example value per parameter.
- Every parameter needs a type hint and a `:param name:` line. Use `str`, `int`, `float`, `bool`. Avoid nested objects; small models fill them in wrongly.
- Return a string. Keep it short; it lands in the context window. Cut long results and say that they were cut.
- Few tools with few parameters beat many. One tool does one thing.

## Filter

```python
class Filter:
    async def inlet(self, body: dict, __user__: dict = None) -> dict:   # before the model
        return body
    async def stream(self, event: dict) -> dict:                         # each streamed chunk
        return event
    async def outlet(self, body: dict, __user__: dict = None) -> dict:  # after the reply
        return body
```

- `body["messages"]` is a list of `{"role", "content"}`. `content` is a string OR a list of parts (`{"type": "text"}`, `{"type": "image_url"}`). Handle both.
- Always return `body`. Changes made in `inlet` reach the model but are not saved to the chat.
- A `priority` valve sets the order between filters; lower runs first.

## Pipe

```python
class Pipe:
    def pipes(self):                 # optional: expose several models
        return [{"id": "my-model", "name": "My Model"}]
    async def pipe(self, body: dict, __user__: dict = None):
        yield "streamed text"        # or return one string
```

## Action

```python
class Action:
    async def action(self, body: dict, __user__=None, __event_emitter__=None, __event_call__=None):
        ...
```

Ask the user for input with `await __event_call__({"type": "input", "data": {"title": "...", "message": "...", "placeholder": "..."}})`.

## Before you hand it over

1. One file, the right class name, the metadata docstring on line 1.
2. No placeholder code. Every branch works.
3. Say where to paste it: Tools go in Workspace → Tools; functions go in Admin Panel → Functions, and must then be switched on and, for filters, enabled per model or globally.
4. List the valves the user has to fill in.
