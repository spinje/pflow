# Feature: runtime_validation_feedback_loop

## Objective
Enable planner runtime self-correction via execution feedback.

## Requirements
- Add RuntimeValidationNode to planner nodes
- Execute candidate workflow once for runtime validation
- Capture node exceptions and namespaced errors
- Detect missing template output paths post-exec
- Classify fixable vs fatal runtime issues
- Limit runtime correction attempts to 3
- Wire node into planner flow with defined actions
- Extend HTTP node with extract and structured errors
- Preserve existing CLI UX and autosave behavior

## Scope
- Does not add dry-run or read-only metadata
- Does not add planner autocomplete or caching changes
- Does not add new CLI flags or prompts

## Inputs
- task_id: int - Identifier for task (fixed 56)
- generated_workflow: dict[str, Any] - Candidate workflow IR from planner
- execution_params: dict[str, Any] - Extracted parameters for templates
- generation_attempts: int - Count of prior static validation retries
- runtime_attempts: int - Count of runtime retries (default 0)

## Outputs
Returns: One of
- default: workflow executed successfully (no fix needed)
- runtime_fix: runtime errors collected and provided to generator
- failed_runtime: non-fixable runtime error detected
Side effects:
- shared["runtime_errors"]: list[dict] present on runtime_fix
- shared updated by executed nodes during validation

## Structured Formats
- None

## State/Flow Changes
- metadata_generation >> runtime_validation
- runtime_validation - "runtime_fix" >> workflow_generator
- runtime_validation - "failed_runtime" >> result_preparation
- runtime_validation >> parameter_preparation

## Constraints
- runtime_attempts ≤ 3
- No modification to Planner ValidatorNode behavior
- No changes to CLI autosave flow
- Feature remains within planner (no external orchestrator)

## Rules
1. RuntimeValidationNode MUST compile and run the candidate workflow once using provided execution_params and a fresh shared store.
2. RuntimeValidationNode MUST catch any exception thrown during run and classify it.
3. RuntimeValidationNode MUST scan shared[node_id] for an "error" key for every node id present after execution.
4. RuntimeValidationNode MUST detect missing template output paths by comparing all ${node_id.field...} references in IR params to the final shared store; ignore non-node variables (workflow inputs without a node_id prefix).
5. RuntimeValidationNode MUST construct shared["runtime_errors"] containing structured entries when any fixable issues are detected.
6. RuntimeValidationNode MUST route action "runtime_fix" when at least one fixable issue is present and runtime_attempts < 3.
7. RuntimeValidationNode MUST route action "failed_runtime" when issues are present but none are fixable or runtime_attempts ≥ 3.
8. RuntimeValidationNode MUST route default when no issues are detected.
9. HTTP node MUST support params.extract: dict[str, str] with dot/array path syntax and, on success, MUST add an "extracted" object to the exec result while leaving the existing "response" key semantics unchanged (no new "raw" key).
10. HTTP node MUST raise RuntimeValidationError on any missing extract path and include attempted paths, available top-level keys, and a structure sample in the exception; HTTP exec_fallback MUST re-raise RuntimeValidationError unchanged (no conversion).
11. MCP runtime validation MUST treat namespaced node "error" values and missing downstream ${mcp_node.*} template paths as fixable when they indicate argument/field mismatches.
12. RuntimeValidationNode MUST NOT perform static schema/template/node-type validation (delegated to ValidatorNode).
13. RuntimeValidationNode MUST increment and persist runtime_attempts on every runtime_fix transition.
14. WorkflowGeneratorNode MUST accept shared["runtime_errors"] and enter a runtime-fix prompt mode that only adjusts argument names/values and output paths.
15. When multiple issues are detected in one run, the planner MUST return "runtime_fix" if any issue is fixable and runtime_attempts < 3; otherwise return "failed_runtime".

## Edge Cases
- No nodes write any outputs → default if no errors, else failed_runtime
- MCP node returns success but downstream template path missing → runtime_fix
- HTTP returns non-JSON while extract requested → failed_runtime
- Network/auth errors for HTTP/MCP → failed_runtime
- Mixed successes and errors across nodes → runtime_fix if any fixable exists and attempts < 3
- runtime_attempts already 3 → failed_runtime regardless of error type

