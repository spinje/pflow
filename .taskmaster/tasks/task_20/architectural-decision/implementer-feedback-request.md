# Feedback Request: WorkflowNode Architecture

## To: Task 20 Implementer

Hi! I've been reviewing the WorkflowNode implementation and discovered a potential architectural issue that I'd like your input on.

## Current Situation

You've already implemented WorkflowNode in `src/pflow/nodes/workflow/` and it appears to be working correctly. However, I've identified a conceptual issue:

**The Issue**: WorkflowNode will appear in the planner's node discovery list alongside regular nodes like "read-file", "write-file", etc. This could confuse users because:
- Workflows are conceptually compositions, not building blocks
- Users might see "workflow" as a node type and not understand its purpose
- It breaks the mental model where nodes are ingredients and workflows are recipes

## Proposed Solution (Not Implemented)

I considered moving WorkflowNode to `src/pflow/runtime/workflow_executor.py` as a runtime component, with special compiler handling for `type: "workflow"`. This would:
- Hide it from the planner
- Maintain conceptual clarity
- Keep it as internal infrastructure

## My Question to You

Given that you've already implemented WorkflowNode and it's working:

1. **Have you noticed any confusion** with WorkflowNode appearing in the planner during your testing?

2. **Do you think this is worth fixing now**, or should we:
   - Document it as an "advanced" feature
   - Add a note in the planner to clarify its purpose
   - Consider refactoring in v2 if users report confusion

3. **From your implementation experience**, how disruptive would it be to move this to runtime/ now?

## My Current Thinking

Since the code is already working and tested, I'm leaning toward keeping it as-is for the MVP and addressing the conceptual issue through documentation rather than refactoring. But I value your perspective as the implementer.

What do you think? Is the conceptual purity worth the refactoring effort, or should we ship with the current working implementation?

Thanks for your input!
