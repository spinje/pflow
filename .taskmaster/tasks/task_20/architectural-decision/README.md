# Architectural Decision Documentation

## Quick Summary

**Decision**: Implement WorkflowNode as `WorkflowExecutor` in the runtime layer, not as a discoverable node.

**Why**: To preserve the conceptual model where nodes are building blocks and workflows are compositions.

## Documents in this Folder

### 1. [DECISION.md](./DECISION.md)
The core decision and rationale in brief.

### 2. [conceptual-model.md](./conceptual-model.md)
Explains the conceptual model of nodes vs workflows vs runtime components using clear analogies.

### 3. [workflow-execution-architecture-report.md](./workflow-execution-architecture-report.md)
Comprehensive analysis of the problem, options considered, and detailed recommendation.

### 4. [implementation-changes-summary.md](./implementation-changes-summary.md)
Exact code changes needed to implement this decision.

### 5. [implementation-roadmap.md](./implementation-roadmap.md)
Step-by-step implementation plan incorporating this architectural decision.

## Key Takeaways

1. **WorkflowExecutor is infrastructure**, not a user-facing node
2. **Lives in `runtime/`**, not `nodes/`
3. **Compiler handles `type: "workflow"`** specially
4. **Users never see it** in the planner
5. **Conceptual model stays clean**: nodes are ingredients, workflows are recipes

## For the Implementer

Start with [implementation-roadmap.md](./implementation-roadmap.md) - it has the updated step-by-step plan that incorporates this architectural decision.
