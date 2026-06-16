# `handle_api_warning` short-circuit trio — #301 + #474 + #249

**Scope:** Fix three coupled GitHub issues *together* because they share one root cause and one
design decision. Do NOT split them into separate branches — see "Why one branch" below.

> Verified against `main` at worktree creation. Trust boundary: every file:line below was read
> directly (Read tool), not assumed. Re-confirm if the file has moved since.

## The shared seam

`detect_api_warning` fires at **`engine.py:1109`** (step 10). On a hit, the engine short-circuits:

```python
warning = detect_api_warning(...)                      # step 10
if warning:
    return handle_api_warning(..., recovered=node.successors.get("error") is not None)
    # ↑ never reaches step 11 (cache) or step 17.5 (the NORMAL failure path:
    #   error_action routing + on-error recovery Diagnostic + completion callback)
```

`handle_api_warning` lives at **`instrumentation.py:747`** (~85 lines). All three bugs are in it
or returned from it:

| Issue | Symptom | Mechanism (file:line) |
|---|---|---|
| **#249** | progress shows the node still "running" | emits `"node_warning"` only (`instrumentation.py:781`), never `"node_complete"` — compare step-17.5 happy/except paths which call `call_completion_callback` |
| **#474** | recovered failure renders as generic "⚠️ API error" instead of the clean `Node 'X' failed — on-error → 'handler'` message | builds a **canned** `warning_diagnostic` (`instrumentation.py:813-823`); `recovered` is **already a param** (line 757, set at the call site, stamped into context at 822) but is ignored for the message + suggestions |
| **#301** | `error_action` (e.g. `continue`) hijacked for "not found"/403/401 patterns | returns `"error"` unconditionally (`instrumentation.py:833`), pre-empting step-17.5 routing. Documented in `runtime/CLAUDE.md` → WorkflowExecutor note. |

## The one decision that resolves all three

**Should the step-10 detection short-circuit, or defer to / merge with the normal step-17.5
failure path?** Answer it once and:

- **#301** → when the node returned a real `error_action`, honor it instead of overriding to `"error"`.
- **#474** → when `recovered=True`, build the same on-error-recovery Diagnostic step 17.5 builds
  (via `mark_node_failed(..., warning=...)`), not the canned api_warning one.
- **#249** → emit `node_complete` (cheapest; pure additive plumbing — could even land first).

The `recovered` flag being plumbed-but-underused is the tell this was meant to be one change.

### #301 carries a genuine precedence decision — surface it to the user BEFORE implementing

The detector is general-purpose (HTTP/MCP/Slack response classification). It can't trivially tell
"external API legitimately returned not-found" from "node genuinely failed and wants routing."
Per CLAUDE.md, ambiguity is a STOP signal. Options to put to the maintainer:

1. Explicit `error_action`/`on-error` **always** wins over a pattern-matched api_warning (cleanest;
   risk: a real API-warning that the author *didn't* intend to route now flows through their handler).
2. api_warning wins only when the node returned the default action (no explicit routing requested).
3. Detector annotates; step 17.5 owns the final action. (Most invasive; arguably the "right" shape.)

Recommend option 1 or 2; do not silently pick one.

## Why one branch (not three)

Three separate branches = three agents independently re-deriving the step-10-vs-17.5 relationship,
with a real risk of inconsistent half-fixes (e.g. #474's render fixed while #301 still swallows the
action). One precedence rule, applied at the `handle_api_warning` / step-17.5 seam, keeps routing,
rendering, and the callback consistent.

## Explicitly OUT of scope

- **#508** (already fixed) — was the *detection* layer (`_parse_mcp_json_result` gating), not the
  *handling* layer. Different concern; don't reopen it here.
- **#253** — different file (`nodes/mcp/node.py:394`), the `return "default"` workaround, its own
  3-option design decision about MCP *protocol* error routing. Touches the step-17.5 invariant
  conceptually but it's a node-level call, not the engine detector. Keep it separate.

## Repro fixtures already in-repo (from the issue bodies)

- #474: `examples/error-handling/non-retriable-file-error.pflow.md` (clean path, no pattern match)
  vs `examples/error-handling/retry-with-backoff.pflow.md` (text matches "not found" → mislabeled).

## Definition of done

- One precedence rule decided *with the user* and applied at the seam.
- #301: `error_action` honored when set; api_warning no longer unconditionally overrides.
- #474: recovered (`on-error`) failures render the recovery message + glyph, matching the
  non-pattern-matching path.
- #249: `node_complete` emitted on the api_warning path.
- Tests pin each behavior; baseline captured before changes, `make test` + `make check` clean,
  regression delta reported. The exception/invariant notes in `runtime/CLAUDE.md` +
  `engine/CLAUDE.md` updated if the step-10/step-17.5 relationship changes.
