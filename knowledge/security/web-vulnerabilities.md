# Web vulnerabilities: how to recognise, confirm and fix

Reference for authorized web application testing and for secure code review. Each section: what it is, where to look, a safe confirmation, the fix.

## SQL injection

- What: user input becomes part of a SQL statement.
- Where: any parameter used in a lookup, filter, sort order or login.
- Confirm: a single quote `'` causes an error or a changed page; `' AND '1'='1` and `' AND '1'='2` give different responses (boolean); `' AND SLEEP(5)-- -` (MySQL), `'; SELECT pg_sleep(5)--` (PostgreSQL), `'; WAITFOR DELAY '0:0:5'--` (MS SQL) delay the response (time-based).
- Column count for UNION: `' ORDER BY 1-- -`, increase until an error.
- Fix: parameterised queries (prepared statements) everywhere; allow-list for identifiers such as column names; least-privilege database account.

## Cross-site scripting (XSS)

- What: input is returned to a browser without encoding, so script runs in another user's session.
- Kinds: reflected (in the response to the same request), stored (saved and shown later), DOM-based (handled by client-side script).
- Confirm: send a unique marker such as `xss7391"'<>` and see where and how it comes back: HTML body, attribute, script block, URL. Then a payload for that context, for example `<img src=x onerror=alert(document.domain)>` in HTML, or `" autofocus onfocus=alert(1) x="` inside an attribute.
- Fix: encode on output for the context (HTML, attribute, JavaScript, URL); use a templating system that escapes by default; Content-Security-Policy as a second layer; `HttpOnly` cookies.

## Broken access control and IDOR

- What: the server does not check that the logged-in user may do this action or see this object.
- Where: numeric or guessable ids in URLs and bodies, admin functions, export and download endpoints, API routes not linked in the UI.
- Confirm: with two accounts of your own, request account B's object with account A's session. Call an admin route with a normal user's session. Repeat a request without the session cookie.
- Fix: check ownership and role on the server for every request; deny by default; do not rely on hidden links or client-side checks.

## Server-side request forgery (SSRF)

- What: the server fetches a URL chosen by the user.
- Where: parameters named `url`, `uri`, `link`, `callback`, `webhook`, `image`, import-from-URL features, PDF generators.
- Confirm: point it at a host you control and see the request arrive. Then internal targets permitted by the scope, such as `http://127.0.0.1:PORT/` or the cloud metadata address `http://169.254.169.254/`.
- Fix: allow-list of destinations; resolve the name and reject private, loopback and link-local addresses, also after redirects; no raw response back to the user.

## Command injection

- What: input reaches a shell command.
- Where: features that ping, convert, compress, or call external programs; file names passed to tools.
- Confirm: `; sleep 5`, `| sleep 5`, `$(sleep 5)`, `` `sleep 5` `` delay the response; `; id` shows output.
- Fix: call programs with an argument list and no shell; validate against an allow-list; never build command strings from input.

## Path traversal and file inclusion

- What: input chooses a file path.
- Confirm: `../../../../etc/passwd`, encoded as `..%2f`, or doubled `....//`. On Windows `..\..\windows\win.ini`. For PHP includes, `php://filter/convert.base64-encode/resource=index.php` reads source.
- Fix: map ids to files on the server; resolve the full path and check it stays inside the intended folder; no user input in include statements.

## Server-side template injection (SSTI)

- Confirm: `{{7*7}}`, `${7*7}`, `<%= 7*7 %>`, `#{7*7}`; the response shows `49`. `{{7*'7'}}` gives `7777777` in Jinja2 and `49` in Twig.
- Fix: never render user input as a template; pass it as data.

## File upload

- Checks: is the extension or the content type trusted; can the uploaded file be requested back and does the server execute it; double extension `shell.php.jpg`; changed case `.pHp`; SVG and HTML uploads (stored XSS).
- Fix: allow-list extensions; store outside the web root or on another domain; generate the file name; serve with `Content-Disposition: attachment`.

## XML external entities (XXE)

- Confirm: add `<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/hostname">]>` and use `&e;` in a field that is echoed.
- Fix: disable DTDs and external entities in the XML parser.

## Insecure deserialization

- Signs: Java serialized data starts with `rO0` in Base64 or `ac ed 00 05` in hex; PHP serialized looks like `O:4:"User":2:{...}`; Python pickle; .NET `__VIEWSTATE` without a MAC.
- Fix: do not deserialize untrusted data; use plain data formats such as JSON with a schema; sign the data.

## Cross-site request forgery (CSRF)

- Confirm: a state-changing request works without an unpredictable token and with cookies sent cross-site.
- Fix: anti-CSRF token per session or request; `SameSite=Lax` or `Strict` cookies; re-authentication for sensitive actions.

## Security headers and cookies

| Header | Good value |
|---|---|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` |
| `Content-Security-Policy` | No `unsafe-inline`; a restrictive `default-src` |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` or CSP `frame-ancestors` | `DENY` or `SAMEORIGIN` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` or stricter |
| Cookie flags | `Secure; HttpOnly; SameSite=Lax` on session cookies |

CORS is misconfigured when the server reflects any `Origin` into `Access-Control-Allow-Origin` together with `Access-Control-Allow-Credentials: true`.
