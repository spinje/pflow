# pflow PRD Version Differences Analysis

This document analyzes the differences between the three versions of the pflow Product Requirements Document:

- `PRD-pflow.md` (376 lines) - Base version
- `PRD-pflow-2.md` (374 lines) - Version 2
- `PRD-pflow-3.md` (359 lines) - Version 3

## Executive Summary

The three PRD versions show an evolution of the pflow CLI specification with the following key trends:

1. **PRD-pflow-2.md** adds the most detailed planner specifications and protocol transparency
2. **PRD-pflow-3.md** simplifies the planner interface and adds more structured CLI commands
3. **PRD-pflow.md** provides the base specification with simpler planning concepts

## Detailed Differences

### 1. Header and Title

| Version | Title Format |
|---------|--------------|
| PRD-pflow.md | `# Product Requirements Document: pflow CLI` |
| PRD-pflow-2.md | `# Product Requirements Document: pflow CLI` |
| PRD-pflow-3.md | Missing the main title header completely |

**Impact**: PRD-pflow-3.md appears to be missing its document title, suggesting it may be an incomplete version.

### 2. Strategic Differentiators Table

**PRD-pflow-2.md adds a unique differentiator:**

- **Planner Protocol Transparency**: "Planning itself is a version-pinned PocketFlow sub-DAG with deterministic retry-budget and explicit failure codes."

**Common differences:**

- **NL ↔ Flow Round-Tripping** implementation details vary:
  - PRD-pflow.md: "future `--explain` command"
  - PRD-pflow-2.md: "future `--explain` command"
  - PRD-pflow-3.md: "`description` metadata" (no mention of future command)

### 3. Design Philosophy

**Key difference in "Controlled Flexibility":**

- **PRD-pflow.md**: Lists "param overrides" only
- **PRD-pflow-2.md**: Adds "model selection (`--model`)" explicitly
- **PRD-pflow-3.md**: Lists "param overrides" only

**"Round-Trippable Intent" differences:**

- **PRD-pflow.md**: "future `--explain` reverse mapping"
- **PRD-pflow-2.md**: "future `--explain` reverse mapping"
- **PRD-pflow-3.md**: "the `--explain` command" (present tense)

**"Immutable Graph, Mutable Data" differences:**

- **PRD-pflow.md**: "This enables planner reuse without graph mutations"
- **PRD-pflow-2.md**: "Config overrides create a *snapshot hash*; cache keys incorporate both flow hash and snapshot hash, so overrides always invalidate cached outputs"
- **PRD-pflow-3.md**: "Config overrides change node input hashes and therefore invalidate cache but do not mutate the DAG structure"

### 4. Natural-Language Planning Pipeline

**Major architectural differences:**

**PRD-pflow.md (Simple 8-step process):**

1. Capture
2. Plan (searches library first, generation as fallback)
3. Shadow Validate
4. User Preview
5. Compile
6. Full Validate
7. Persist
8. Execute

**PRD-pflow-2.md (Detailed 9-step process):**

1. Capture
2. Plan Step 1 – Pipe Draft (LLM + validator lint)
3. Plan Step 2 – IR Draft (second LLM call)
4. Shadow Validate
5. User Preview
6. Compile
7. Full Validate
8. Persist (includes `planner_log_path`)
9. Execute

**PRD-pflow-3.md (Structured 8-step process):**

1. Capture
2. Plan (broken into two LLM stages with explicit retrieval)
3. Shadow Validate
4. User Preview
5. Compile (includes CLI args mapping)
6. Full Validate
7. Persist (includes `llm_model`)
8. Execute

**Key differences:**

- **PRD-pflow-2.md** has the most detailed step-by-step LLM process
- **PRD-pflow-3.md** adds formal "Agent Protocol & Contract" and "Planner Prompting Strategy" sections
- **PRD-pflow-2.md** includes a "Planner Contract" overview

### 5. CLI Command Interface

**Model parameter handling:**

- **PRD-pflow.md**: No model parameter mentioned in CLI
- **PRD-pflow-2.md**: `[--model claude-3-sonnet]` with note about planner LLM model
- **PRD-pflow-3.md**: Uses `--planner-model=<model>` and `--planner-verbose` flags

