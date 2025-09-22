# Task 56: Runtime Validation & Error Feedback — Implementation Plan

## 1) Overview & Outcomes
- Add a planner-stage runtime self-correction loop that executes the candidate workflow and feeds runtime errors back to the generator for automatic fixes (≤ 3 attempts).
- Extend HTTP node with deterministic extraction and structured runtime errors.
- Support MCP tools in the loop by harvesting node-level errors and missing downstream template paths.
- Preserve current CLI and planner UX (no new flags; double-execution during fixes is acceptable for MVP).

## 2) Deliverables
- New planner node: `RuntimeValidationNode` in `src/pflow/planning/nodes.py`.
- Flow wiring changes in `src/pflow/planning/flow.py`.
- HTTP node enhancements in `src/pflow/nodes/http/http.py`.
- New exception: `RuntimeValidationError` in `src/pflow/core/exceptions.py`.
- Optional new prompt file for runtime-fix mode (if needed) in `src/pflow/planning/prompts/`.
- Unit and integration tests (HTTP, MCP, planner loop).
- Architecture/docs updates (brief).

## 3) File-by-File Changes
- `src/pflow/core/exceptions.py`
  - Add `class RuntimeValidationError(PflowError)` with structured fields: `source`, `node_id`, `node_type`, `category`, `attempted`, `available`, `sample`, `message`.

- `src/pflow/nodes/http/http.py`
  - Add optional `params.extract: dict[str, str]` using a simple dot/array path syntax (e.g., `$.field`, `$.nested.field`, `$.items[0].name`).
  - Implement a tiny extractor (no external JSONPath dep): resolve dot parts and `[idx]` for lists; return `None` when path missing.
  - On extraction failure for any key, raise `RuntimeValidationError` with:
    - `source="http"`, `node_id` not known in node (leave None), `node_type="http"`, `category="extraction_error"`
    - `attempted`: list of `{key, path}`
    - `available`: top-level keys from response JSON (list[str])
    - `sample`: shallow-sampled JSON string (depth/size limited)
    - `message`: human string
  - On success: return `{ "extracted": dict, "raw": json_or_text }` while keeping existing `response`, `status_code`, `headers`, `duration` structure. In `post`, continue writing existing shared keys; also write `extracted` under shared.

- `src/pflow/planning/nodes.py`
  - Add `class RuntimeValidationNode(Node)` with:
    - `prep(shared)`: consume `generated_workflow` IR, `execution_params`, and counters `runtime_attempts` (default 0), pass through registry and trace contexts if needed.
    - `exec(prep_res)`: compile and run the candidate workflow using `compile_ir_to_flow(...)` and `flow.run(shared_child)` with the same parameters used by CLI execute (namespacing/instrumentation already handled by compiler). Catch exceptions only to package classification output (don’t swallow; return info to `post`).
    - `post(shared, prep_res, exec_res)`: classify and route.
      - Gather issues via three mechanisms:
        1) Exception info captured from `exec`.
        2) Namespaced `error` keys for each node present in `shared` (i.e., any dict under `shared` that is a namespace).
        3) IR-vs-shared template audit: extract all `${...}` references from IR and verify paths exist in final shared store; for missing paths, add a fixable issue.
      - Build `shared["runtime_errors"]: list[dict]` using the unified schema.
      - If fixable issues exist and `runtime_attempts < 3` → increment `shared["runtime_attempts"]` and return `"runtime_fix"`.
      - If only fatal issues or `runtime_attempts >= 3` → return `"failed_runtime"`.
      - If no issues → return default.

- `src/pflow/planning/flow.py`
  - Wire after validation/metadata phase:
    - `metadata_generation >> runtime_validation`
    - `runtime_validation - "runtime_fix" >> workflow_generator`
    - `runtime_validation - "failed_runtime" >> result_preparation`
    - `runtime_validation >> parameter_preparation` (default/success path)

- `src/pflow/planning/nodes.py` (WorkflowGeneratorNode tweaks)
  - Accept `shared["runtime_errors"]` when present to switch to a runtime-fix prompt variant.
  - Do not change generator’s core outputs; only enrich the prompt context.
  - If we externalize prompt text, add `src/pflow/planning/prompts/workflow_generator_runtime_fix.md` and load it similarly to existing prompts.

