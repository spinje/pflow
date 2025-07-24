# Task 17: Natural Language Planner - Document Overview

The Natural Language Planner is the heart of pflow's "Plan Once, Run Forever" philosophy. It transforms user intent expressed in natural language into deterministic, reusable workflows that can be executed repeatedly with different parameters.

This meta-workflow system orchestrates the entire lifecycle of workflow creation through two distinct paths:
- **Path A**: Discovers and reuses existing workflows that match user intent
- **Path B**: Generates new workflows when no suitable match exists

Both paths converge at a critical parameter extraction and verification point, ensuring that workflows only execute when all required inputs are available. The planner uses PocketFlow internally for its complex orchestration needs while generating simple, linear workflows for users.

Key innovations include:
- **Template variables with path support** (`$data.field.subfield`) for flexible data access
- **Smart context loading** that prevents LLM overwhelm while enabling discovery
- **Three-tier validation** ensuring generated workflows are both syntactically and semantically correct
- **Structured output generation** using Pydantic models with Simon Willison's LLM library
- **MVP focus on sequential workflows** with branching deferred to v2.0

This document set provides comprehensive guidance for implementing the planner, from high-level architecture to concrete code examples.

## Getting Started

Task 17: Natural Language Planner - Context and Implementation Details

> **First step:** Read these core docs *in full* and make sure you deeply understand them:
>
> * `.taskmaster/tasks/task_17/task-17-architecture-and-patterns.md`
> * `.taskmaster/tasks/task_17/task-17-implementation-guide.md`
> * `.taskmaster/tasks/task_17/task-17-core-concepts.md`

## Document Structure

Three focused files for better organization:

1. **task-17-architecture-and-patterns.md** - Core architecture, design patterns, and anti-patterns
   - Meta-workflow architecture with two paths
   - PocketFlow usage rationale
   - Advanced implementation patterns
   - Comprehensive anti-patterns list

2. **task-17-implementation-guide.md** - Implementation details, code examples, and integration
   - LLM integration with structured output
   - Prompt templates and context building
   - Testing strategies and hybrid test approach
   - Concrete integration examples
   - CLI integration patterns and batch mode handling
   - Parameter detection and routing

3. **task-17-core-concepts.md** - Critical concepts, constraints, and decision rationale
   - Template variable system and constraints
   - Parameter extraction as verification
   - Risk mitigation strategies
   - Success metrics
   - Implementation recommendations and resolutions
   - MVP feature boundaries and scope
