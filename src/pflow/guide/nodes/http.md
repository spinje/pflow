# HTTP Node

**Use for**: JSON REST APIs. For binary/streaming data, use `shell` with `curl` instead.

**Async API tip**: Try `Prefer: wait=60` header first (eliminates polling nodes).

**Integrating a new API?** Research first: authentication method, main endpoints, request format, response structure, rate limits.

**Caching**: HTTP nodes don't cache by default — responses can change between runs, so they re-fetch each time (safe inside polling or iteration loops). Add `cache: true` only when the endpoint is effectively immutable for your run (e.g. a static or versioned resource) and the call is expensive.

### Node Creation Pattern

`````markdown
## Steps

### fetch-with-auth

Fetch data from protected API with authentication.

- type: http
- url: ${api_url}
- method: POST
- headers:
    Authorization: Bearer ${api_token}
    Content-Type: application/json
    Accept: application/json
- body:
    query: ${search_query}
    limit: ${limit}
`````

### When to Probe HTTP Nodes

Probe new/unknown APIs with `pflow probe http url=... headers=...` if you need to extract specific fields from the response. Skip probing if the API structure is documented or you're passing `${node.response}` wholesale.

