# Fork: Task 107 — Phase 3.1 — Convert examples/real-workflows/ to .pflow.md

## Entry 1: Convert all 4 real-workflow JSON files

Attempting: Manually convert all 4 JSON workflow files to hand-crafted .pflow.md format with IR verification.

Result:
- ✅ webpage-to-markdown (7 nodes, 3 inputs, 1 output) — converted and verified
- ✅ generate-changelog-simple (19 nodes, 2 inputs, 5 outputs) — converted and verified
- ✅ release-announcements (8 nodes, 7 inputs, 5 outputs, 3 LLM batch with inline items) — converted and verified
- ✅ generate-changelog (17 nodes, 4 inputs, 5 outputs, dual-format LLM batch with inline items) — converted and verified
- ✅ All JSON originals deleted
- 💡 Inputs with `required: false` in the JSON must include `- required: false` in markdown — omitting it defaults to true per IR schema. Fixed after first verification pass.
- 💡 Inline batch items (literal arrays of objects, not template references) work correctly as YAML inside `yaml batch` code blocks.
- 💡 The `format-both` node has inline batch items where each item's `prompt` field is a very long multi-line string. Using YAML double-quoted strings with `\n` escapes works (from F7 insight: YAML block scalars with blank lines break due to continuation rules).

Files modified:
- `examples/real-workflows/webpage-to-markdown/workflow.pflow.md` (created)
- `examples/real-workflows/generate-changelog-simple/workflow.pflow.md` (created)
- `examples/real-workflows/release-announcements/workflow.pflow.md` (created)
- `examples/real-workflows/generate-changelog/workflow.pflow.md` (created)
- `examples/real-workflows/webpage-to-markdown/workflow.json` (deleted)
- `examples/real-workflows/generate-changelog-simple/workflow.json` (deleted)
- `examples/real-workflows/release-announcements/workflow.json` (deleted)
- `examples/real-workflows/generate-changelog/workflow.json` (deleted)

Status: Fork F8 complete. All 4 real-workflow JSON files converted to .pflow.md and originals deleted. IR comparison verified for all nodes, params, batch configs, inputs, and outputs.
