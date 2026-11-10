---
name: json-wrangling
description: Inspect, query, compare and repair JSON data such as API responses, config files and exports. Use when the user shares JSON and asks what it contains, wants a value extracted, wants two JSON files compared, has a JSON syntax error, or needs a jq or JSONPath expression.
---

# Working with JSON

Do not read large JSON by eye. Get its shape, then go to the part you need.

## Tools

If you can run code, `scripts/json_tool.py` does the common jobs with only the Python standard library:

```
python scripts/json_tool.py shape data.json              # structure, types, array sizes, optional keys
python scripts/json_tool.py get data.json 'items[0].name'
python scripts/json_tool.py get data.json 'items[*].id'  # one value from every element
python scripts/json_tool.py paths data.json --grep email # find where a key or value lives
python scripts/json_tool.py diff old.json new.json       # added, removed and changed values by path
curl -s https://example.com/api | python scripts/json_tool.py shape -
```

On invalid JSON it prints the line, column and a pointer to the error.

## Steps

1. **Shape first.** Say what the top level is, what the main array holds, and how many elements.
2. **Locate** the wanted data with `paths --grep` rather than guessing a path.
3. **Extract or compare**, and show the path you used, so the user can reuse it.
4. **Give the user a reusable expression** in the tool they have: jq, Python, or JavaScript.

## jq cheat sheet

| Goal | Expression |
|---|---|
| One field | `jq '.meta.count'` |
| Field from every element | `jq '.items[].name'` |
| Filter | `jq '.items[] | select(.price > 10)'` |
| Reshape | `jq '.items[] | {id, name}'` |
| Count | `jq '.items | length'` |
| Raw strings, no quotes | `jq -r '.items[].name'` |
| To CSV | `jq -r '.items[] | [.id, .name] | @csv'` |
| Key might be missing | `jq '.a.b? // "none"'` |

## Fixing invalid JSON

The usual causes: a trailing comma, single quotes instead of double, unquoted keys, comments, `None`/`True` from Python instead of `null`/`true`, an unescaped quote or newline inside a string, or a file cut off mid-way. Fix exactly the reported position, then validate again; the first error often hides a second.

## Rules

- Never retype large JSON by hand; values get altered. Transform it with a command.
- Keep numbers as they are. Large ids lose digits when parsed as floats in JavaScript; treat them as strings.
- If the JSON is cut off, say so instead of inventing the missing end.
- Do not print secrets found in the data (tokens, passwords, keys). Mention that they are there.
