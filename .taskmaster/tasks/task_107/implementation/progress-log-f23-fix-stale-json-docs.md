# Fork: Task 107 — Fix stale .json workflow references in architecture docs

## Entry 1: Fix all 5 architecture doc files

Attempting: Replace all stale .json workflow references with .pflow.md equivalents across architecture documentation.

Result:
- ✅ `architecture/architecture.md` — 16 fixes:
  - Overview: "JSON configuration files" → "markdown files (.pflow.md)"
  - CLI interface: `workflow.json` → `workflow.pflow.md` (3 occurrences)
  - "JSON workflows" → ".pflow.md workflows" in important note
  - Authoring flow: `./my-workflow.json` → `./my-workflow.pflow.md`, removed `--description` flag
  - Building commands: `--validate-only workflow.json` → `workflow.pflow.md`, `save ./file.json` → `./file.pflow.md`
  - Planner status: updated to mention gated status
  - Execution pipeline: "Load JSON directly" → "Parse .pflow.md", planner marked gated
  - Running workflows code block: `workflow.json` → `workflow.pflow.md`
  - Managing workflows code block: `save ./workflow.json` → `./workflow.pflow.md`
  - Configuration section: Replaced entire "Workflow JSON Format" JSON example with markdown format example
  - Storage: Added note about .pflow.md with YAML frontmatter
  - Design decisions: Replaced "Why JSON Workflows?" with "Why Markdown Workflows?"
  - Self-healing: Updated to note gated status, .pflow.md reference
  - Nested workflow example: Replaced JSON with markdown format
  - Compiler description: "JSON IR" → "workflow IR"
  - Node types: "workflow JSON" → "workflow .pflow.md files"
- ✅ `architecture/features/simple-nodes.md` — 1 fix: `workflow.json` → `workflow.pflow.md`
- ✅ `architecture/features/shell-pipes.md` — 4 fixes:
  - CLI override example: `workflow.json` → `workflow.pflow.md`
  - Pipeline examples: 3 `.json` → `.pflow.md`
  - Input declaration: JSON format → markdown format
- ✅ `architecture/vision/north-star-examples.md` — 1 fix: caveat text updated
- ✅ `architecture/vision/README.md` — 1 fix: CLI syntax reference updated

Files modified:
- `architecture/architecture.md`
- `architecture/features/simple-nodes.md`
- `architecture/features/shell-pipes.md`
- `architecture/vision/north-star-examples.md`
- `architecture/vision/README.md`

Skipped (as instructed):
- `architecture/historical/` — preserved as historical artifacts
- `architecture/CLAUDE.md` — already updated in previous fork

Status: Complete. All 5 files fixed.
