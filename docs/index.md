# pflow Documentation

[![Release](https://img.shields.io/github/v/release/spinje/pflow)](https://img.shields.io/github/v/release/spinje/pflow)
[![Build status](https://img.shields.io/github/actions/workflow/status/spinje/pflow/main.yml?branch=main)](https://github.com/spinje/pflow/actions/workflows/main.yml?query=branch%3Amain)
[![Commit activity](https://img.shields.io/github/commit-activity/m/spinje/pflow)](https://img.shields.io/github/commit-activity/m/spinje/pflow)
[![License](https://img.shields.io/github/license/spinje/pflow)](https://img.shields.io/github/license/spinje/pflow)

> **pflow** is a workflow compiler that transforms natural language and CLI pipe syntax into permanent, deterministic CLI commands. It follows a "Plan Once, Run Forever" philosophy - capturing user intent once and compiling it into reproducible workflows that run instantly without AI overhead.

## Contents

- [Quick Start](#quick-start)
- [Documentation Structure](#documentation-structure)
- [Example Workflows](#example-workflows)
- [Find What You Need](#find-what-you-need)
- [Learning Paths](#learning-paths)
- [Key Design Principles](#key-design-principles)
- [Version Guide](#version-guide)
- [Contributing](#contributing)

## Quick Start

### 🚀 New to pflow?
1. [Workflow Analysis](./features/workflow-analysis.md) - Understand the problem pflow solves
2. [MVP Scope](./features/mvp-scope.md) - Learn what pflow can do
3. [Architecture](./architecture/architecture.md) - See how it works

### ⚡ For CLI Users
- [CLI Reference](./reference/cli-reference.md) - Complete command syntax and operators
- [Quick Examples](#example-workflows) - See pflow in action
- [Shell Integration](./features/shell-pipes.md) - Unix pipe support

### 💻 For Developers
- [Node Reference](./reference/node-reference.md) - Build custom nodes
- [Shared Store](./core-concepts/shared-store.md) - Understand data flow
- [Node Packages](./core-node-packages/) - Example implementations

## Documentation Structure

### 📋 Core Documentation

| Document | Purpose | Start Here If... |
|----------|---------|------------------|
| [PRD](./prd.md) | Master product vision and strategy | You want the complete vision |
| [Architecture](./architecture/architecture.md) | Technical implementation for MVP | You're implementing pflow |
| [MVP Scope](./features/mvp-scope.md) | Clear boundaries and success criteria | You need to know what's included |

### 🏗️ Core Patterns

| Pattern | Purpose | Key Concept |
|---------|---------|-------------|
| [Shared Store](./core-concepts/shared-store.md) | Inter-node communication pattern | Natural interfaces with `shared["key"]` |
| [Simple Nodes](./features/simple-nodes.md) | Node design philosophy | One node, one purpose |
| [CLI Runtime](./features/cli-runtime.md) | Execution specification | Type flags; engine decides |

### 🧩 System Components

| Component | Purpose | MVP Status |
|-----------|---------|------------|
| [Planner](./features/planner.md) | Natural language → CLI workflow | ✅ MVP |
| [Runtime](./core-concepts/runtime.md) | Caching and execution engine | ✅ MVP |
| [Registry](./core-concepts/registry.md) | Node discovery and versioning | ✅ MVP |
| [Components](./architecture/components.md) | Complete component inventory | Reference |
| [Schemas](./core-concepts/schemas.md) | JSON IR and metadata schemas | ✅ MVP |

### 📦 Node Packages

| Package | Nodes | Purpose |
|---------|-------|---------|
| [GitHub](./core-node-packages/github-nodes.md) | 8 nodes | GitHub API operations |
| [Claude](./core-node-packages/claude-nodes.md) | 1 super node | AI development tasks |
| [CI](./core-node-packages/ci-nodes.md) | 5 nodes | Testing and builds |
| [LLM](./core-node-packages/llm-nodes.md) | 1 node | General text processing |

### 📚 Reference Documentation

| Document | Purpose | Quick Links |
|----------|---------|-------------|
| [Node Reference](./reference/node-reference.md) | Complete guide to building nodes | [Lifecycle](./reference/node-reference.md#node-lifecycle) • [Patterns](./reference/node-reference.md#node-patterns) • [Testing](./reference/node-reference.md#testing-nodes) |
| [CLI Reference](./reference/cli-reference.md) | Command syntax and operators | [Syntax](./reference/cli-reference.md#command-syntax) • [Operators](./reference/cli-reference.md#operators) • [Examples](./reference/cli-reference.md#examples) |
| [Execution Reference](./reference/execution-reference.md) | Runtime behavior specification | [Flow](./reference/execution-reference.md#execution-flow) • [Errors](./reference/execution-reference.md#error-handling) • [Caching](./reference/execution-reference.md#caching) |

### 🔧 Implementation Guides

- [PocketFlow Integration](./architecture/pflow-pocketflow-integration-guide.md) - Critical insights for correct implementation
- [Shell Pipes](./features/shell-pipes.md) - Unix pipe integration
- [Metadata Extraction](./implementation-details/metadata-extraction.md) - Node discovery system

### 🚀 Future Features

| Feature | Version | Status |
|---------|---------|--------|
| [MCP Integration](./features/mcp-integration.md) | v2.0 | ❌ Deferred |
| [CLI Autocomplete](./features/autocomplete.md) | v2.0 | ❌ Deferred |
| [JSON Extraction](./future-version/json-extraction.md) | v3.0 | ⏳ Future |
| [LLM Node Gen](./future-version/llm-node-gen.md) | v3.0 | ⏳ Future |

## Example Workflows

### 📝 Text Processing
```bash
# Transform error logs into actionable insights
pflow read-file --path=error.log >> \
      llm --prompt="extract error patterns and suggest fixes" >> \
      write-file --path=analysis.md
```

### 🐙 GitHub Issue to PR
```bash
# Convert issue into pull request with implementation
pflow github-get-issue --issue=1234 >> \
      claude-code --prompt="implement the requested feature" >> \
      github-create-pr --title="Fix: Issue #1234"
```

### 🔄 CI Integration
```bash
# Run tests and create report
pflow ci-run-tests --suite=unit >> \
      llm --prompt="summarize test failures" >> \
      write-file --path=test-report.md
```

See [CLI Reference](./reference/cli-reference.md#examples) for more examples.

## Find What You Need

### ❓ Common Tasks

| I want to... | Start here |
|--------------|------------|
| Write my first pflow command | [CLI Reference](./reference/cli-reference.md#getting-started) |
| Create a custom node | [Node Reference](./reference/node-reference.md) + [Simple Nodes](./features/simple-nodes.md) |
| Understand how data flows | [Shared Store](./core-concepts/shared-store.md) |
| Debug a failing workflow | [Execution Reference](./reference/execution-reference.md#error-handling) |
| Use natural language | [Planner](./features/planner.md) |
| Integrate with shell scripts | [Shell Pipes](./features/shell-pipes.md) |

### 🔧 Troubleshooting

| Problem | Solution |
|---------|----------|
| Command syntax errors | Check [CLI Reference](./reference/cli-reference.md#command-syntax) |
| Node not found | See [Registry](./core-concepts/registry.md#node-discovery) |
| Shared store key missing | Review [Shared Store](./core-concepts/shared-store.md#debugging) |
| Execution failures | Consult [Execution Reference](./reference/execution-reference.md#error-codes) |

## Concept Quick Reference

### 📖 Reference Documents

- **Node Lifecycle** → [node-reference.md](./reference/node-reference.md#node-lifecycle) - prep/exec/post phases
- **CLI Syntax** → [cli-reference.md](./reference/cli-reference.md#command-syntax) - Complete grammar
- **Execution Model** → [execution-reference.md](./reference/execution-reference.md) - Runtime behavior

### Core Concepts

- **Shared Store** → [shared-store.md](./core-concepts/shared-store.md) - Flow-scoped dictionary for node communication
- **Template Variables** → [shared-store.md#template-variable-resolution](./core-concepts/shared-store.md#template-variable-resolution) - `$variable` syntax for dynamic content
- **Simple Nodes** → [simple-nodes.md](./features/simple-nodes.md) - Single-purpose node architecture
- **NodeAwareSharedStore Proxy** → [shared-store.md#nodeawaresharedstore-proxy](./core-concepts/shared-store.md#nodeawaresharedstore-proxy) - Transparent key mapping
- **Natural Interfaces** → [shared-store.md#node-autonomy-principle](./core-concepts/shared-store.md#node-autonomy-principle) - Intuitive key names

### Planning & Validation

- **Dual-Mode Planner** → [planner.md](./features/planner.md) - Natural language and CLI paths
- **JSON IR** → [schemas.md](./core-concepts/schemas.md) - Intermediate representation format
- **Metadata System** → [schemas.md#node-metadata-schema](./core-concepts/schemas.md#node-metadata-schema) - Node interface definitions
- **Registry** → [registry.md](./core-concepts/registry.md) - Node discovery and versioning

### Execution

- **Runtime Engine** → [runtime.md](./core-concepts/runtime.md) - Flow execution with caching
- **CLI Parser** → [cli-runtime.md](./features/cli-runtime.md) - Command parsing and resolution
- **Shell Integration** → [shell-pipes.md](./features/shell-pipes.md) - Unix pipe support

## Learning Paths

### 🎯 For Product Understanding
1. [Workflow Analysis](./features/workflow-analysis.md) - Problem space
2. [MVP Scope](./features/mvp-scope.md) - Solution vision
3. [PRD](./prd.md) - Complete product strategy

### 💻 For Implementation
1. [PocketFlow Integration Guide](./architecture/pflow-pocketflow-integration-guide.md) - Critical insights
2. [Shared Store](./core-concepts/shared-store.md) - Core pattern
3. [Architecture](./architecture/architecture.md) - System design
4. [Components](./architecture/components.md) - What to build

### 🔌 For Node Development
1. [Node Reference](./reference/node-reference.md) - Complete implementation guide
2. [Simple Nodes](./features/simple-nodes.md) - Design philosophy
3. [Shared Store](./core-concepts/shared-store.md) - Communication pattern
4. [Node Package Examples](./core-node-packages/) - Reference implementations

### ⚡ For CLI Power Users
1. [CLI Reference](./reference/cli-reference.md) - Master the syntax
2. [Shell Pipes](./features/shell-pipes.md) - Unix integration
3. [Execution Reference](./reference/execution-reference.md) - Understand runtime
4. [Example Workflows](#example-workflows) - Learn by doing

## Key Design Principles

1. **Plan Once, Run Forever** - Transform AI reasoning into permanent workflows
2. **Natural Interfaces** - Nodes use intuitive keys like `shared["text"]`
3. **Simple Nodes** - Each node does one thing well
4. **Deterministic Execution** - Same inputs → same outputs
5. **Progressive Complexity** - Simple flows stay simple, complex flows are possible

## Version Guide

- **MVP (v0.1)** - Local CLI execution with natural language planning
- **v2.0** - MCP integration, autocomplete, conditional flows
- **v3.0+** - Cloud platform, marketplace, advanced features

See [MVP Scope](./features/mvp-scope.md) for detailed version boundaries.

## Contributing

### 📝 Documentation Guidelines

When adding new documentation:
1. **Choose the right location**:
   - `reference/` - Authoritative specifications
   - `core-concepts/` - Fundamental patterns
   - `architecture/` - System design documents
   - `features/` - Feature specifications
   - `core-node-packages/` - Node package docs

2. **Follow standards**:
   - Include version header using the [template](./features/mvp-scope.md#version-header-template)
   - Add navigation section with related links
   - Include "See Also" section at the end
   - Use single-source-of-truth principle

3. **Update navigation**:
   - Add to this index in appropriate section
   - Update cross-references in related docs
   - Verify all links work correctly

### 🔍 Documentation Structure

```
docs/
├── reference/           # Authoritative references
├── core-concepts/       # Fundamental patterns
├── architecture/        # System design
├── features/           # Feature specifications
├── core-node-packages/ # Platform nodes
├── implementation-details/ # Detailed guides
└── future-version/     # Post-MVP features
```

---

*This documentation follows a single-source-of-truth principle. Each concept has one canonical document, with other documents linking to it rather than duplicating content.*
