# Manual Testing Plan — Workflow Bundling on Save (Task 130)

Tests that `pflow workflow save` correctly bundles workflows and their file dependencies
into self-contained folders, and that saved workflows execute correctly.

## Prerequisites

```bash
cd /path/to/pflow   # project root
make install         # ensure deps are up to date
```

## Test 1: Save simple workflow (no dependencies)

Verifies basic folder-based save/load/list/delete lifecycle.

```bash
# Save
uv run pflow workflow save examples/bundling/simple.pflow.md --name simple-bundling-test

# Verify folder structure
ls -la ~/.pflow/workflows/simple-bundling-test/
# Expected: simple-bundling-test.pflow.md (and nothing else)

# List — should show the workflow
uv run pflow workflow list

# Describe — should show interface
uv run pflow workflow describe simple-bundling-test

# Execute the saved workflow
uv run pflow simple-bundling-test

# Expected output: "Hello from bundled workflow"

# Clean up
rm -rf ~/.pflow/workflows/simple-bundling-test
```

## Test 2: Save workflow with file reference (prompt)

Verifies that `- prompt: ./prompts/greet.prompt.md` is bundled and resolves from the saved location.

```bash
# Validate from source (should pass)
uv run pflow --validate-only examples/bundling/prompt-ref.pflow.md

# Save
uv run pflow workflow save examples/bundling/prompt-ref.pflow.md --name prompt-ref-test

# Verify bundle contains the prompt file
ls -la ~/.pflow/workflows/prompt-ref-test/
ls -la ~/.pflow/workflows/prompt-ref-test/prompts/
# Expected: entry point + prompts/greet.prompt.md

# Verify the prompt file content
cat ~/.pflow/workflows/prompt-ref-test/prompts/greet.prompt.md
# Expected: the greeting prompt template

# Verify the save output mentions bundled files
# Expected output includes: "Bundled 1 file:"

# Clean up
rm -rf ~/.pflow/workflows/prompt-ref-test
```

## Test 3: Save workflow with command file reference

Verifies that `- command: ./scripts/hello.sh` is bundled and resolves from the saved location.

```bash
# Execute from source (should work)
uv run pflow examples/bundling/command-ref.pflow.md

# Save
uv run pflow workflow save examples/bundling/command-ref.pflow.md --name command-ref-test

# Verify bundle
ls -laR ~/.pflow/workflows/command-ref-test/
# Expected: entry point + scripts/hello.sh

# Execute the SAVED workflow — this is the critical test
uv run pflow command-ref-test

# Expected: same output as running from source ("Hello from bundled script")
# This proves file references resolve from the bundle directory.

# Clean up
rm -rf ~/.pflow/workflows/command-ref-test
```

## Test 4: Save workflow with sub-workflow reference

Verifies that `- workflow: ./sub-echo.pflow.md` is bundled alongside the parent.

```bash
# Execute from source
uv run pflow examples/bundling/parent-with-sub.pflow.md input="test message"

# Save
uv run pflow workflow save examples/bundling/parent-with-sub.pflow.md --name sub-ref-test

# Verify bundle
ls -laR ~/.pflow/workflows/sub-ref-test/
# Expected: entry point + sub-echo.pflow.md

# Execute the saved workflow
uv run pflow sub-ref-test input="bundled sub test"

# Expected: same output as running from source (uppercased input)

# Clean up
rm -rf ~/.pflow/workflows/sub-ref-test
```

## Test 5: Save with --force replaces entire bundle

Verifies that force-saving replaces old dependencies with new ones.

```bash
# Save v1
uv run pflow workflow save examples/bundling/command-ref.pflow.md --name force-test

# Verify v1 bundle
ls ~/.pflow/workflows/force-test/scripts/
# Expected: hello.sh

# Force-save a different workflow over it
uv run pflow workflow save examples/bundling/prompt-ref.pflow.md --name force-test --force

# Verify v2 bundle — old deps gone, new deps present
ls ~/.pflow/workflows/force-test/
# Expected: force-test.pflow.md + prompts/ (no scripts/)
test ! -d ~/.pflow/workflows/force-test/scripts && echo "PASS: old deps removed" || echo "FAIL"

# Clean up
rm -rf ~/.pflow/workflows/force-test
```

## Test 6: Existing nested workflow example still works

Regression test — the existing nested workflow examples should still work.

```bash
# Execute nested workflow from source
uv run pflow examples/nested/document-processor.pflow.md title="Hello" body="World"

# Expected: "Title: HELLO\nBody: WORLD"
```

## Test 7: Existing file-reference examples still work

Regression test — the existing file-reference examples should still validate.

```bash
# Validate all file-reference examples
uv run pflow --validate-only examples/file-references/prompt-file-ref.pflow.md
uv run pflow --validate-only examples/file-references/command-file-ref.pflow.md
uv run pflow --validate-only examples/file-references/code-file-ref.pflow.md
uv run pflow --validate-only examples/file-references/no-file-refs.pflow.md

# Execute the ones that don't need LLM
uv run pflow examples/file-references/command-file-ref.pflow.md
uv run pflow examples/file-references/code-file-ref.pflow.md input="test data"
```

## Test 8: workflow list shows folder-based workflows

Verifies the listing works with the new folder storage format.

```bash
# Save two workflows
uv run pflow workflow save examples/bundling/simple.pflow.md --name list-test-a
uv run pflow workflow save examples/bundling/command-ref.pflow.md --name list-test-b

# List should show both, sorted
uv run pflow workflow list
# Expected: both list-test-a and list-test-b appear with descriptions

# Filter
uv run pflow workflow list list-test
# Expected: both appear

# Clean up
rm -rf ~/.pflow/workflows/list-test-a ~/.pflow/workflows/list-test-b
```

## Test Fixtures

The following example files are used by the tests above:

- `examples/bundling/simple.pflow.md` — workflow with no file dependencies
- `examples/bundling/command-ref.pflow.md` — workflow referencing `./scripts/hello.sh`
- `examples/bundling/scripts/hello.sh` — shell script dependency
- `examples/bundling/prompt-ref.pflow.md` — workflow referencing `./prompts/greet.prompt.md`
- `examples/bundling/prompts/greet.prompt.md` — prompt file dependency
- `examples/bundling/parent-with-sub.pflow.md` — parent workflow referencing `./sub-echo.pflow.md`
- `examples/bundling/sub-echo.pflow.md` — sub-workflow that echoes input uppercased
