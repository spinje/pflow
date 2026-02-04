# Fork: Task 107 — Phase 3.1 — Convert examples/core/ workflows to .pflow.md

## Entry 1: Read and analyze JSON workflows

Attempting: Read all 5 JSON workflows to understand structure and identify conversion challenges.

Result:
- ✅ Read all 5 files
- 💡 `error-handling.json` has non-linear edges (error paths, retry loops) — not expressible in linear-only markdown format. Document this in the converted file.
- 💡 `proxy-mappings.json` uses the `mappings` IR field — not expressed in markdown syntax. Document this in the converted file.
- 💡 `template-variables.json` has a `content` param with literal `\n` characters — needs YAML double-quoted string with `\n` escapes to match.

Status: Analysis complete, ready to convert.

## Entry 2: Convert all 5 workflows and verify

Attempting: Write hand-crafted .pflow.md files for all 5 workflows and verify IR equivalence.

Result:
- ✅ `minimal.pflow.md`: single node, exact IR match
- ✅ `simple-pipeline.pflow.md`: 3 nodes, exact IR match (nodes + edges)
- ✅ `template-variables.pflow.md`: 5 nodes, exact IR match after fixing content param to use YAML double-quoted `\n` escapes
- ✅ `error-handling.pflow.md`: 6 nodes, params match. Edges differ as expected (linear vs non-linear). Documented in file description.
- ✅ `proxy-mappings.pflow.md`: 3 nodes, exact IR match. Mappings not expressible in markdown. Documented in file description.
- ✅ Deleted all 5 `.json` originals
- ✅ Deleted leftover `.md` files (without `.pflow.` prefix) that were artifacts from previous work

Decision: YAML block scalar (`|`) for multi-line content
- Options: (A) YAML block scalar `|`, (B) YAML double-quoted `\n` escapes
- Chose: (B) because the parser's YAML continuation rules terminate on blank lines, breaking block scalars with blank lines. YAML double-quoted strings handle `\n` escapes correctly and produce identical output to JSON.
- Reversible: yes

Files modified:
- `examples/core/minimal.pflow.md` (created)
- `examples/core/simple-pipeline.pflow.md` (created)
- `examples/core/template-variables.pflow.md` (created)
- `examples/core/error-handling.pflow.md` (created)
- `examples/core/proxy-mappings.pflow.md` (created)
- `examples/core/minimal.json` (deleted)
- `examples/core/simple-pipeline.json` (deleted)
- `examples/core/template-variables.json` (deleted)
- `examples/core/error-handling.json` (deleted)
- `examples/core/proxy-mappings.json` (deleted)
- `examples/core/minimal.md` (deleted — leftover artifact)
- `examples/core/simple-pipeline.md` (deleted — leftover artifact)
- `examples/core/template-variables.md` (deleted — leftover artifact)
- `examples/core/error-handling.md` (deleted — leftover artifact)
- `examples/core/proxy-mappings.md` (deleted — leftover artifact)

Note for main agent: The parser's YAML continuation rule (blank line terminates continuation) means YAML block scalars (`|`) with blank lines don't work in `- key:` params. Multi-line values that contain blank lines should use YAML double-quoted strings with `\n` escapes instead. This affects `ir_to_markdown()` in `tests/shared/markdown_utils.py` — it currently uses `"\\n"` escapes in double-quoted strings which is correct for this reason.

Status: Fork F7 complete. All 5 .json workflow files in examples/core/ converted to .pflow.md, verified via parser, and originals deleted.
