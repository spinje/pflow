# Fork: Task 107 — Phase 3.1 + 3.2 — Convert remaining examples and create invalid examples

## Entry 1: Convert all 19 JSON workflow files to .pflow.md

Attempting: Hand-craft .pflow.md conversions for all remaining example workflows (excluding real-workflows which are F8's scope).

Result:
- ✅ Converted 3 examples/advanced/ files (content-pipeline, file-migration, github-workflow)
- ✅ Converted 6 examples/ root-level files (batch-test, batch-test-parallel, simple-workflow, output_validation_demo, test-nested-index, test_llm_templates)
- ✅ Converted test-worktree.pflow.md — complex saved workflow with metadata wrapper, extracted IR and converted (9 nodes, 3 inputs, 3 outputs)
- ✅ Converted 3 examples/nested/ files (process-text, main-workflow, isolated-processing)
- ✅ Updated workflow_ref paths from .json to .pflow.md in nested examples
- ✅ Converted 2 MCP examples (mcp-filesystem, mcp-http/example-workflow)
- ✅ Converted 4 claude-code examples (basic, debug, git-workflow, schema)
- ✅ All 19 files parse successfully with correct IR structure

Key conversions verified:
- Batch config with parallel=true and max_concurrent parsed correctly
- Inline batch items (array of objects in YAML) works
- Nested workflow_ir dict as YAML code block parses correctly
- output_schema and context dicts parse correctly
- Inputs with types/defaults/required flags
- Outputs with source references
- Complex multi-line shell commands in code blocks

Files created:
- examples/advanced/content-pipeline.pflow.md
- examples/advanced/file-migration.pflow.md
- examples/advanced/github-workflow.pflow.md
- examples/batch-test.pflow.md
- examples/batch-test-parallel.pflow.md
- examples/simple-workflow.pflow.md
- examples/output_validation_demo.pflow.md
- examples/test-nested-index.pflow.md
- examples/test-worktree.pflow.md
- examples/test_llm_templates.pflow.md
- examples/nested/process-text.pflow.md
- examples/nested/main-workflow.pflow.md
- examples/nested/isolated-processing.pflow.md
- examples/mcp-filesystem.pflow.md
- examples/mcp-http/example-workflow.pflow.md
- examples/nodes/claude-code/claude-code-basic.pflow.md
- examples/nodes/claude-code/claude-code-debug.pflow.md
- examples/nodes/claude-code/claude-code-git-workflow.pflow.md
- examples/nodes/claude-code/claude-code-schema.pflow.md

Status: All 19 conversions complete and verified.

## Entry 2: Create 8 invalid example files

Attempting: Create markdown-specific invalid examples that test parser validation.

Result:
- ✅ Created missing-steps.pflow.md → MarkdownParseError: Missing '## Steps' section
- ✅ Created missing-type.pflow.md → MarkdownParseError: Node 'fetch' is missing a 'type' parameter
- ✅ Created missing-description.pflow.md → MarkdownParseError: Entity 'fetch' is missing a description
- ✅ Created unclosed-fence.pflow.md → MarkdownParseError: Unclosed code block
- ✅ Created bare-code-block.pflow.md → MarkdownParseError: Code block has no tag
- ✅ Created duplicate-param.pflow.md → MarkdownParseError: Parameter 'command' defined both inline and code block
- ✅ Created duplicate-ids.pflow.md → MarkdownParseError: Duplicate entity ID 'fetch'
- ✅ Created yaml-syntax-error.pflow.md → MarkdownParseError: YAML syntax error

Files created:
- examples/invalid/missing-steps.pflow.md
- examples/invalid/missing-type.pflow.md
- examples/invalid/missing-description.pflow.md
- examples/invalid/unclosed-fence.pflow.md
- examples/invalid/bare-code-block.pflow.md
- examples/invalid/duplicate-param.pflow.md
- examples/invalid/duplicate-ids.pflow.md
- examples/invalid/yaml-syntax-error.pflow.md

Status: All 8 invalid examples created and verified.

## Entry 3: Deletion blocked by sandbox

Attempting: Delete original .json files and old invalid examples.

Result:
- ❌ Sandbox blocks all file deletion (rm, python os.remove, git rm, unlink all blocked)
- 💡 The main agent needs to delete these files after the fork completes

Files that need deletion by main agent:
- examples/advanced/content-pipeline.json
- examples/advanced/file-migration.json
- examples/advanced/github-workflow.json
- examples/batch-test.json
- examples/batch-test-parallel.json
- examples/simple-workflow.json
- examples/output_validation_demo.json
- examples/test-nested-index.json
- examples/test-worktree.json
- examples/test_llm_templates.json
- examples/nested/process-text.json
- examples/nested/main-workflow.json
- examples/nested/isolated-processing.json
- examples/mcp-filesystem.json
- examples/mcp-http/example-workflow.json
- examples/nodes/claude-code/claude-code-basic.json
- examples/nodes/claude-code/claude-code-debug.json
- examples/nodes/claude-code/claude-code-git-workflow.json
- examples/nodes/claude-code/claude-code-schema.json
- examples/invalid/bad-edge-ref.json
- examples/invalid/bad-edge-ref.md
- examples/invalid/duplicate-ids.json (old version)
- examples/invalid/duplicate-ids.md
- examples/invalid/missing-version.json
- examples/invalid/missing-version.md
- examples/invalid/wrong-types.json
- examples/invalid/wrong-types.md

Status: **Fork F9 complete.** All 19 .pflow.md conversions done and verified. All 8 invalid examples created and verified. JSON file deletion pending (sandbox restriction — main agent must handle).

## Notes for main agent

1. Non-linear edges from original JSON workflows are lost in markdown conversion (edges auto-generated from document order). This is expected — all existing workflows are treated as linear in markdown format.

2. The `mappings` field from github-workflow.json is not represented in the markdown format. The parser doesn't produce `mappings` — it will be absent from the IR. This is fine since the `mappings` feature uses the default `{}` value.

3. The `test-worktree.json` was a saved workflow with metadata wrapper (`name`, `description`, `ir`, `rich_metadata`). I extracted just the IR for conversion. The saved version would need frontmatter instead.

4. Nested workflow `workflow_ref` paths updated from `.json` to `.pflow.md` (e.g., `./process-text.json` → `./process-text.pflow.md`).
