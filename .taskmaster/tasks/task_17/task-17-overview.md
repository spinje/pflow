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

## Documentation Summary

We have **9 comprehensive documents** organized into three categories:

1. **Core Documentation (4 docs)**: The foundation - architecture, implementation guide, core concepts, and standardized conventions
2. **Planning & Design (2 docs)**: Resolved ambiguities and subtask decomposition
3. **Implementation Resources (3 docs)**: Practical patterns, PocketFlow insights, and debugging principles

Each document serves a specific purpose in the implementation journey, from understanding the system to debugging production issues.

## Document Organization

### Core Documentation (Foundation)

These four documents form the foundation - **read them first in full**:

1. **task-17-standardized-conventions.md** - Consolidated guidelines resolving documentation conflicts
   - Recommended shared store schema
   - Parameter flow and terminology
   - Action strings for routing
   - Model configuration
   - File structure conventions

2. **task-17-architecture-and-patterns.md** - Core architecture, design patterns, and anti-patterns
   - Meta-workflow architecture with two paths
   - PocketFlow usage rationale
   - Advanced implementation patterns
   - Comprehensive anti-patterns list

3. **task-17-implementation-guide.md** - Implementation details, code examples, and integration
   - LLM integration with structured output
   - Prompt templates and context building
   - Testing strategies and hybrid test approach
   - Concrete integration examples
   - CLI integration patterns and batch mode handling
   - Parameter detection and routing

4. **task-17-core-concepts.md** - Critical concepts, constraints, and decision rationale
   - Template variable system and constraints
   - Parameter extraction as verification
   - Risk mitigation strategies
   - Success metrics
   - Implementation recommendations and resolutions
   - MVP feature boundaries and scope

### Planning & Design Documents

These documents provide critical decisions and planning structure:

5. **task-17-ambiguities.md** - Resolved design decisions and ambiguities
   - LLM model selection (anthropic/claude-sonnet-4-0)
   - Retry strategies and validation approaches
   - Parameter discovery architecture
   - Testing strategy (hybrid mocked/real)
   - Workflow storage integration
   - Clear recommendations for each decision

6. **task-17-subtask-plan.md** - Decomposition into 7 logical subtasks
   - Subtask 1: Foundation & Infrastructure
   - Subtask 2: Discovery System
   - Subtask 3: Parameter Management System
   - Subtask 4: Generation System
   - Subtask 5: Validation & Refinement System
   - Subtask 6: Flow Orchestration
   - Subtask 7: Integration & Polish
   - Critical parameter extraction independence explained
   - Dependencies and testing strategy

> IMPORTANT: These should be implemented one by one in the order of the subtasks. You should have been asigned a single subtask to implement.

### Implementation Resources

These documents provide practical patterns and guidance:

7. **task-17-advanced-patterns.md** - Production-proven PocketFlow patterns
   - Pattern 1: Two-path decision with convergence
   - Pattern 2: Graceful failure recovery with exec_fallback
   - Pattern 3: Progressive context building
   - Pattern 4: Multi-tier validation with bounded retries
   - Pattern 5: Structured LLM output with JSON (using llm library's schema support)
   - Pattern 6: Using validation errors for better retries
   - Pattern 7: Structured shared store design
   - Implementation checklist and anti-patterns to avoid

8. **task-17-pocketflow-insights.md** - PocketFlow conventions and implementation philosophy
   - Critical distinction: Implementing agent vs planner structure
   - File structure conventions (nodes.py, flow.py, utils/)
   - What patterns apply (Workflow, Supervisor) vs don't apply (Agent)
   - Shared store design principles
   - Agentic Coding process for implementers

9. **task-17-implementation-principles.md** - Practical debugging and implementation guide
   - Walking skeleton WITH LOGGING approach
   - Critical PocketFlow framework rules (4 rules with ❌/✅ examples)
   - LLM setup instructions for anthropic/claude-sonnet-4-0
   - Quick debugging checklist
   - Common mistakes to avoid
   - Implementation sequence (5 steps)
   - Subtask focus mapping

## Recommended Reading Order

### For Understanding the Task:
1. Start with **task-17-standardized-conventions.md** for consolidated guidelines
2. Read **task-17-core-concepts.md** to understand what we're building
3. Read **task-17-architecture-and-patterns.md** for the system design
4. Review **task-17-ambiguities.md** to understand resolved decisions

### For Planning Implementation:
1. Read **task-17-subtask-plan.md** to understand the work breakdown
2. Review **task-17-pocketflow-insights.md** for framework conventions
3. Study **task-17-advanced-patterns.md** for proven solutions

### For Active Implementation:
1. Keep **task-17-implementation-principles.md** open for debugging help
2. Reference **task-17-implementation-guide.md** for code examples
3. Use **task-17-advanced-patterns.md** for specific pattern implementations

## Quick Reference Guide

- **Need consolidated guidelines?** → task-17-standardized-conventions.md
- **Need to understand the overall system?** → task-17-architecture-and-patterns.md
- **Confused about a design decision?** → task-17-ambiguities.md
- **Starting implementation?** → task-17-implementation-principles.md (walking skeleton)
- **Need a specific pattern?** → task-17-advanced-patterns.md
- **Debugging issues?** → task-17-implementation-principles.md (debugging checklist)
- **Understanding your subtask?** → task-17-subtask-plan.md + your subtask spec
- **PocketFlow questions?** → task-17-pocketflow-insights.md + pocketflow/__init__.py

## Implementation Status

### Documentation Phase: ✅ COMPLETE
All planning and design documentation is complete with:
- 9 comprehensive documents totaling ~500KB of guidance
- Clear subtask decomposition with dependencies

### Next Steps:
1. **Create subtask specifications** (if not already done) for each of the 7 subtasks
2. **Begin Subtask 1 (Foundation)** implementation following the walking skeleton approach
3. **After Subtask 1**, Continue with Subtasks 2-5
4. **Subtask 6 (Orchestration)** wires everything together
5. **Subtask 7 (Integration)** connects to CLI and adds comprehensive testing

---
