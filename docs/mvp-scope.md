# MVP Scope

## ✅ MVP CLI Goals

Claude must prioritize features that enable a local developer to:

- Compose and run flows using `pflow` CLI
- Define simple nodes (like `prompt`, `transform`, `read_file`)
- Store intermediate data in a shared store
- Use shell pipe syntax for stdin/stdout integration

The system must be:

- Pure Python
- Single-machine
- Stateless

---

## ❌ Excluded from MVP (Do *Not* Build Yet)

These are part of version 2.0 of pflow, post MVP:

- Conditional transitions (e.g. `node - "fail" >> error_handler`)
- LLM-based natural language planning
- CLI autocomplete and shadow-store suggestions
- async nodes and flows

These are part of the future cloud platform, pflow 3.0:

- Authentication, multi-user access
- Remote node discovery (e.g. from MCP servers)
- Namespaced and versioned node resolution (like `core/summarize@1.2.0`)
- Secure MCP authentication and permissions
- Cloud execution, job queues, and async scheduling
- Web UI or dashboards
- Interactive prompting for missing shared inputs
- IR mutation tools (e.g. repair, diff, version upgrades)

These can be mocked or scaffolded, but **not implemented** now.

## MVP Components (What we're building now)

- Core Foundation - pocketflow integration, shared store, proxy pattern
- CLI Interface - Basic commands, pipe syntax parser, shell integration
- Node System - Registry, metadata, and essential built-in nodes
- Planning & Validation - CLI path only (no LLM yet, that comes in version 2.0)
- Execution Engine - Synchronous runtime with basic caching
- Observability - Tracing and logging for debugging
- Storage - Lockfiles and local filesystem
- Testing - Basic test framework
- Documentation - Built-in help system

## Critical MVP Dependencies

10 absolutely essential components that MUST be in MVP for pflow to deliver on its core promises:

- pocketflow framework
- Shared store pattern (included in pocketflow)
- CLI pipe syntax
- Node registry
- JSON IR
- Validation
- Tracing
- Shell pipes
- Error reporting
- Lockfiles
