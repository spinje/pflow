# Braindump: Nested Workflow Gaps Found During Task 107 Verification

## Where I Am

During Task 107 (markdown format migration), the user pushed hard to verify nested workflows work end-to-end before calling the task done. We found and fixed several issues, but deferred the harder problems to Task 59. This braindump captures everything the next agent needs to know about the gaps.

## User's Mental Model

The user thinks about nested workflows from an **AI agent's perspective**. Their key question was: "how good and AI agent optimized are the error messages for when a subworkflow doesn't get all its required params etc. are we handling all edge cases here?" They want agents to be able to diagnose and fix their own mistakes without human intervention. Error messages should tell the agent exactly what went wrong and what the fix is.

Their approach: "fix the most obvious and easy to fix issues and then lets stop and pass the remaining hard work and audit to task 59." They're practical — quick wins now, systematic work later.

## Key Insights

### What We Fixed (in Task 107, committed on feat/markdown-workflow-format branch)

1. **`workflow_validator.py`**: Added `compiler_special_types = {"workflow", "pflow.runtime.workflow_executor"}` set. Without this, `type: workflow` nodes fail with "Unknown node type" during validation. The validator checks all types against the registry, but workflow is handled by the compiler, not registered.

2. **`template_validator.py`**: Added `output_mapping` registration for workflow nodes in `_extract_node_outputs()`. Without this, `${process.mapped_key}` fails template validation because the validator doesn't know what outputs a workflow node produces. The fix reads `output_mapping` from the node's params and registers each mapped parent key as an available output. This also registers namespaced versions (`node_id.parent_key`).

3. **`workflow_executor.py`**: Added warning when `output_mapping` child_key doesn't exist in child storage. Filters out internal keys (`_pflow_*`, `__*__`) from the "Available keys" list so agents see only meaningful options.

4. **Two regression tests** added to `test_workflow_validator.py`: `test_workflow_node_type_bypasses_registry` and `test_workflow_output_mapping_resolves_in_templates`.

### What We Found But Did NOT Fix

These are the deferred items for Task 59:

#### 1. Tracebacks shown to agents (HIGH PRIORITY)

When a child workflow fails compilation (e.g., missing required input), the agent sees a full Python traceback including internal compiler lines. The actual error is buried inside: `WorkflowExecutor failed at [child path]: Failed to compile sub-workflow: Validation error at inputs.text: Workflow requires input 'text': The text to transform.`

The traceback comes from the compiler's `_validate_workflow` → `_raise_input_validation_errors` path. The `exec()` method in `workflow_executor.py:155-164` catches exceptions and wraps them, but the traceback is printed to stderr BEFORE the catch lands. I didn't trace exactly where the traceback output happens — it might be in the instrumented wrapper's error handling.

NEEDS VERIFICATION: Where exactly does the traceback get printed? The `exec()` method catches the exception at line 163 and returns a dict. Something upstream is also printing the traceback to stderr.

#### 2. Wrong param_mapping doesn't suggest available child inputs

When you map `wrong_name: hello` but the child expects `text`, the error says "Workflow requires input 'text'" but does NOT say "you provided 'wrong_name' which doesn't match any child input." The agent has to infer the fix. The `_resolve_parameter_mappings()` method at line 262 doesn't have access to the child's input schema — it just resolves templates. The child's input validation happens later during compilation.

CONSIDER: Could `prep()` load the child workflow IR, extract its declared inputs, and validate param_mapping keys against them BEFORE passing to compilation? This would give a much better error: "param_mapping key 'wrong_name' does not match any input in child workflow. Available inputs: text (string, required)."

#### 3. Silent failure on wrong output_mapping keys (PARTIALLY FIXED)

We added a WARNING log, but it's still a warning — the workflow continues and the downstream node fails with an unrelated "Unresolved variables" error. The agent has to connect the warning to the downstream failure.

CONSIDER: Should a missing output_mapping key be an error, not a warning? The current behavior (line 210: `if child_key in child_storage`) means the parent key simply never gets set. This is almost always a bug, not intentional.

#### 4. Relative path resolution for top-level workflow_ref (CONFIRMED BUG)

`_resolve_safe_path()` at line 219-235 checks `shared["_pflow_workflow_file"]` to resolve relative paths from the parent workflow's location. For the top-level workflow (run via CLI), nobody sets `_pflow_workflow_file` in the shared store. So `./child.pflow.md` resolves from `Path.cwd()`, not from the parent workflow's directory.

This works when you `cd` to the workflow's directory, but fails when you run `pflow path/to/parent.pflow.md` from a different directory. The fix would be in the CLI (or execution service) to set `_pflow_workflow_file` in the initial shared store before compilation.

ASSUMPTION: The `_pflow_workflow_file` key should be set by the CLI when running from a file path. The executor already sets it for child workflows (line 323). The pattern is consistent — it's just missing for the top-level entry.

## The Test Scenarios I Created

I created 4 test workflows in `scratchpads/nested-test/` that demonstrate each failure mode. These are scratch files, not committed, but the patterns are valuable for writing proper tests:

