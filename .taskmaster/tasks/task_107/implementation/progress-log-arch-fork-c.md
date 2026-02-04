# Fork: Task 107 — Architecture docs — template-variables.md

## Entry 1: Fix stale references

Attempting: Update CLI command examples, add repair gating notes, and add clarifying note about IR examples.

Result:
- ✅ Added clarifying note after title explaining JSON examples show internal IR structure, users write .pflow.md
- ✅ Line 573: Added gating note to `repair_workflow()` comment
- ✅ Line 664: Updated "guides users (and the repair system)" — repair noted as gated
- ✅ Lines 805-806: Added gating notes to `__modified_nodes__` and `__non_repairable_error__` reserved keys
- ✅ Line 827: Added gating note to "Triggers repair system" comment
- ✅ Line 890: Added gating note to "Error Recovery" section header referencing repair system
- ✅ Line 1515: `pflow validate workflow.json` → `pflow --validate-only workflow.pflow.md`
- ✅ Lines 1762-1772: All 4 CLI commands updated from `workflow.json` to `workflow.pflow.md`
- ✅ Line 1779: "Complete JSON IR specification" → "Complete IR specification"
- ✅ Verified remaining .json references are all legitimate (settings.json, trace files, template examples)

Files modified: `architecture/reference/template-variables.md`

Status: Fork complete. All assigned changes applied.
