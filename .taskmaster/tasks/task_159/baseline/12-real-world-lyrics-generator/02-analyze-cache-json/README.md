# 02 — analyze-cache on real lyrics-generator (JSON)

**Surface**: 12-real-world-lyrics-generator

**Triggers**: same workflow as case 01, `--format=json`.

**Expected**: full JSON shape with `format_version: "4.0"` first key,
`per_call[]` with 25 entries, `warnings[]` with multiple catalog IDs,
`cross_workflow_findings` populated, `unavailable_models_by_workflow`
populated for the haiku-only sub-workflows, `summary.projection_exclusions`
for any heterogeneous-model rows.

**Mutation contract**: locks the JSON shape against drift on real-world
data. The minimal fixture cases (surface 03/04) lock individual fields;
this case locks the *interaction* between fields under a workflow with
realistic call volume.
