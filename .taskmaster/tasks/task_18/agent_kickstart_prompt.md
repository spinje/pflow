# Task 18: Template Variable System Implementation

## Your Epistemic Responsibility

You are about to implement the **runtime proxy** that enables pflow's core value proposition: "Plan Once, Run Forever". This is not just another feature - it's the foundation that makes workflows reusable instead of single-use. Your implementation will determine whether users can truly create workflows once and run them with different parameters forever.

**Your role is not to complete a task - it is to ensure the implementation is correct, robust, and survives real-world usage.**

## Critical Scope Boundary

**YOU ARE IMPLEMENTING TASK 18 ONLY - THE TEMPLATE VARIABLE SYSTEM**

Do NOT:
- Modify the CLI beyond integrating template validation
- Implement any planner functionality (that's Task 17)
- Create new node types
- Add features beyond template variables
- Refactor existing code unless required for integration
- Add proxy mappings or key renaming (that's Task 9, deferred to v2.0)

Your implementation scope is EXACTLY:
1. `TemplateResolver` - Detects and resolves `$variable` syntax with path support
2. `TemplateValidator` - Validates required parameters exist before execution
3. `TemplateAwareNodeWrapper` - Wraps nodes to intercept and resolve templates
4. Integration with `compiler.py` - Wire validation and wrapping into compilation
5. Comprehensive tests for all the above

## Required Reading (In Order)

**You MUST read these files completely before writing any code:**

1. **`.taskmaster/workflow/epistemic-manifesto.md`** - Your operating principles. This defines HOW you should think and work. Pay special attention to:
   - "Ambiguity is a STOP condition"
   - "Documentation is a hypothesis, not a truth source"
   - "Design for future understanding"

2. **`pocketflow/__init__.py`** - The PocketFlow framework source code. Understanding how nodes execute is CRITICAL. Pay special attention to:
   - How `_run()` method works
   - The `copy.copy(node)` behavior in Flow execution
   - Why `set_params()` is called on a fresh copy
   - The execution flow: `prep()` → `exec()` → `post()`

3. **`.taskmaster/tasks/task_18/task_18_spec.md`** - The formal specification. This is your contract. Every rule (R1-R12) and edge case (E1-E8) must be implemented and tested exactly as specified.

4. **`.taskmaster/tasks/task_18/template-variable-path-implementation-mvp.md`** - The implementation guide with context, examples, and code structure. This explains WHY decisions were made and HOW the system fits together.

## Critical Context

**What you're building**: A template variable system that intercepts node execution to replace `$variable` placeholders (like `$issue_number` or `$data.field.subfield`) with actual values at runtime. This happens transparently - existing nodes don't need modification.

**Why it matters**: Without this, every workflow would have hardcoded values. A workflow to "fix issue 1234" couldn't be reused for issue 5678. The template system enables true reusability.

**The two phases**:
1. **Validation** - Before execution, ensure all required parameters exist
2. **Resolution** - During execution, replace templates with actual values

## Your Implementation Approach

### 1. Verify Understanding First
Before coding, ensure you understand:
- How PocketFlow's node execution works (study the `_run()` and `copy.copy()` behavior)
- Why interception must happen at `_run()` and nowhere else
- How the fallback pattern in pflow nodes enables this to work
- Why resolution must be dynamic (values change during execution)

**If anything is unclear, STOP and investigate. Do not guess.**

### 2. Key Implementation Considerations

**What makes this challenging**:
- You're modifying node behavior without changing node code
- Resolution must happen at the exact right moment in execution
- The wrapper must be completely transparent except for template resolution
- Both validation and resolution share parsing logic but serve different purposes

**Critical constraints**:
- Templates ONLY exist in `params` values (never in id, type, or edges)
- ALL values convert to strings (no type preservation in MVP)
- Unresolvable templates remain unchanged (for debugging visibility)
- Initial params from planner have priority over shared store values

### 3. Implementation Order
1. Start with `TemplateResolver` - the core parsing and resolution logic
2. Write comprehensive tests for the resolver BEFORE moving on
3. Implement `TemplateValidator` using the resolver's parsing
4. Create `TemplateAwareNodeWrapper` with careful attention to attribute delegation
5. Integrate with `compiler.py` - handle both validation and wrapping
6. Test the complete integration with real workflows

### 4. Testing Philosophy
- Test edge cases FIRST (malformed syntax, missing paths, null values)
- Test the integration between components, not just units
- Verify the wrapper is truly transparent (attributes delegate correctly)
- Ensure backwards compatibility (non-template workflows unchanged)

## Success Criteria

Your implementation succeeds when:

1. **The planner's vision works**: "fix github issue 1234" creates a workflow with `$issue_number` that can later run with `--issue=5678`

2. **Validation catches errors early**: Missing parameters fail with clear messages like "Missing required parameter: --url"

3. **Path traversal works**: `$transcript_data.metadata.author` correctly navigates nested data

4. **Nodes remain unmodified**: Existing nodes work without any changes

5. **Debugging is possible**: Unresolved templates remain visible as `$missing_var`

## Epistemic Checkpoints

As you work, regularly ask yourself:

1. **Am I making assumptions about node behavior?** → Verify against actual pflow nodes
2. **Does my implementation handle ALL specified edge cases?** → Check against E1-E8
3. **Would someone debugging a workflow understand what happened?** → Test with missing variables
4. **Have I proven this works, or do I just think it works?** → Write tests that could fail

## Final Guidance

This task requires deep understanding of how nodes execute, careful implementation of the wrapper pattern, and thorough testing of edge cases. The spec (R1-R12, E1-E8) is your contract - implement it exactly.

Remember: **You are epistemically responsible for this implementation.** It's not enough that it works in simple cases - it must be robust enough to power every workflow in the pflow ecosystem.

When you're ready, begin by reading the four required documents in order. Then start with understanding, not coding. The implementation will follow naturally from deep comprehension.

**Your first output should demonstrate that you've read and understood all four documents. Show your understanding, surface any ambiguities, and outline your implementation plan before writing any code.**

Remember: You are implementing ONLY the template variable system (Task 18). Stay within scope.
