# pflow Version History

This file tracks completed milestones with completion dates.
For planned tasks, see `CLAUDE.md`. For task details, see `.taskmaster/tasks/task_N/`.

---

## Completed

### v0.1 - Foundation (June 2025)
Core CLI that can parse and execute workflows from JSON.

- Task 1: Package setup and CLI entry point (2025-06-27)
- Task 2: Basic CLI run command with stdio/stdin (2025-06-28)
- Task 4: IR-to-PocketFlow Converter (2025-06-29)
- Task 5: Node discovery and registry (2025-06-29)
- Task 6: Define JSON IR schema (2025-06-29)
- Task 11: File nodes - read/write (2025-06-30)

### v0.2 - Nodes & Templates (July 2025)
Node metadata, core nodes, and template system.

- Task 3: Hello World Workflow (2025-07-08)
- Task 7: Extract node metadata from docstrings (2025-07-08)
- Task 8: Shell pipe integration stdin/stdout (2025-07-10)
- Task 14: Interface documentation for nodes (2025-07-17)
- Task 15: Two-phase context builder (2025-07-19)
- Task 18: Template Variable System ${var} (2025-07-26)
- Task 19: Node Interface Registry for validation (2025-07-27)
- Task 20: Nested Workflow Execution (2025-07-28)
- Task 21: Workflow Input/Output Declaration (2025-07-29)
- Task 30: Refactor validation from compiler (2025-07-29)
- Task 24: Workflow Manager - save/load/resolve (2025-07-30)

### v0.3 - Nodes & Validation (August 2025 - early)
Additional nodes and validation improvements.

- Task 12: LLM Node (2025-08-03)
- Task 26: Git and GitHub nodes (2025-08-03)
- Task 33: Extract planner prompts to markdown (2025-08-15)
- Task 9: Shared store collision detection (2025-08-16)
- Task 35: Template syntax migration $ → ${} (2025-08-16)

### v0.4 - Planner (August 2025 - mid)
Natural language to workflow generation.

- Task 16: Planning context builder (unknown)
- Task 17: Natural Language Planner System (2025-08-17)
- Task 27: Planner debugging capabilities (2025-08-17)
- Task 31: Test infrastructure refactor (2025-08-17)
- Task 34: Prompt accuracy tracking (2025-08-17)
- Task 36: Context builder namespacing clarity (2025-08-18)
- Task 37: API Error Handling (2025-08-21)
- Task 28: Planner prompt performance (2025-08-24)
- Task 40: Unified Workflow Validation (2025-08-24)
- Task 41: Shell Node (2025-08-25)
- Task 10: Registry CLI commands (2025-08-30)
- Task 32: Metrics and Tracing System (2025-08-30)
- Task 50: Node Filtering System (2025-08-31)

### v0.5 - MCP & Polish (September 2025)
MCP integration and CLI polish.

- Task 22: Named Workflow Execution (2025-09-01)
- Task 43: MCP Server support (2025-09-02)
- Task 53: Rerun Command Display (2025-09-02)
- Task 54: HTTP Node (2025-09-03)
- Task 55: Output Control interactive/non-interactive (2025-09-04)
- Task 57: Planner integration tests (2025-09-05)
- Task 42: Claude Code Agentic Node (2025-09-07)
- Task 58: Workflow generator tests (2025-09-09)
- Task 52: Plan and requirements steps (2025-09-14)
- Task 47: MCP http transport (2025-09-18)
- Task 67: MCP Standard Format compatibility (2025-09-19)
- Task 56: Runtime validation feedback loop (2025-09-21)
- Task 68: Separate RuntimeValidation from planner (2025-09-29)
- Task 63: Pre-Execution Risk Assessment (unknown)

### v0.6 - Agent Support (October 2025)
Agent-friendly tooling and MCP server.

- Task 70: MCP-Based Agent Infrastructure design (2025-10-02)
- Task 71: CLI commands for agent workflow building (2025-10-03)
- Task 76: Registry Execute Command (2025-10-06)
- Task 80: API Key Management (2025-10-09)
- Task 82: Binary Data Support (2025-10-10)
- Task 72: MCP Server for pflow (2025-10-12)
- Task 84: Schema-Aware Type Checking (2025-10-20)
- Task 85: Template Resolution Hardening (2025-10-20)
- Task 83: Security Audit (unknown)

### v0.7 - Production Ready (Nov 2025 - Jan 2026)
Documentation, final hardening, release preparation.

- Task 89: Structure-Only Mode (2025-11-17)
- Task 93: Mintlify Documentation (2025-12-16)
- Task 95: Unify LLM via llm library (2025-12-19)
- Task 96: Batch Processing (2025-12-27)
- Task 102: Remove Parameter Fallback (2025-12-30)
- Task 103: Preserve Inline Object Type (2026-01-01)
- Task 105: Auto-Parse JSON Strings (2026-01-02)

---

## Deprecated
- Task 60: Gemini models for planner (superseded by Task 95)
- Task 61: Fast Mode for Planner
- Task 69: Refactor Repair to Pocketflow
- Task 73: Checkpoint Persistence (superseded by Task 106)
