---
name: web-app-testing
description: Test a web application or API for security flaws in an authorized assessment, bug bounty or CTF - mapping, authentication, access control, injection, file handling, SSRF. Use when the user gives a URL, HTTP request or response, or source code of a web app and wants to find or confirm vulnerabilities.
---

# Web application testing

Understand the application before attacking it. Test one hypothesis at a time and show the request and the response difference that proves it.

## 1. Map

- Technology: response headers, cookies names, error pages, `/robots.txt`, `/sitemap.xml`, JS files.
- Content: `ffuf -u https://T/FUZZ -w wordlist -mc all -fc 404`, virtual hosts with `-H "Host: FUZZ.T"`.
- Every input: URL parameters, body fields, headers, cookies, file uploads, JSON keys, hidden fields.
- Roles: what an anonymous user, a normal user and an admin can each do.

## 2. Check in this order

1. **Access control** (most common serious bug): change ids in requests (IDOR), call admin endpoints as a normal user, drop the session cookie, change the HTTP method, change `role`/`isAdmin` fields in the body.
2. **Authentication and session**: default credentials, user enumeration by response difference, weak reset tokens, missing rate limit, JWT flaws (use the `jwt_decode` tool if available), cookie flags.
3. **Injection**:
   - SQL: `'`, `' OR '1'='1`, `' AND SLEEP(5)-- -`; confirm with a boolean or time difference before using `sqlmap -r request.txt`.
   - Command: `; id`, `$(id)`, `| id`, with a time-based check `; sleep 5`.
   - Template (SSTI): `{{7*7}}`, `${7*7}`, `<%= 7*7 %>`; 49 in the response means evaluation.
   - XSS: a unique marker first to see where and how it is reflected, then a payload that fits that context.
4. **Files**: path traversal `../../etc/passwd`, upload of a script with a changed extension or content type, local file inclusion with wrappers.
5. **Server-side requests (SSRF)**: any parameter that takes a URL; try an address you control, then internal ones allowed by the scope.
6. **Deserialization, XXE, CORS, open redirect, CSRF, race conditions** where the technology suggests them.

## 3. Confirm and rate

A finding needs: the exact request, the response that shows the effect, and what an attacker gains. Use a harmless proof (read your own second account's data, `id`, a timing difference). Do not dump data or change other users' records.

## With source code

Trace from every input to a sink: database query, shell call, file path, template render, deserializer, outgoing HTTP request. Report file and line, the tainted path, and a request that reaches it.

## How to answer

Say what you are testing and why, give the exact request or command, and say what result confirms or rules it out. When the user pastes a response, interpret it before suggesting the next step.
