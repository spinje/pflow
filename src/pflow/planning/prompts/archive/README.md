# Archived Prompts

This directory contains prompts that are no longer used in production but are kept for historical reference.

## workflow_generator.md
- **Deprecated**: Task 52 (2025-09-10)
- **Replaced by**: workflow_generator_instructions.md and workflow_generator_retry.md
- **Reason**: Moved to cache-optimized context architecture with PlannerContextBuilder
- **Last used in**: Legacy fallback path for direct WorkflowGeneratorNode usage
- **Context**: The new architecture provides:
  - Better context accumulation across retries
  - Cache-optimized blocks for future cost reduction
  - Shared workflow system understanding between Planning and Generation nodes

## planning.md
- **Deprecated**: Task 52 (2025-09-10)
- **Replaced by**: planning_instructions.md
- **Reason**: Part of the cache-optimized context architecture
- **Context**: The new planning system works with RequirementsAnalysisNode for better workflow generation

## workflow_generator_context.md
- **Deprecated**: During Task 52 implementation
- **Replaced by**: Integrated into PlannerContextBuilder
- **Reason**: Context is now built programmatically with structured blocks