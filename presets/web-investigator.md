# Web investigator preset

A model setup for looking at websites: what a site runs on, why a request fails, whether a page really exists, logging in and reading pages that need cookies or headers. It also fixes the most common reason a local model gets stuck on web tasks: trying to fetch pages from the code interpreter.

## Attach

| What | Which |
|---|---|
| Tools | `web_inspector`, `web_reader`, `text_utils`; `sec_tools` for security work |
| Filters | `tool_coach`, `context_trim`, `date_context` |
| Skills | `website-analysis`, `research-with-sources`; `web-app-testing` for authorized tests |
| Knowledge | the `reference` knowledge base (HTTP methods, status codes, headers) |
| Capabilities | Web search on. Code interpreter optional, with the prompt below |

For lab machines and anything on a private address, switch on `allow_private_addresses` in the Web Inspector valves. It is off by default because it lets the model reach services on your own network.

## System prompt

```
You investigate websites for the owner of this system.

1. Never fetch a URL from code. The code interpreter has no network. Use the tools: site_profile for a first look, http_request for a single request with your own method, headers, cookies or body, check_paths to test whether paths exist, find_in_page to search a page or script, page_structure for forms and scripts, tls_certificate for certificates.
2. Read the whole response: status, redirects, headers, cookies, body, and the Notes under it.
3. A status code alone proves little. 200 can be a custom error page, a redirect can be a catch-all, 403 can be a firewall. Compare with a path that cannot exist before you say a path exists.
4. Before stating a conclusion, write down the evidence for it. One signal is a hint. Two different kinds of evidence that agree make it likely. If you have only one, make a second, different check first.
5. Mark every finding as confirmed, likely or hint. Say what you could not check. Never invent a header, a version or a response.
6. If a result looks odd, repeat the request once and think about what else could explain it: a proxy, a cache, a bot check, a login wall.
7. Load the website-analysis skill with view_skill for anything beyond a single request.
```

## The code interpreter has no TLS, and cannot get it

Open WebUI's default code interpreter is Pyodide: Python compiled to WebAssembly, running inside the browser tab. A browser tab cannot open sockets, so there is no TLS, no raw HTTP, no DNS. `requests`, `urllib` and `ssl` either fail outright or go through the browser's `fetch`, which other sites block (CORS). No setting inside Pyodide changes that.

The built-in prompt nevertheless tells the model it can use the interpreter for "API calls", so a model keeps writing `requests.get(...)`, gets an error, and tries again. Three ways out, best first:

1. **Do network work in tools.** Tools run in the Open WebUI server process, with real sockets and full TLS. That is what `web_inspector` is for, and rule 1 of the system prompt above points the model at it.
2. **Correct the interpreter's prompt.** Admin Panel → Settings → Code Execution → Code Interpreter → prompt template. Add these lines to the template in use:

   ```
   - This Python runs inside the browser and has NO network access: no sockets, no TLS, no DNS. requests, urllib, httpx, socket and ssl do not work. Never fetch a URL from code.
   - To get anything from the web, call a tool first (http_request, read_webpage, fetch_url, search_web), then process the returned text in code.
   ```

3. **Give the interpreter a real Python.** In the same settings, switch the engine from Pyodide to Jupyter and point it at a Jupyter server. Code then runs in a normal Python with sockets, TLS and installable packages. It also means the model executes code on that machine, so run Jupyter in a container that holds nothing you care about.

## Parameters

| Parameter | Value | Why |
|---|---|---|
| temperature | 0.6 | Reading responses is precise work; the chat default of 1.0 invents more |
| presence_penalty | 0 | Headers, paths and status lines repeat on purpose |
| Reasoning (think) | on | Weighing two explanations for a response is where thinking pays off |
| Function calling | native | Needed for skills and for several tool calls in one answer |

The temperature and penalty values follow the security preset and were not measured separately for web work.

## What the tool does not do

- It does not run JavaScript. A page that builds itself in the browser shows up as an almost empty body; the tool says so and points at the scripts, where the API addresses usually are.
- It cannot pass bot checks or CAPTCHAs, and says when it meets one.
- Requests come from the machine Open WebUI runs on, with that machine's address.
- Cookies are kept in memory per chat and are gone after a restart of Open WebUI.
