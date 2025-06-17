# pflow Documentation

[![Release](https://img.shields.io/github/v/release/spinje/pflow)](https://img.shields.io/github/v/release/spinje/pflow)
[![Build status](https://img.shields.io/github/actions/workflow/status/spinje/pflow/main.yml?branch=main)](https://github.com/spinje/pflow/actions/workflows/main.yml?query=branch%3Amain)
[![Commit activity](https://img.shields.io/github/commit-activity/m/spinje/pflow)](https://img.shields.io/github/commit-activity/m/spinje/pflow)
[![License](https://img.shields.io/github/license/spinje/pflow)](https://img.shields.io/github/license/spinje/pflow)

> **pflow** is a workflow compiler that transforms natural language and CLI pipe syntax into permanent, deterministic CLI commands. It follows a "Plan Once, Run Forever" philosophy - capturing user intent once and compiling it into reproducible workflows that run instantly without AI overhead.

## Quick Start

**New to pflow?** Start here:
1. [Workflow Analysis](./workflow-analysis.md) - Understand the problem pflow solves
2. [MVP Scope](./mvp-scope.md) - Learn what pflow can do
3. [Architecture](./architecture.md) - See how it works

## Documentation Structure

### 📋 Core Documentation

| Document | Purpose | Start Here If... |
|----------|---------|------------------|
| [PRD](./prd.md) | Master product vision and strategy | You want the complete vision |
| [Architecture](./architecture.md) | Technical implementation for MVP | You're implementing pflow |
| [MVP Scope](./mvp-scope.md) | Clear boundaries and success criteria | You need to know what's included |

### 🏗️ Core Patterns

| Pattern | Purpose | Key Concept |
|---------|---------|-------------|
| [Shared Store](./shared-store.md) | Inter-node communication pattern | Natural interfaces with `shared["key"]` |
| [Simple Nodes](./simple-nodes.md) | Node design philosophy | One node, one purpose |
| [CLI Runtime](./cli-runtime.md) | Execution specification | Type flags; engine decides |

### 🧩 System Components

| Component | Purpose | MVP Status |
|-----------|---------|------------|
| [Planner](./planner.md) | Natural language → CLI workflow | ✅ MVP |
| [Runtime](./runtime.md) | Execution engine | ✅ MVP |
| [Registry](./registry.md) | Node discovery and versioning | ✅ MVP |
| [Components](./components.md) | Complete component inventory | Reference |
| [Schemas](./schemas.md) | JSON IR and metadata schemas | ✅ MVP |

### 📦 Node Packages

| Package | Nodes | Purpose |
|---------|-------|---------|
| [GitHub](./core-node-packages/github-nodes.md) | 8 nodes | GitHub API operations |
| [Claude](./core-node-packages/claude-nodes.md) | 1 super node | AI development tasks |
| [CI](./core-node-packages/ci-nodes.md) | 5 nodes | Testing and builds |
| [LLM](./core-node-packages/llm-nodes.md) | 1 node | General text processing |

### 🔧 Implementation Guides

- [PocketFlow Integration](./pflow-pocketflow-integration-guide.md) - Critical insights for correct implementation
- [Shell Pipes](./shell-pipes.md) - Unix pipe integration
- [Metadata Extraction](./implementation-details/metadata-extraction.md) - Node discovery system

### 🚀 Future Features

| Feature | Version | Status |
|---------|---------|--------|
| [MCP Integration](./mcp-integration.md) | v2.0 | ❌ Deferred |
| [CLI Autocomplete](./implementation-details/autocomplete-impl.md) | v2.0 | ❌ Deferred |
| [JSON Extraction](./future-version/json-extraction.md) | v3.0 | ⏳ Future |
| [LLM Node Gen](./future-version/llm-node-gen.md) | v3.0 | ⏳ Future |

## Concept Quick Reference

### Core Concepts

- **Shared Store** → [shared-store.md](./shared-store.md) - Flow-scoped dictionary for node communication
- **Template Variables** → [shared-store.md#template-variable-resolution](./shared-store.md#template-variable-resolution) - `$variable` syntax for dynamic content
- **Simple Nodes** → [simple-nodes.md](./simple-nodes.md) - Single-purpose node architecture
- **NodeAwareSharedStore Proxy** → [shared-store.md#nodeawaresharedstore-proxy](./shared-store.md#nodeawaresharedstore-proxy) - Transparent key mapping
- **Natural Interfaces** → [shared-store.md#node-autonomy-principle](./shared-store.md#node-autonomy-principle) - Intuitive key names

### Planning & Validation

- **Dual-Mode Planner** → [planner.md](./planner.md) - Natural language and CLI paths
- **JSON IR** → [schemas.md](./schemas.md) - Intermediate representation format
- **Metadata System** → [schemas.md#node-metadata-schema](./schemas.md#node-metadata-schema) - Node interface definitions
- **Registry** → [registry.md](./registry.md) - Node discovery and versioning

### Execution

- **Runtime Engine** → [runtime.md](./runtime.md) - Flow execution with caching
- **CLI Parser** → [cli-runtime.md](./cli-runtime.md) - Command parsing and resolution
- **Shell Integration** → [shell-pipes.md](./shell-pipes.md) - Unix pipe support

## Learning Paths

### 🎯 For Product Understanding
1. [Workflow Analysis](./workflow-analysis.md) - Problem space
2. [MVP Scope](./mvp-scope.md) - Solution vision
3. [PRD](./prd.md) - Complete product strategy

### 💻 For Implementation
1. [PocketFlow Integration Guide](./pflow-pocketflow-integration-guide.md) - Critical insights
2. [Shared Store](./shared-store.md) - Core pattern
3. [Architecture](./architecture.md) - System design
4. [Components](./components.md) - What to build

### 🔌 For Node Development
1. [Simple Nodes](./simple-nodes.md) - Design philosophy
2. [Shared Store](./shared-store.md) - Communication pattern
3. [Node Package Examples](./core-node-packages/) - Reference implementations

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

See [MVP Scope](./mvp-scope.md) for detailed version boundaries.

## Contributing

When adding new documentation:
1. Include version header using the [template](./mvp-scope.md#version-header-template)
2. Add navigation section linking to related docs
3. Update this index with your new document
4. Add cross-references to existing docs where relevant
5. Include a "See Also" section at the end

---

*This documentation follows a single-source-of-truth principle. Each concept has one canonical document, with other documents linking to it rather than duplicating content.*