- (Optional) Utility helpers
  - If needed: `src/pflow/runtime/json_path.py` for minimal dot/array extraction used by HTTP node (or inline within HTTP node for MVP).
  - In `RuntimeValidationNode`, use existing `TemplateValidator._extract_all_templates` for IR template discovery if accessible; otherwise implement a minimal IR template extractor scoped to `${...}` values in node params/outputs.

## 4) Detailed Steps
1) Exceptions
- Implement `RuntimeValidationError` in `src/pflow/core/exceptions.py`.
- Fields (all optional except `message`):
  - `source: str`, `node_id: str | None`, `node_type: str | None`, `category: str`
  - `attempted: list[dict]`, `available: list[str] | None`, `sample: str | None`, `message: str`

2) HTTP Node
- Add parameter parsing for `extract` in `prep()` (copy without mutating inputs).
- In `exec()` after response parsing:
  - If content is JSON and `extract` provided:
    - For each `alias, path` resolve; collect successes into `extracted`, misses into `errors`.
    - If any `errors`: compute `available` as top-level keys of JSON; compute `sample` via a small serializer limited to N keys / 500 chars; raise `RuntimeValidationError` with aggregation.
    - Else: include `extracted` in return dict alongside existing fields.
- In `post()`: in addition to existing writes, when `extracted` present, write `shared["extracted"] = exec_res["extracted"]` (namespacing will place under node namespace).

3) RuntimeValidationNode
- Add node with PocketFlow conventions (no try/except in `exec()` impacting retries; collect exception into `exec_fallback` or as part of the result per pattern used in planner nodes — for planner nodes, we typically return structured info rather than raise; follow existing planning nodes’ pattern):

```python
class RuntimeValidationNode(Node):
    name = "runtime_validation"
    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return {
            "workflow_ir": shared.get("generated_workflow"),
            "execution_params": shared.get("execution_params", {}),
            "runtime_attempts": int(shared.get("runtime_attempts", 0)),
            # pass-through for registry/trace/metrics if needed later
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        # Compile & run the candidate workflow
        try:
            from pflow.registry import Registry
            from pflow.runtime import compile_ir_to_flow
            registry = Registry()
            flow = compile_ir_to_flow(
                prep_res["workflow_ir"], registry, initial_params=prep_res.get("execution_params", {})
            )
            # Use the same shared store object to collect outputs
            shared_ref = {}
            result = flow.run(shared_ref)
            return {"ok": True, "shared_after": shared_ref, "result": result}
        except Exception as e:
            return {"ok": False, "error": str(e), "exception": e}

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        issues: list[dict[str, Any]] = []
        # 1) Exception-based issues
        if not exec_res.get("ok", False):
            issues.append({
                "source": "runtime",
                "node_id": None,
                "node_type": None,
                "category": "exception",
                "message": exec_res.get("error", "runtime exception"),
            })
            shared["runtime_errors"] = issues
            return "failed_runtime" if prep_res.get("runtime_attempts", 0) >= 3 else "runtime_fix"

        # 2) Namespaced error scan
        shared_after = exec_res.get("shared_after", {})
        for k, v in shared_after.items():
            if isinstance(v, dict) and "error" in v:
                issues.append({
                    "source": "node",
                    "node_id": k,
                    "node_type": v.get("type"),
                    "category": "node_error",
                    "message": str(v.get("error")),
                })

        # 3) IR-vs-shared template path check
        # Implement minimal extractor for ${node.path} references from IR params
        missing_refs = _find_missing_template_paths(prep_res["workflow_ir"], shared_after)
        for ref in missing_refs:
            issues.append({
                "source": "template",
                "node_id": ref["node_id"],
                "node_type": None,
                "category": "missing_output_path",
                "attempted": [{"path": ref["path"]}],
                "message": f"Template path missing: {ref['path']}",
            })

        if not issues:
            return "default"

        # Classify fixable vs fatal — MVP: any issue triggers runtime_fix when attempts<3
        attempts = int(prep_res.get("runtime_attempts", 0))
        shared["runtime_errors"] = issues
        if attempts < 3:
            shared["runtime_attempts"] = attempts + 1
            return "runtime_fix"
        return "failed_runtime"
```