## Error Handling
- Exceptions during execution → classified into fixable (extraction/argument mismatch) or fatal (auth/network/non-JSON/attempts exhausted) per Rules 6–7 and 15
- Unparseable IR or compilation failure inside RuntimeValidationNode → failed_runtime

## Non-Functional Criteria
- Runtime validation end-to-end ≤ 30s with default timeouts
- No additional planner prompts unless runtime_fix path taken

## Examples
- None

## Test Criteria
1. Rule 1: Compile+run once — Provide IR with a simple HTTP GET; verify one execution and default action.
2. Rule 2: Catch exception — HTTP extract missing path raises RuntimeValidationError; runtime_validation returns runtime_fix.
3. Rule 3: Namespaced error scan — MCP node sets namespaced error; runtime_validation returns runtime_fix.
4. Rule 4: Missing template path — IR references ${node.missing}; after run path absent → runtime_fix.
5. Rule 5: runtime_errors collected — Validate shape contains source, node_id, category, attempted, available.
6. Rule 6: runtime_fix when fixable and attempts<3 — attempts=0 → runtime_fix, attempts incremented to 1.
7. Rule 7: failed_runtime when non-fixable or attempts≥3 — auth error or attempts=3 → failed_runtime.
8. Rule 8: default when no issues — Valid IR and outputs present → default.
9. Rule 9: HTTP extract success — result contains "extracted" and "response" only (no "raw").
10. Rule 10: HTTP extract failure formatting — includes attempted paths, available keys, sample; exec_fallback re-raises RuntimeValidationError.
11. Rule 11: MCP fixable classification — tool error or missing downstream path yields runtime_fix.
12. Rule 12: No static validation in RuntimeValidationNode — ensure no schema/template/node-type calls.
13. Rule 13: attempts increment — verify attempts increases on runtime_fix.
14. Rule 14: Generator consumes runtime_errors — verify generator receives list and modifies IR paths.
15. Rule 15: Mixed issues priority — both fatal and fixable present with attempts<3 → runtime_fix.
16. Edge: Non-JSON with extract — failed_runtime.

## Notes (Why)
- Runtime feedback eliminates guesswork on external schemas and tool args while keeping deterministic runs post-fix.

## Compliance Matrix
- Rule 1 → Test 1
- Rule 2 → Test 2
- Rule 3 → Test 3
- Rule 4 → Test 4
- Rule 5 → Test 5
- Rule 6 → Test 6
- Rule 7 → Test 7, 16
- Rule 8 → Test 8
- Rule 9 → Test 9
- Rule 10 → Test 10
- Rule 11 → Test 11
- Rule 12 → Test 12
- Rule 13 → Test 13
- Rule 14 → Test 14
- Rule 15 → Test 15

## Versioning & Evolution
- v0.1.1 — Clarified HTTP return keys; explicit classification and re-raise behavior
- v0.1.0 — Initial runtime validation feedback loop

## Epistemic Appendix
### Assumptions & Unknowns
- None

### Conflicts & Resolutions
- HTTP "raw" key ambiguity vs existing "response" return — Resolution: keep "response" as-is; add "extracted" only; no new "raw" key.

### Decision Log / Tradeoffs
- Execute everything vs dry-run: chose execution for MVP to avoid metadata work
- Dot/array paths vs JSONPath: chose simpler syntax for determinism and speed

### Ripple Effects / Impact Map
- Modifies planner flow wiring and adds a new planner node
- Extends HTTP node API and error behavior

### Residual Risks & Confidence
- Risk: double execution side-effects; Accepted for MVP
- Confidence: High

### Epistemic Audit (Checklist Answers)
1. Unstated assumptions eliminated
2. If wrong classifications were assumed, tests catch via Rules 6–7, 15
3. Chose robustness over elegance (execute all, simple paths)
4. Rules↔Tests mapping complete
5. Affects planner flow, HTTP node, error model
6. Remaining uncertainty: low; Confidence: High
