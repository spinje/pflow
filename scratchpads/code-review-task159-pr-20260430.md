# Code Review: Task 159 Prompt Caching

Review target: PR diff against `origin/main`
Task context: `.taskmaster/tasks/task_159/task-159.md` and implementation progress log

## Critical — must fix before merge

### 1. Anthropic `ttl: 1h` requests do not set the required extended-cache beta header

`src/pflow/core/cache_render.py:197-199` emits `{"type": "ephemeral", "ttl": "1h"}` for Anthropic, and `src/pflow/nodes/llm/llm.py:469-476` only adds provider-specific model options for OpenAI. I do not see any Anthropic path adding `extra_headers={"anthropic-beta": "extended-cache-ttl-2025-04-11"}` or equivalent LiteLLM option.

That is a provider-boundary correctness issue: a workflow declaring `## Cache` with `- ttl: 1h` on Anthropic can produce an invalid request instead of extended caching. This is also inconsistent with the paid spike in `scratchpads/task-159-spike-3.py`, where the 1h call explicitly passed that header. Anthropic’s prompt-caching docs describe the beta header requirement for extended TTL: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching

Suggested fix: add an Anthropic-specific cache kwargs helper alongside `_build_openai_cache_kwargs`, merge it in `_assemble_cache_prep`, and preserve user overrides the same way OpenAI does.

```python
def _build_anthropic_cache_kwargs(*, cache_ttl: str | None) -> dict[str, Any]:
    if cache_ttl != "1h":
        return {}
    return {"extra_headers": {"anthropic-beta": "extended-cache-ttl-2025-04-11"}}
```

Be careful to merge with any user-provided `extra_headers` rather than replacing them.

## Warnings — should be addressed

### 2. `prewarm: true` with images still serializes item 0 even after runtime disables the cache marker

`src/pflow/nodes/llm/llm.py:323-348` says image attachments “gracefully disable prewarm for this run (full fan-out...)” and returns `None` for `user_message_blocks`. But the executor has already made the serialization decision using only `cache_ctx.prewarm` in `src/pflow/runtime/engine/batch_executor.py:612-630`. So an image batch with `prewarm: true` still runs item 0 synchronously, then fans out the remainder, but no item gets the auto batch-prefix cache marker.

That creates the worst of both paths: extra latency with no provider-cache benefit. The current tests in `tests/test_nodes/test_llm/test_batch_cache_prefix.py:402-435` exercise `LLMNode` directly, so they miss the executor-level behavior.

Suggested fix options:

1. Reject `prewarm: true` + `images:` during validation for v1. This is simplest and matches the stated unsupported image-cache limitation.
2. Teach the batch executor whether prewarm is actually eligible before it serializes item 0. That likely means carrying an eligibility flag in `CacheRenderContext` or deriving it from static node params.

Add an integration-style batch executor test where `max_concurrent`/barrier timing proves image batches do not serialize item 0 when prewarm is disabled.

### 3. Stable diagnostic IDs can collapse distinct cache warnings with no `node_id`

`Diagnostic.__eq__` and `__hash__` use `(severity, source, node_id, id or message)` (`src/pflow/core/diagnostic.py:94-104`). `_make_unused_chunk_diagnostic()` sets `id="cache.unused-chunk"` with no `node_id` (`src/pflow/core/workflow/data_flow.py:900-914`). If a workflow declares two unused cache chunks, `deduplicate_diagnostics()` can collapse them into one because the chunk name only appears in `message` and `context`, both ignored once `id` is set.

This weakens validation output for exactly the agent-facing cleanup case: only one dead cache chunk may be reported.

Suggested fix: include a stable location in identity for ID-backed diagnostics, such as `context["path"]`, or make `cache.unused-chunk` preserve message-keyed identity while still emitting the top-level `id` in JSON/text. Add a regression test with two unused chunks and a dedup pass.

## Suggestions — optional improvements

- The trace 2.1.0 task text says `cache_key`, `cache_source`, and `cache_age_sec` are per-event fields, but the implementation stores them under `event["llm_call"]`. That may be fine because the analyzer reads `llm_call`, but the docs/tests should consistently call this the `llm_call` surface to avoid a false contract for external trace consumers.

## Verification

I did not run the test suite for this review. Findings above are from static inspection of the PR diff and task context.
