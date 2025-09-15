# Archived Tests

This directory contains tests for deprecated prompts and legacy implementations.

## test_workflow_generator_prompt.py
- **Deprecated**: Task 52 (2025-09-10)
- **Replaced by**: test_workflow_generator_context_prompt.py
- **Reason**: Tests the new cache-optimized context architecture
- **Key differences**:
  - Original test: Used legacy `workflow_generator.md` prompt without context blocks
  - New test: Uses `workflow_generator_instructions.md` with PlannerContextBuilder
  - New test: Simulates full planning context including RequirementsAnalysisNode and PlanningNode outputs
- **Test count**: 15 real-world test cases (vs 12 in original)
- **Accuracy**: 100% with new architecture