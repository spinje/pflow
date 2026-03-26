# Task 133: Unified Per-Node Storage for Trace and Cache

## Description

Restructure trace and cache storage into a shared, content-addressed per-node store. Currently, node output data is stored twice — in the monolithic trace file (for debugging/reporting) and in the memoization cache file (for iteration caching). Unify them into per-node files that serve both purposes.

## Status

not started

## Priority

low

## Problem

After Task 106 (iteration cache) and Task 108 (trace system), node output data is duplicated:
- **Trace**: stores `node_output` per node inside a monolithic JSON file (~17MB for lyrics-generator). Also stores LLM prompts, responses, template resolutions, nested sub-workflow events.
- **Cache**: stores `output` per node in lean cache files (~3MB for lyrics-generator). Also stores cache key, action string.

~3MB of node output data is written to both systems. Different format, different access pattern, same underlying data.

## Solution

Per-node files in a content-addressed store. Each node execution writes one file containing everything — output data, trace metadata (timing, prompts, resolutions), and cache metadata (cache key, action). Both the trace report generator and the cache system read from the same store.

```
~/.pflow/store/
  {content_hash}.json    # one file per node invocation
```

The monolithic trace file becomes a **generated artifact** — assembled from per-node files for a given run, not the source of truth. The cache index maps cache keys to store entries.

## Dependencies

- Task 106: Workflow Iteration Cache — must be implemented first. This task unifies the cache storage with the trace storage.
- Task 108: Smart Trace Debug Output — the current trace system that would be restructured.

## Design Decisions

(To be made during implementation. Key questions to resolve:)
- Content-addressed (hash of content) vs execution-addressed (run ID + node ID)?
- How to efficiently assemble a full trace report from per-node files?
- How to handle trace file deletion (should store entries be independent of trace lifecycle?)
- Impact on `--report` flag and trace file writing

## References

- Task 106 task file: `.taskmaster/tasks/task_106/task-106.md` — section on "Cache File Design Note"
- Task 106 braindump: `.taskmaster/tasks/task_106/starting-context/braindump-design-discussion-20260324.md` — section on trace duplication discussion
- Trace system: `src/pflow/runtime/workflow_trace.py`
- Trace report: `src/pflow/core/trace_report.py`
