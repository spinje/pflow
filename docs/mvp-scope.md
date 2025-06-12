# MVP Scope

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