**Command table format:**

- **PRD-pflow.md** & **PRD-pflow-3.md**: Standard 2-column table
- **PRD-pflow-2.md**: 3-column table with additional "Notes" column

### 6. Out-of-Scope Items

**PRD-pflow-2.md adds a unique exclusion:**

- **CLI flow search** (`pflow search`): "First iteration exposes discovery via Python API & LLM routing; CLI search reserved for later roadmap."

This item is not mentioned in the other versions.

### 7. Core Concepts - CLI Parameter Resolution

**Config override behavior:**

- **PRD-pflow.md**: "does **not** change the flow hash"
- **PRD-pflow-2.md**: "config override always invalidates node cache"
- **PRD-pflow-3.md**: "invalidates cache"

### 8. Execution Semantics - Caching

**Cache key composition:**

- **PRD-pflow.md**: `SHA-256(node-type + params + input hash)`
- **PRD-pflow-2.md**: `SHA-256(node-type + params + input hash + snapshot hash)`
- **PRD-pflow-3.md**: `SHA-256(node-type + params + input hash)` with note about config overrides

### 9. Flow Definitions

**PRD-pflow-3.md adds:**

- **Saved flows** can be referenced by name: `pflow myflow >> summarize`

This feature is not explicitly mentioned in the other versions.

### 10. NL → Flow Guarantees

**PRD-pflow-2.md adds a unique guarantee:**

- **Config override invalidates cache**: "Snapshot hash merged into cache key; overrides noted in run-log"

### 11. MCP Integration

**PRD-pflow-2.md has a note:**

- "*(Unchanged; retained for completeness.)*"

This suggests PRD-pflow-2.md might be documenting changes from a previous version.

### 12. User Journey

**Reuse step:**

- **PRD-pflow.md**: Missing the "Reuse" step
- **PRD-pflow-2.md**: Includes explicit "Reuse" step with `pflow myWeatherFlow >> summarize`
- **PRD-pflow-3.md**: Missing the "Reuse" step

**Automation step:**

- **PRD-pflow.md**: `--use-cache` only
- **PRD-pflow-2.md**: `--use-cache --model claude-3-sonnet`
- **PRD-pflow-3.md**: `--use-cache` only

### 13. MVP Acceptance Criteria

**PRD-pflow-2.md includes additional metrics:**

- **Planner generation pass rate within 4 retries**: ≥ 95%
- **Retrieval hit-rate on repeated prompts**: ≥ 90%

**PRD-pflow-3.md adds:**

- **Planner retrieval hit-rate on repeated prompts**: ≥ 90%
- **Planner generation passes full validation**: ≥ 95% within 4 retries
- **Average planner latency (local LLM)**: ≤ 800 ms
- **Incidence of `MISSING_INPUT` in non-interactive CI**: 0

### 14. Roadmap

**PRD-pflow-2.md adds:**

- **Semantic flow search CLI** (`pflow search`) as item #5

### 15. Open Risks

**PRD-pflow-2.md adds a unique risk:**

- **Over-complex planner prompts**: "Two-step modular design, small retry budget, explicit telemetry to refine prompts."

### 16. Appendix

**PRD-pflow-2.md is the only version with an appendix:**

- **Appendix A – Planner Specification (condensed)**: Detailed table covering Architecture, Retrieval, Generation, Failure Codes, Parameter Resolution, Logging, Trust Levels, and Metrics Targets.

## Summary of Version Evolution

1. **PRD-pflow.md**: Base specification with simple planner concepts
2. **PRD-pflow-2.md**: Most comprehensive version with detailed planner protocols, additional metrics, and appendix
3. **PRD-pflow-3.md**: Refined version with structured agent protocols but missing title and some features

**Most complete version**: PRD-pflow-2.md (includes appendix and most detailed specifications)
**Most structured version**: PRD-pflow-3.md (formal agent protocols and contracts)
**Base version**: PRD-pflow.md (simplest implementation concepts)
