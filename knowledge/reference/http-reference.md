# HTTP reference: methods, status codes, headers, curl

## Methods

| Method | Use | Safe | Idempotent |
|---|---|---|---|
| GET | Read a resource | yes | yes |
| HEAD | Like GET, headers only | yes | yes |
| POST | Create, or run an action | no | no |
| PUT | Replace a resource | no | yes |
| PATCH | Change part of a resource | no | no |
| DELETE | Remove a resource | no | yes |
| OPTIONS | Ask what is allowed; CORS preflight | yes | yes |

## Status codes

| Code | Meaning | Typical cause |
|---|---|---|
| 200 | OK | |
| 201 | Created | A POST made a new resource; `Location` points to it |
| 204 | No Content | Success with an empty body |
| 301 / 308 | Moved permanently | 308 keeps the method, 301 may turn POST into GET |
| 302 / 307 | Temporary redirect | 307 keeps the method |
| 304 | Not Modified | Cached copy is still valid (`If-None-Match`, `If-Modified-Since`) |
| 400 | Bad Request | Malformed syntax or invalid parameters |
| 401 | Unauthorized | Not logged in or bad credentials; `WWW-Authenticate` says how |
| 403 | Forbidden | Logged in, but not allowed |
| 404 | Not Found | Wrong path, or hidden on purpose |
| 405 | Method Not Allowed | `Allow` lists the valid methods |
| 409 | Conflict | State clash, for example a duplicate |
| 413 | Content Too Large | Body over the server limit |
| 415 | Unsupported Media Type | Wrong `Content-Type` |
| 422 | Unprocessable Content | Well-formed but fails validation |
| 429 | Too Many Requests | Rate limit; see `Retry-After` |
| 500 | Internal Server Error | Unhandled error in the application |
| 502 | Bad Gateway | The proxy got an invalid answer from the backend |
| 503 | Service Unavailable | Backend down or overloaded |
| 504 | Gateway Timeout | The backend did not answer the proxy in time |

## Request headers

| Header | Purpose |
|---|---|
| `Host` | Which site on the server; decides the virtual host |
| `Authorization` | `Basic base64(user:pass)` or `Bearer TOKEN` |
| `Cookie` | Session and other cookies |
| `Content-Type` | Format of the body: `application/json`, `application/x-www-form-urlencoded`, `multipart/form-data` |
| `Accept` | Formats the client wants back |
| `User-Agent` | Client identification |
| `Origin`, `Referer` | Where the request came from; used by CORS and CSRF checks |
| `X-Forwarded-For` | Client address as reported by a proxy; trusted only if the server is configured for it |
| `If-None-Match`, `If-Modified-Since` | Conditional requests for caching |
| `Range` | Ask for part of a resource |

## Response headers

| Header | Purpose |
|---|---|
| `Set-Cookie` | Sets a cookie; flags `Secure`, `HttpOnly`, `SameSite`, `Path`, `Domain`, `Max-Age` |
| `Location` | Target of a redirect or of a created resource |
| `Cache-Control` | `no-store`, `no-cache`, `max-age=N`, `private`, `public` |
| `ETag` | Version tag for caching |
| `Content-Disposition` | `attachment; filename="x"` forces a download |
| `Access-Control-Allow-Origin` | Which origins may read the response (CORS) |
| `Strict-Transport-Security` | Browser must use HTTPS for this host |
| `Content-Security-Policy` | Which scripts, styles and frames may load |
| `Server`, `X-Powered-By` | Software names; often reveal versions |

## curl

```
curl -i URL                                  # show response headers and body
curl -I URL                                  # headers only (HEAD)
curl -v URL                                  # show the whole exchange
curl -L URL                                  # follow redirects
curl -k URL                                  # ignore certificate errors
curl -X POST -d 'a=1&b=2' URL                # form body
curl -H 'Content-Type: application/json' -d '{"a":1}' URL
curl -H 'Authorization: Bearer TOKEN' URL
curl -u user:pass URL                        # basic auth
curl -b 'session=abc' URL                    # send a cookie
curl -c jar.txt -b jar.txt URL               # keep cookies between calls
curl -F 'file=@photo.jpg' URL                # multipart upload
curl -o out.bin URL                          # save to a file
curl -x http://127.0.0.1:8080 URL            # through a proxy
curl -s -o /dev/null -w '%{http_code} %{time_total}\n' URL   # status and timing only
curl --resolve example.com:443:10.0.0.5 https://example.com/  # force an address for a name
```
