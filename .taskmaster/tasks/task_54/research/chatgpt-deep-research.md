# HTTP Node API Design for pflow

## Executive Summary

Design the **HTTP node** so a user can say one sentence—e.g., “\*\*fetch users from [https://api…\*\*”](https://api…**”) or “**post JSON to Slack webhook**”—and pflow turns that into a deterministic request with smart defaults. The **minimal surface** should center on: `url`, `method`, `headers`, `params`, `body`, `auth`, and `timeout`. Everything else stays out of the way until needed. This mirrors how leading workflow tools expose HTTP (basic fields up front, advanced options tucked away), and how developer CLIs like HTTPie and curl optimize “do the common thing with minimal typing.” ([docs.n8n.io][1], [help.zapier.com][2], [IFTTT][3], [httpie.io][4])

Authentication must be frictionless in a CLI: **Bearer tokens** and **Basic auth** should be one-liners (or pulled from env). JSON should be the default **request/response** assumption, SSL verification **on** by default, redirects **followed**, and 4xx/5xx should **fail fast** unless explicitly suppressed. This delivers pflow’s “**Plan once, run forever**” promise for the 80% of API tasks, while leaving room for v2 features (OAuth helpers, multipart, auto-pagination, retry policies) once real usage demands it. ([docs.n8n.io][1], [learn.microsoft.com][5], [httpie.io][4], [everything.curl.dev][6])

---

## Key Findings

* **Everyone exposes the same core knobs.** n8n, Zapier, Make, Power Automate, and IFTTT all converge on: **Method, URL, Headers, Body, Auth** (plus query params). They present these plainly, with switches for body type (JSON/form/raw), and only surface advanced bits (SSL, redirects, pagination) behind toggles. ([docs.n8n.io][1], [help.zapier.com][2], [apps.make.com][7], [learn.microsoft.com][5], [IFTTT][3])
* **Auth is mostly Basic/Bearer.** Tools let you pass username\:password or a token that becomes `Authorization: Bearer …`. More complex auth (OAuth) is handled via credentials/connection objects or left to separate flows. For a CLI-first node, a single `auth` field can cover 90% of cases. ([docs.n8n.io][1], [httpie.io][8])
* **JSON-first defaults reduce friction.** HTTPie auto-serializes data as JSON and sets `Content-Type`/`Accept` unless overridden—exactly the ergonomics pflow should emulate. ([httpie.io][4], [manpages.debian.org][9])
* **Advanced options are opt-in.** n8n offers pagination, proxies, timeout, SSL ignore, response optimization for LLMs—kept under “Options.” Make.com exposes **Parse response** and **Evaluate all states as errors** (treat status codes as errors), but you must choose them. pflow should mirror this progressive complexity. ([docs.n8n.io][1], [apps.make.com][7])
* **IFTTT shows the floor.** Its webhook action requires **URL + Method**; **Content Type**, **Headers**, **Body** are optional. This is the minimalist baseline. ([IFTTT][3])
* **Enterprise patterns:** Power Automate’s HTTP action highlights explicit **Follow redirection**, **Fail on error status**, and **connection timeout**, and writes **status code/headers** to variables—useful cues for pflow’s error/output design. ([learn.microsoft.com][5])
* **Developer muscle memory:** curl doesn’t follow redirects unless `-L`; HTTPie does JSON by default and has native bearer auth; both reinforce sensible defaults and short flags for overrides. ([everything.curl.dev][6], [httpie.io][4])
* **Common complaints to dodge:** Make’s “Parse response” fails when servers send **non-standard content-types**; users want clearer error hints. Treat 4xx/5xx as failures by default but let users override; detect obvious JSON mislabels when safe. ([Make Community][10])

---

## Recommended API Design

### 1) Parameter Specification

**Required**

* **`url`**: `str` — Destination endpoint.
* **`method`**: `str` — One of `GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS`. *(Default heuristic: `GET` if no `body`, `POST` if `body` present.)* ([docs.n8n.io][1], [httpie.io][4])

**Optional (commonly used)**

* **`params`**: `dict[str, str]` — Query string parameters appended to `url`. ([docs.n8n.io][1])
* **`headers`**: `dict[str, str]` — Extra headers (e.g., `Authorization`, `X-API-Key`).
* **`body`**: `str | dict | bytes` — Payload. If `dict`, auto-serialize as JSON and set `Content-Type: application/json`. ([httpie.io][4])
* **`content_type`**: `str` — Override content type (e.g., `application/x-www-form-urlencoded`, `text/plain`).
* **`auth`**: `str | tuple` — Simple auth convenience:

  * `"user:pass"` → Basic Auth
  * `"Bearer TOKEN"` or `"TOKEN"` → Bearer token
  * (API keys: set via `headers` or allow `auth="X-API-Key: KEY"` shorthand later.) ([httpie.io][8])
* **`timeout`**: `int` — Seconds; default `30`.

**Advanced (rarely needed)**

* **`follow_redirects`**: `bool` — Default `true`. (curl needs `-L`; users generally expect following.) ([everything.curl.dev][6])
* **`verify_ssl`**: `bool` — Default `true`; set `false` to ignore invalid certs (explicitly unsafe).
* **`retries`**: `int | {count:int, backoff:str, retry_on:list[int|str]}` — Off by default.
* **`include_headers`**: `bool` — When `true`, also output `status` and `headers`. (Analogous to n8n’s response/headers option.) ([docs.n8n.io][1])
* **`pagination`** *(v2)*: disabled by default; future strategies like “next link” or “page param”. ([docs.n8n.io][1])
* **`form` / `multipart`** *(v2)*: convenience switches to encode dict body as urlencoded or multipart.

> **Defaults**: JSON-first, secure by default (verify SSL), follow redirects, fail on HTTP errors (≥400), and deterministic timeout.

---

### 2) pflow Interface Design

```yaml
# HTTPNode

- Reads:
    shared["url"]: str              # Optional fallback if param omitted
    shared["payload"]: str|dict     # Optional body from prior node
    shared["headers"]: dict         # Optional default headers (e.g., auth from previous step)

- Writes:
    shared["response_body"]: str    # Response text (JSON remains a string by default)
    shared["response_status"]: int  # Only when include_headers=true or on error
    shared["response_headers"]: dict  # Only when include_headers=true

- Params:
    url: str
    method: str                     # GET|POST|PUT|PATCH|DELETE|...
    params: dict[str,str]           # Query parameters
    headers: dict[str,str]          # Request headers
    body: str|dict|bytes            # Request body (dict => JSON)
    content_type: str               # Override Content-Type
    auth: str|tuple                 # "user:pass" | "Bearer TOKEN" | "TOKEN"
    timeout: int                    # default 30
    follow_redirects: bool          # default true
    verify_ssl: bool                # default true
    include_headers: bool           # default false

- Actions:
    http_request (always)
```

**Behavior notes**

* If `method` omitted: **POST** when `body` provided, else **GET**—mirrors HTTPie ergonomics. ([httpie.io][4])
* If `body` is `dict`: auto-serialize to JSON and set `Content-Type` unless user overrides. ([httpie.io][4])
* On `status >= 400`: **fail node** (clear error with status/body excerpt). Power users can toggle behavior later (e.g., `continue_on_error`). ([learn.microsoft.com][5])

---

## Natural Language → Parameter Mapping

| User Says                                                                                         | Maps To                                                                                            |
| ------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| “fetch data from \*\*[https://api.example.com/users\*\*”](https://api.example.com/users**”)       | `method=GET`, `url="https://api.example.com/users"`                                                |
| “get weather for **London** from OpenWeather”                                                     | `method=GET`, `url="https://api.openweathermap.org/data/2.5/weather"`, `params={"q":"London"}`     |
| “post JSON to **[https://api.example.com/users](https://api.example.com/users)** with name/email” | `method=POST`, `url=...`, `body={"name":"…","email":"…"} (JSON)`                                   |
| “send webhook to Slack”                                                                           | `method=POST`, `url="<slack webhook URL>"`, `body={...}` (JSON)                                    |
| “update user 123 at **…/users/123**”                                                              | `method=PUT`, `url="…/users/123"`, `body={...}`                                                    |
| “patch order **A42**”                                                                             | `method=PATCH`, `url="…/orders/A42"`, `body={...}`                                                 |
| “delete **…/items/45**”                                                                           | `method=DELETE`, `url="…/items/45"`                                                                |
| “submit **form data** to **…/submit**”                                                            | `method=POST`, `url=…`, `body={"field":"val"}`, `content_type="application/x-www-form-urlencoded"` |
| “upload **file.jpg** to **…/upload**”                                                             | `method=POST`, `url=…`, *(v2: `multipart` support or combine with read-file\`)*                    |
| “use API key **XYZ**”                                                                             | `headers={"Authorization":"Bearer XYZ"}` *(or `auth="Bearer XYZ"` convenience)* ([httpie.io][8])   |
| “check if **…/health** is up”                                                                     | `method=GET`, `url=…`, default fail if `status>=400` (health degraded)                             |

> These map cleanly to n8n/Zapier/IFTTT mental models: **URL + Method** always, opt-in **Body/Headers/Auth** when needed. ([docs.n8n.io][1], [help.zapier.com][2], [IFTTT][3])

---

## Parameter Design Research (Highlights)

* **Naming convergence:** *Method*, *URL*, *Headers*, *Body*, *Query parameters* (n8n uses “Send Query Parameters/Headers/Body”; Power Automate uses “URL/Endpoint, Method, Custom headers, Request body”). Use these canonical names in pflow. ([docs.n8n.io][1], [learn.microsoft.com][5])
* **Content types:** JSON is the common case; form-urlencoded & multipart are next. Zapier exposes “Payload Type: json|form”, Postman/Insomnia expose explicit body type pickers; we can **infer** JSON from `dict` and provide an override. ([help.zapier.com][2], [Postman Docs][11], [Kong Docs][12])
* **Defaults that help:**

  * JSON serialization & headers when body is structured. (HTTPie precedent.) ([httpie.io][4])
  * Follow redirects (users expect it; curl requires `-L`). ([everything.curl.dev][6])
  * SSL verify on. (Enterprise norm; Insomnia allows toggling for local dev.) ([Kong Docs][13])
  * Fail on HTTP error statuses unless suppressed (Power Automate’s **Fail on error status** exists). ([learn.microsoft.com][5])
  * Timeout \~30s by default (Power Automate defaults 30). ([learn.microsoft.com][5])

---

## Error Handling Patterns

* **Status handling:** Treat **2xx** as success; **4xx/5xx** fail node by default (clear message with status and snippet). Provide a future `continue_on_error` to surface the response for user logic (n8n / Make expose similar toggles). ([docs.n8n.io][1], [apps.make.com][7])
* **Redirects:** Follow automatically; allow `follow_redirects=false` for edge cases. (curl’s `-L` shows expectation—make it the default here.) ([everything.curl.dev][6])
* **Timeouts:** Default 30s; configurable. (Matches Power Automate.) ([learn.microsoft.com][5])
* **Retries (v2):** Add simple `retries` (count + backoff), default off. curl examples show common retry flags (`--retry`, `--retry-max-time`). ([webscraping.ai][14])
* **Make.com learnings:** “Evaluate all states as errors” and “Parse response” toggles surface explicit intent; watch content-type mismatches (JSON labeled incorrectly) and reflect actionable errors. ([apps.make.com][7], [Make Community][10])

---

## Response Processing

* **Default output:** `shared["response_body"]` as text (JSON remains a string for determinism; users can parse downstream).
* **Optional extras:** When `include_headers=true`, also write `shared["response_status"]` and `shared["response_headers"]`. (Parallels n8n’s response options and Power Automate’s variables.) ([docs.n8n.io][1], [learn.microsoft.com][5])
* **Future helpers:**

  * `parse_json=true` to directly emit a parsed object (opt-in, like Make’s **Parse response**). ([apps.make.com][7])
  * Simple JSONPath/JMESPath extraction (later).
  * Streaming/large payload guidance via chaining to `write-file`.

---

## Implementation Recommendations

* **Library:** Start with Python **`requests`** (sync, reliable, SSL/redirects handled, Basic Auth helpers). Consider **`httpx`** later if async execution benefits pflow.
* **MVP behaviors:**

  1. Infer **method** (`POST` with body else `GET`), set JSON headers for `dict` bodies. ([httpie.io][4])
  2. **Auth convenience:** `"user:pass"` → Basic; “`Bearer TOKEN`” or lone token → Bearer header. ([httpie.io][8])
  3. **Secure defaults:** `verify_ssl=true`, `follow_redirects=true`, `timeout=30`, **fail on ≥400** (include status/body excerpt). ([learn.microsoft.com][5], [everything.curl.dev][6])
  4. **Shared store integration:** read `shared["payload"]`/`["headers"]` if param missing; always write `response_body` (and status/headers when asked).
* **Auth handling:** Encourage env/inputs instead of hardcoding (`auth=$API_TOKEN` pattern). Future: simple secrets support or a credentials node (akin to n8n’s credentials). ([docs.n8n.io][1])
* **CLI UX:** Print concise request summary in verbose mode (method, URL, status, \~200-char body snippet on error).
* **Tests:** Cover GET JSON, POST JSON, Basic/Bearer auth, non-200 error, timeout, redirects.

---

## Natural Language Examples (10+)

1. “Fetch users from `https://api.example.com/users`.” → `method=GET, url=…`
2. “Get weather for Stockholm from OpenWeather.” → `GET`, `url=…/weather`, `params={"q":"Stockholm"}`
3. “Post JSON to `…/users` with name and email.” → `POST`, `body={"name":"…","email":"…"}`
4. “Send Slack webhook.” → `POST`, `url="<webhook>"`, `body={text:"…"} `
5. “Update user 42 at `…/users/42`.” → `PUT`, `body={...}`
6. “Patch order A42 status to shipped.” → `PATCH`, `url="…/orders/A42"`, `body={"status":"shipped"}`
7. “Delete `…/items/99`.” → `DELETE`, `url=…`
8. “Submit form data to `…/submit`.” → `POST`, `body={field:"val"}`, `content_type="application/x-www-form-urlencoded"`
9. “Upload `report.pdf` to `…/upload`.” → `POST`, *(v2: multipart)*
10. “Use API key XYZ.” → `headers={"Authorization":"Bearer XYZ"}` *(or `auth="Bearer XYZ"`)* ([httpie.io][8])
11. “Check if `…/health` is up.” → `GET`, fail if `status>=400`.

---

## Implementation Priorities

**MVP (now)**

* Core params: `url, method, headers, params, body, auth, timeout`.
* JSON-first defaults & secure defaults (SSL verify on, redirects on). ([httpie.io][4], [everything.curl.dev][6])
* Fail on HTTP errors by default; clear error messages. ([learn.microsoft.com][5])
* `include_headers` flag to expose status/headers when needed. ([docs.n8n.io][1])

**V2 (after usage feedback)**

* **OAuth 2** helper (token fetch/refresh) and/or credentials node (like n8n). ([docs.n8n.io][1])
* **Multipart uploads** + file streaming; convenience `form=true`.
* **Auto-pagination** strategies (next-link, page param). ([docs.n8n.io][1])
* **Retry policy** (count/backoff; default off). ([webscraping.ai][14])
* **Parse JSON** opt-in + field extraction (simple JSONPath). ([apps.make.com][7])
* **Proxy/CA overrides** for enterprise.

---

## Risks & Mitigations

* **Over-complex surface.** Too many knobs upfront confuses users. **Mitigate:** keep MVP to essentials; advanced flags hidden until asked. (Industry tools do this.) ([docs.n8n.io][1], [IFTTT][3])
* **Underpowered for edge cases.** Missing features block power users. **Mitigate:** always allow `headers`, raw `body`, and arbitrary `method`; promise v2 escape hatches (multipart, OAuth, pagination). ([docs.n8n.io][1])
* **Credential leakage.** Users may paste secrets into workflows. **Mitigate:** recommend env vars/placeholders; mask in logs; plan credentials store later. (Zapier/n8n use credential abstractions.) ([docs.n8n.io][1])
* **Ambiguous failures.** Non-standard content-types break parsing; redirects/timeouts confuse. **Mitigate:** fail fast by default; actionable errors (status, hint); allow disabling follow/SSL if user intends; Make.com community shows content-type pitfalls. ([Make Community][10])
* **Non-determinism & size.** Huge/binary responses and changing external data. **Mitigate:** stream or chain to `write-file`; document API determinism expectations; keep node behavior itself deterministic.

---

## Appendix: Competitive Snapshots (select citations)

* **n8n HTTP Request**: Method/URL; auth (Basic/Digest/OAuth1/2/Custom/Header/Query); Send Query Params/Headers/Body (JSON/form/raw/binary); Options include SSL ignore, redirects, pagination, timeout, response optimization; import cURL. ([docs.n8n.io][1])
* **Zapier Webhooks**: Action config highlights **Payload Type (json|form)**, **Data**, **Basic Auth**, **Headers**; supports nested/unflatten; shows practical examples. ([help.zapier.com][2])
* **Make.com HTTP**: **Parse response** (auto JSON/XML to bundles), **Evaluate all states as errors** (treat HTTP status as errors), community notes on redirects/content-type quirks. ([apps.make.com][7], [Make Community][15])
* **Power Automate HTTP**: Explicit **Follow redirection**, **Fail on error status**, timeout default 30s; stores **StatusCode**, **Headers**, **Response** variables. ([learn.microsoft.com][5])
* **IFTTT Webhooks**: **URL + Method** required; **Content Type**, **Headers**, **Body** optional; FAQ clarifies headers vs Content-Type. ([IFTTT][3], [help.ifttt.com][16])
* **HTTPie**: Data ⇒ JSON by default, sets `Content-Type`/`Accept`; native **Bearer** auth; rich defaults. ([httpie.io][4])
* **curl**: Does **not** follow redirects by default (`-L` to enable); common retry/timeouts flags well-documented. ([everything.curl.dev][6], [webscraping.ai][14])

---

### Final Take

Keep the **HTTP node small, sane, and JSON-first**. Make the 80% **trivial** (URL, method, optional body/auth) and keep power in reserve via a handful of opt-in flags. That’s the sweet spot where pflow’s **NL → deterministic CLI** compiler will shine, chaining `http >> llm >> write-file` all day long.

[1]: https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.httprequest/ "HTTP Request node documentation | n8n Docs "
[2]: https://help.zapier.com/hc/en-us/articles/8496083355661-How-to-get-started-with-Webhooks-by-Zapier "How to get started with Webhooks by Zapier – Zapier"
[3]: https://ifttt.com/maker_webhooks/actions/make_web_request?utm_source=chatgpt.com "Webhooks action: Make a web request"
[4]: https://httpie.io/docs/cli/default-behavior?utm_source=chatgpt.com "Default behavior - HTTPie 3.2.4 (latest) docs"
[5]: https://learn.microsoft.com/en-us/power-automate/desktop-flows/actions-reference/web "HTTP actions reference - Power Automate | Microsoft Learn"
[6]: https://everything.curl.dev/http/redirects.html?utm_source=chatgpt.com "Redirects - Everything curl"
[7]: https://apps.make.com/http?utm_source=chatgpt.com "HTTP - Apps Documentation - Make"
[8]: https://httpie.io/docs/desktop/bearer-auth?utm_source=chatgpt.com "Bearer auth - HTTPie for Web & Desktop docs"
[9]: https://manpages.debian.org/unstable/httpie/http.1.en.html?utm_source=chatgpt.com "http(1) — httpie — Debian unstable"
[10]: https://community.make.com/t/parse-response-option-of-http-module-doesnt-work/46158?utm_source=chatgpt.com "Parse Response Option Of HTTP Module Doesn't Work"
[11]: https://learning.postman.com/docs/sending-requests/create-requests/parameters/?utm_source=chatgpt.com "Send parameters and body data with API requests in ..."
[12]: https://docs.insomnia.rest/insomnia/requests?utm_source=chatgpt.com "Requests | Insomnia Docs"
[13]: https://docs.insomnia.rest/insomnia/authentication?utm_source=chatgpt.com "Authentication | Insomnia Docs"
[14]: https://webscraping.ai/faq/curl/what-are-some-common-curl-options-and-flags?utm_source=chatgpt.com "What are some common Curl options and flags?"
[15]: https://community.make.com/t/help-needed-with-http-module-redirect-issue/49965?utm_source=chatgpt.com "Help Needed with HTTP Module Redirect Issue"
[16]: https://help.ifttt.com/hc/en-us/articles/115010230347-Webhooks-service-FAQ?utm_source=chatgpt.com "Webhooks service FAQ"
