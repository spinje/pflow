# Archived Research Documents

**Archived**: 2024-12-21

These documents contain historical research that has been superseded or contains inaccuracies identified during verification.

## Why Archived

### `implementation-options-comparison.md`
- **Issue**: Conflates data parallelism (BatchNode) with task parallelism (fan-out/fan-in)
- **Issue**: Contains incorrect claim that parameter passing modification "blocks" BatchFlow
- **Issue**: Options A and D discuss batch processing, which is now Task 96
- **Useful Content**: The phased approach recommendation is sound, but needs separation by task

### `parallel-execution-deep-analysis.md`
- **Issue**: Conflates data parallelism with task parallelism
- **Issue**: Claims parameter passing modification is a "Critical Blocker" - this is FALSE
- **Issue**: Suggests using BatchNode/BatchFlow for task parallelism - this is WRONG
- **Useful Content**: PocketFlow class documentation is accurate (extracted to Task 96)
- **Useful Content**: Types of parallelism section is accurate

## Verified Findings

The following was verified during a deep-dive session:

1. **Parameter Passing NOT a Blocker**:
   - The modification only affects sync `Flow._orch()`, not async `_orch_async()`
   - BatchFlow always passes explicit params, so the conditional is always True
   - `AsyncParallelBatchFlow` uses unmodified async path

2. **Two Types of Parallelism**:
   - Data parallelism (Task 96): Same operation × N items → Use PocketFlow's BatchNode
   - Task parallelism (Task 39): N different operations × same data → Must build custom

3. **PocketFlow Doesn't Support Fan-Out**:
   - `node.successors[action] = target` only stores ONE successor per action
   - Task parallelism requires custom implementation

## Where This Content Went

- BatchNode/BatchFlow documentation → `task_96/research/pocketflow-batch-capabilities.md`
- Task parallelism analysis → Incorporated into updated Task 39 spec
- Verified findings → `session-verification-summary.md`