- Implement `_find_missing_template_paths(ir, shared_after)` locally or reuse `TemplateValidator._extract_all_templates` if importable; verify each `${node.field...}` exists under namespaced shared via `shared_after[node_id][field]` traversal.

4) Planner Flow Wiring
- In `create_planner_flow(...)` (in `src/pflow/planning/flow.py`):
  - Instantiate `runtime_validation = RuntimeValidationNode()`.
  - Wire:
    - `metadata_generation >> runtime_validation`
    - `runtime_validation - "runtime_fix" >> workflow_generator`
    - `runtime_validation - "failed_runtime" >> result_preparation`
    - `runtime_validation >> parameter_preparation`.

5) WorkflowGenerator runtime-fix support
- Update `WorkflowGeneratorNode.prep/exec` to read `shared.get("runtime_errors")` when present and select a runtime-fix prompt variant (new prompt markdown file). Scope of change: only prompt context; outputs unchanged.

6) Tests
- Unit (HTTP):
  - extract success returns `{extracted, raw}` and writes in namespaced shared.
  - extract missing path raises `RuntimeValidationError` with `attempted`, `available`, `sample`.
- Unit (RuntimeValidationNode):
  - no issues → default.
  - namespaced error present → runtime_fix and `runtime_attempts` increment.
  - exception during run → runtime_fix (attempts<3) else failed_runtime.
  - missing template path in IR → runtime_fix.
- Unit (MCP handling path):
  - Simulate namespaced MCP error; detected as fixable (runtime_fix).
- Integration:
  - HTTP: planner end-to-end “guess → runtime validation → fix → success”.
  - MCP: wrong downstream field path → runtime validation identifies missing path → fix → success (use a mock/simple MCP tool or fixture).

7) Documentation
- Update `architecture/features/` or task docs to mention the new loop and HTTP extract.
- Brief docs in `docs/nodes.md` for HTTP extract parameter and behavior.

## 5) Data Contracts
- `shared["runtime_errors"]: list[dict]` entries contain:
  - `source: str`, `node_id: str | None`, `node_type: str | None`, `category: str`,
  - `attempted: list[dict] | None`, `available: list[str] | None`, `sample: str | None`, `message: str`.
- HTTP `exec()` success returns keys: `response`, `status_code`, `headers`, `duration`, plus `extracted` (when provided), plus `raw` inside `response` or separate as specified; in `post()` write `response`, `status_code`, `response_headers`, `response_time`, `error` (on non-2xx), and `extracted` when present.

## 6) Classification Rules (MVP)
- Fixable:
  - HTTP `RuntimeValidationError` with `category="extraction_error"`.
  - Namespaced node `error` with messages indicating argument/field mismatch.
  - Missing IR template paths after run.
- Fatal:
  - Auth/network/timeout/5xx from HTTP/MCP (no extraction/argument correction signal).
  - Non-JSON body when `extract` requested.
  - Attempts exhausted (≥ 3).

## 7) Template Path Detection (MVP)
- Extract all strings containing `${...}` from node params of the IR.
- For each `${node.path}`:
  - Split into `node_id` and `path` (dot traversal on namespaced dict in shared).
  - If traversal fails, record a missing path issue.

## 8) Execution & Retry Semantics
- RuntimeValidationNode executes full workflow each attempt.
- On runtime_fix, generator produces corrected IR; loop repeats up to 3 times.
- Double execution is accepted (MVP trade-off).

## 9) Acceptance Criteria
- All Test Criteria in the spec pass.
- Planner flow includes new node and transitions.
- HTTP extraction and error raising behave as specified.
- `runtime_errors` present and consumed for fixes; attempts capped.
- No regressions in existing planner and CLI tests.

## 10) Risks & Mitigations
- Side-effects due to multiple executions → Accepted for MVP; documented.
- MCP variability in error formats → Classify by presence of namespaced `error` and missing template paths.
- Template extraction brittleness → Keep extractor minimal and covered by tests.

## 11) Rollout
- Land code + tests; run `make test` and `make check`.
- Update docs.
- No feature flags required.
