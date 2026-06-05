# Error Handling

**Use when**: A step can fail and you want to recover rather than abort — "retry on failure", "fall back if X fails", "handle the error", "undo on failure".

Choose the tool by the kind of failure you expect:

| Failure | Tool |
|---|---|
| Transient (flaky network, rate limit, timeout) | `retry:` — automatic re-attempts |
| Expected, with an alternative path | `on-error:` — route to a handler |
| A precondition that must hold | no handler — let it fail and stop the run |

## `retry:` — automatic re-attempts for transient failures

Add `retry:` to a node that does work directly (http, shell, llm, code, file). `max` is the total number of attempts (`max: 1` = no retry); when an attempt fails, pflow waits, then tries again until the attempts run out.

```markdown
### fetch
- type: http
- url: ${api}/data
- retry:
    max: 5
    wait: 1                # base seconds between attempts
    backoff: exponential   # 1s, 2s, 4s, ... (capped at 60s); or `fixed`
```

A node that **succeeds on a retry is a clean success** — recovering from a flaky call does not mark the run as degraded. Reach for `retry:` when a re-attempt can fix the failure: network blips, rate limits, timeouts. For a failure a re-run can't fix — a bad URL, an invalid input — let it fail fast, or route it to a handler with `on-error:`.

For a sub-workflow, put `retry:` on the failing step *inside* the child, not on the `workflow` node that calls it.

## `on-error:` — fall back to a handler

Any node can route its failure to a handler instead of stopping the run:

```markdown
### primary
- type: http
- url: ${primary_api}/data
- on-error: use-backup

### use-backup
Fetch from the backup source when the primary fails.
- type: http
- url: ${backup_api}/data
- next: combine
```

A node reached via `on-error:` must declare an explicit `- next:` (see `pflow guide branching`). The handler runs and the workflow finishes — reported as **completed with a warning** that names the fallback, so the failure stays visible rather than hidden. (Unlike `retry:`, where the same node succeeding on a re-attempt is a clean success, `on-error:` routes *around* a node that stayed failed.)

**Reading the failure:** a handler can read what went wrong from the failed node's output (e.g. `${primary.error}`), and `??` lets a later node take whichever path produced a value: `${primary.response ?? use-backup.response}`.

A self-contained version you can run — `fetch` fails, `recover` supplies a backup, and the run finishes (reported with a warning that the fallback fired):

````markdown
# Fall Back On Failure

Try the primary source; if it fails, recover with a backup so the run finishes.

## Steps

### fetch

Try the primary source. On failure, hand off to the recovery handler.

- type: shell
- on-error: recover

```shell command
echo "primary unavailable" >&2
exit 1
```

### recover

Serve a backup value so the workflow finishes.

- type: shell
- next: end

```shell command
echo "served from backup"
```
````

## Pattern: retry, then fall back

Combine them — retry the transient case automatically, and fall back only if the retries are exhausted:

```markdown
### fetch
- type: http
- url: ${api}/data
- retry: { max: 3, backoff: exponential }
- on-error: use-cache        # reached only after all retries fail
```

## Pattern: compensating rollback (saga)

When a sequence must undo earlier work if a later step fails, point each step's failure at a handler that reverses what was already done:

```markdown
### reserve-stock
- type: http
- url: ${api}/reserve
# no handler — if reserving fails, nothing was done; the run stops here

### charge-card
- type: http
- url: ${api}/charge
- on-error: release-stock        # charge failed → undo the reservation

### release-stock
Undo the reservation because the charge failed.
- type: http
- url: ${api}/release
- inputs:
    id: ${reserve-stock.response.id}
- next: end
```

Each step names the compensator for the work that came before it; the handler reverses it and the run finishes — reported as completed with a warning that the rollback fired.

## Let hard failures stop the run

When a failure means the workflow can't sensibly continue — a missing required input, a precondition that isn't met — leave the node without a handler. A node that fails with no `on-error:` stops the run with a non-zero exit, which is the right outcome for a precondition that must hold.
