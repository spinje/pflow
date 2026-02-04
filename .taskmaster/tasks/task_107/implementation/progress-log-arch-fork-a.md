# Fork: Task 107 — Architecture Docs — Fork A: Overview + Core Concepts

## Entry 1: Fix stale JSON workflow references in 3 files

Attempting: Update all stale JSON workflow format references in overview.md, pflow-pocketflow-integration-guide.md, and core-concepts/shared-store.md to reflect .pflow.md as the current format.

### overview.md (7 edits)

1. Line 7: "workflows defined in JSON" → "workflows defined in markdown (`.pflow.md`)"
2. Line 108: "Workflows are JSON with declared inputs" → "Workflows are structured markdown (`.pflow.md`)"
3. Line 158: "Workflows are JSON files" → "Workflows are markdown files (`.pflow.md`)"
4. Lines 208-216: Renamed section "JSON Workflows" → "Markdown Workflows (`.pflow.md`)" with updated bullet points explaining markdown benefits and noting JSON was the original format replaced in Task 107
5. Line 280: Planner described as "may be deprecated" → "gated pending markdown format prompt rewrites (Task 107 Decision 26)" with note that discovery commands remain active
6. Line 297: Validation "6-layer" → "7-layer" with corrected layer names (checked actual codebase: `workflow_validator.py` has 7 layers — structural, stdin, data flow, template, node type, output source, unknown param warnings)
7. Line 330: "The current JSON format works but has friction..." → Reframed as completed work ("done — Task 107") with markdown as the current format

### pflow-pocketflow-integration-guide.md (7 edits)

1. Line 22: "use JSON workflows via the CLI (`pflow workflow.json`)" → "use markdown workflows via the CLI (`pflow workflow.pflow.md`)"
2. Line 30: "where JSON IR is transformed" → "where the workflow IR is transformed"
3. Line 64: "JSON IR to Flow compilation" → "Markdown parser (`.pflow.md` → IR dict) and IR-to-Flow compilation", added planner gating note
4. Lines 179-213: Insight #7 heading "JSON IR Compilation Pattern" → "IR Compilation Pattern", `ir_json` param → `ir_dict`, "Instantiate pocketflow objects from JSON" → "from the IR dict"
5. Line 243: "LLM output (JSON IR)" → "IR dict — produced from .pflow.md by the markdown parser"
6. Lines 306-314: Core Architecture diagram: "Planning (optional) → JSON IR" → "Markdown Parser → IR dict", "Converts JSON to pocketflow objects" → "Converts IR dict to pocketflow objects"

### core-concepts/shared-store.md (5 edits)

1. Line 4: "pflow uses JSON workflow files" → "pflow uses markdown workflow files (`.pflow.md`)"
2. Line 42: "Template variables are preserved in the JSON IR by the planner" → "preserved in the IR dict (produced from `.pflow.md` by the markdown parser)"
3. Lines 381-390: IR section — added contextual note explaining JSON examples show internal IR dict structure, not authored .pflow.md format. Did NOT rewrite examples.
4. Lines 418-426: "Why JSON IR?" → "Why a Structured IR?" — updated to reflect agents author .pflow.md, parser converts to IR
5. Line 654: "Workflow JSON format specification" → "Workflow IR dict structure specification"

Result:
- ✅ All 19 edits applied cleanly across 3 files
- ✅ JSON examples in shared-store.md preserved (they show IR dict structure which is still valid)
- ✅ Validation layer count reconciled with actual codebase (7 layers, not 5 or 6)

Files modified:
- `architecture/overview.md`
- `architecture/pflow-pocketflow-integration-guide.md`
- `architecture/core-concepts/shared-store.md`

Status: Fork A complete. All stale JSON workflow format references in assigned files updated.