- `parent.pflow.md` — working nested workflow (uses absolute path due to bug #4)
- `child.pflow.md` — simple text-to-uppercase sub-workflow
- `parent-missing-param.pflow.md` — child requires `text`, parent provides no param_mapping
- `parent-wrong-mapping.pflow.md` — maps `wrong_name` instead of `text`
- `parent-wrong-output.pflow.md` — maps `nonexistent_output` from child
- `parent-no-mapping.pflow.md` — no param_mapping or output_mapping at all

The exact error output for each is documented in the conversation but NOT in any file. Here's what agents see:

**Missing param**: Full traceback + `"WorkflowExecutor failed at [path]: Failed to compile sub-workflow: Validation error at inputs.text: Workflow requires input 'text': The text to transform."`

**Wrong param name**: Same as missing param (child doesn't receive the mapped value, so it's just "missing required input text")

**Wrong output key**: `WARNING: output_mapping key 'nonexistent_output' not found in child workflow storage. Available keys: ['text', 'transform', 'result']` followed by downstream `"Unresolved variables in parameter 'command': ${process.processed_text}"`

**No mapping at all**: Caught at validation time: `"Node 'process' does not output 'processed_text'"` — this is actually the BEST error because the template validator handles it.

## Assumptions & Uncertainties

ASSUMPTION: The `exec()` try/catch at line 155-164 should be sufficient to suppress tracebacks. If the traceback is being printed elsewhere (e.g., by the instrumented wrapper or PocketFlow's error handling), the fix is more involved.

UNCLEAR: Should `output_mapping` validation happen at compile time or runtime? At compile time, we don't have the child's actual outputs — we only have the mapping declaration. At runtime, we have the child's storage but it's too late for a clean error.

UNCLEAR: The user hasn't specified what Task 59's full scope is. I associated this braindump with Task 59 based on the conversation, but the task spec might define a different scope. Read the task spec first.

NEEDS VERIFICATION: Are there tests for the `WorkflowExecutor` that go through the full CLI path (not just direct executor tests)? The existing tests in `tests/test_runtime/test_workflow_executor/` bypass validation entirely.

## Unexplored Territory

UNEXPLORED: What happens when a child workflow has `## Outputs` declarations? Do output declarations in the child interact with `output_mapping` in the parent? I suspect they don't — the executor just reads from child_storage directly.

UNEXPLORED: What about `storage_mode: shared`? The `post()` method at line 202 explicitly skips output_mapping for shared mode (`if output_mapping and exec_res.get("storage_mode") != "shared"`). Is this correct? In shared mode the child writes directly to parent storage, so mapping isn't needed — but there's no documentation or error message explaining this.

CONSIDER: Nested workflows with batch processing. Can a workflow node have a `batch` config? What happens if `workflow_ref` contains templates that need to be resolved per-batch-item?

MIGHT MATTER: Error propagation chain. When a deeply nested workflow (3+ levels) fails, the error message stacks: `"WorkflowExecutor failed at X: Failed to compile sub-workflow: WorkflowExecutor failed at Y: ..."`. This gets unreadable fast. The `CircularWorkflowReferenceError` exception class exists in `core/exceptions.py` but is never used (it's dead code). There's also `WorkflowExecutionError` with a `workflow_path` chain — also dead code. These were designed for this exact problem but never wired up.

MIGHT MATTER: The MCP path for nested workflows. If an agent executes a workflow via MCP that contains `type: workflow` nodes with `workflow_ref`, the relative path resolution is even worse because there's no file system context at all.

## What I'd Tell Myself

- Start by running the 4 test scenarios I described above. Reproduce each failure mode to understand the current state.
- The traceback suppression is the highest-value fix. Agents should never see Python tracebacks.
- The `_pflow_workflow_file` fix in the CLI is straightforward — look at how the CLI stores `source_file_path` in `ctx.obj` and mirror that into the initial shared store.
- Don't try to validate `output_mapping` keys at compile time. The child's actual output keys depend on runtime behavior. The warning approach is the right pattern — just make it louder (maybe make it an error if the child storage has NO matching key at all).
- The `compile_ir_to_flow` call at `workflow_executor.py:157` passes `validate=True`. This triggers full template validation on the child workflow. Make sure any param_mapping validation you add runs BEFORE this call, not after.

## Relevant Files & References

- `src/pflow/runtime/workflow_executor.py` — the full executor (~330 lines), all fixes go here
- `src/pflow/core/workflow_validator.py:201-218` — the `_validate_node_types` with the new allowlist
- `src/pflow/runtime/template_validator.py:815-825` — the new `output_mapping` registration block
- `src/pflow/runtime/compiler.py:1118-1125` — compiler's duplicate `output_mapping` handling (the template validator fix mirrors this)
- `src/pflow/core/exceptions.py` — `WorkflowExecutionError` and `CircularWorkflowReferenceError` (dead code, designed for nested error chains)
- `tests/test_runtime/test_workflow_executor/` — existing test suite (bypasses CLI validation path)
- `tests/test_core/test_workflow_validator.py` — the 2 new regression tests we added

## For the Next Agent

Start by reading the Task 59 spec to understand the full scope. Then read this braindump. The 4 deferred issues are ordered by value:

1. **Traceback suppression** — highest agent impact, investigate where tracebacks are printed
2. **Relative path resolution** — confirmed bug, straightforward fix in CLI
3. **Richer param_mapping errors** — moderate effort, validate keys against child inputs in `prep()`
4. **output_mapping error escalation** — decide whether missing keys should be errors vs warnings

Don't touch the validator or template_validator fixes — those are done and tested. Build on them.

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
