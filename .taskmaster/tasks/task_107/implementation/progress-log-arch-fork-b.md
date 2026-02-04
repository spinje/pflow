# Fork: Task 107 — Architecture docs — Fork B: json-workflows.md + ir-schema.md

## Entry 1: Add deprecation notice + update file references

Attempting: Add historical deprecation notice to json-workflows.md and update ir-schema.md with clarifying note + .pflow.md file references.

Result:
- ✅ `architecture/guides/json-workflows.md`: Added prominent deprecation notice at top with link to format specification and `pflow instructions usage`. File content preserved as historical reference.
- ✅ `architecture/reference/ir-schema.md`: Added "Format Note" callout after intro explaining this documents the internal IR dict (not user-authored format), that `ir_version` is auto-added by `normalize_ir()`, and linking to the format specification.
- ✅ `ir-schema.md` line 43: Updated `minimal.json` → `minimal.pflow.md` with clarifying note about parser conversion.
- ✅ `ir-schema.md` lines 531-532: Updated `simple-pipeline.json` and `error-handling.json` → `.pflow.md`.
- ✅ `ir-schema.md` line 563: Updated `proxy-mappings.json` → `.pflow.md`.
- ✅ `ir-schema.md` lines 709-727: Rewrote entire Example Repository section — core examples (5 files → .pflow.md), advanced examples (2 files → .pflow.md), invalid examples (replaced 4 old JSON-specific entries with 8 new markdown-specific entries matching actual files in examples/invalid/).
- ✅ Updated closing line: "JSON schemas" → "schemas" (document covers IR structure, not just JSON).
- ✅ Verified all referenced files exist on disk (core: 5/5, advanced: 2/2, invalid: 8/8).
- ✅ JSON IR examples within ir-schema.md left unchanged — they correctly show the internal dict structure.

Files modified:
- `architecture/guides/json-workflows.md`
- `architecture/reference/ir-schema.md`

Status: Fork B complete. Both files updated, all references verified.
