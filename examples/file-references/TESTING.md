# Manual Testing Plan — External File References (Task 129)

## Prerequisites

```bash
cd /path/to/pflow
make install  # ensure deps are up to date
```

## Test 1: Prompt File Reference

Verifies that `- prompt: ./prompts/analyze.prompt.md` reads the file and uses it as the prompt.

```bash
# Validate (should pass — template ${input} is a declared input)
uv run pflow --validate-only examples/file-references/prompt-file-ref.pflow.md

# Execute (requires LLM API key)
uv run pflow examples/file-references/prompt-file-ref.pflow.md input="def hello(): pass"
```

**Expected**: Validation passes. Execution sends the external file's content as the prompt.

## Test 2: Code File Reference

Verifies that `- code: ./scripts/transform.py` reads the Python file and executes it.

```bash
# Validate
uv run pflow --validate-only examples/file-references/code-file-ref.pflow.md

# Execute
uv run pflow examples/file-references/code-file-ref.pflow.md input="hello world"
```

**Expected**: Validation passes. Output is "HELLO WORLD".

## Test 3: Batch File Reference

Verifies that `- batch: ./config/reviewers.yaml` reads the YAML file.

```bash
# Validate
uv run pflow --validate-only examples/file-references/batch-file-ref.pflow.md
```

**Expected**: Validation passes. The batch config is loaded from the YAML file.

## Test 4: Command File Reference

Verifies that `- command: ./scripts/greet.sh` reads the shell script content.

```bash
# Execute
uv run pflow examples/file-references/command-file-ref.pflow.md
```

**Expected**: Output includes "Hello from external script!"

## Test 5: Missing File Error

Verifies clear error when a referenced file doesn't exist.

```bash
# Create a workflow referencing a nonexistent file
cat > /tmp/test-missing.pflow.md << 'EOF'
# Missing File Test

## Steps

### step
- type: llm
- prompt: ./nonexistent-prompt.md
EOF

uv run pflow --validate-only /tmp/test-missing.pflow.md
```

**Expected**: Error message includes:
- Node ID and param name
- The original file path
- The resolved absolute path
- The base directory

## Test 6: No File References (Regression)

Verifies existing workflows without file references are completely unaffected.

```bash
uv run pflow examples/file-references/no-file-refs.pflow.md
```

**Expected**: Output includes "Hello world, no file references here"

## Test 7: Existing Example Workflows

Verify no regressions in existing example workflows.

```bash
# Run a few existing examples
uv run pflow --validate-only examples/hello-world.pflow.md
uv run pflow examples/hello-world.pflow.md
```

**Expected**: All pass unchanged.

## Test 8: Mutual Exclusivity

Verifies that having both a YAML param file reference and a code block for the same param produces a parse error.

```bash
cat > /tmp/test-mutual-exclusivity.pflow.md << 'EOF'
# Mutual Exclusivity Test

## Steps

### step

A step.

- type: llm
- prompt: ./some-file.md

```prompt
This is inline content that conflicts.
```
EOF

uv run pflow --validate-only /tmp/test-mutual-exclusivity.pflow.md
```

**Expected**: Parse error: "Parameter 'prompt' is defined both inline and as a code block."

## Test 9: Template Variables in External Files

Verifies that `${var}` in external files are properly validated.

```bash
# Create a prompt with an invalid template variable
mkdir -p /tmp/test-templates/prompts
echo 'Hello ${nonexistent_node.output}' > /tmp/test-templates/prompts/bad.md

cat > /tmp/test-templates/workflow.pflow.md << 'EOF'
# Template Test

## Steps

### step
- type: llm
- prompt: ./prompts/bad.md
EOF

uv run pflow --validate-only /tmp/test-templates/workflow.pflow.md
```

**Expected**: Template validation error about `${nonexistent_node.output}` having no valid source. Error should include:
```
Loaded from file: ./prompts/bad.md
```

This tells the agent which file to edit, not just which node has the problem.

## Test 10: Inline Template Error Has No File Hint

Verifies that inline prompts (no file reference) do NOT show "Loaded from file" in errors.

```bash
cat > /tmp/test-inline-error.pflow.md << 'EOF'
# Inline Error Test

## Steps

### step

A step.

- type: llm

```prompt
Hello ${nonexistent_node.output}
```
EOF

uv run pflow --validate-only /tmp/test-inline-error.pflow.md
```

**Expected**: Template validation error about `${nonexistent_node.output}` but NO "Loaded from file" hint.

## Test 11: Path Traversal Blocked

Verifies that `../../../etc/passwd` style references are rejected.

```bash
cat > /tmp/test-traversal.pflow.md << 'EOF'
# Path Traversal Test

## Steps

### step

A step.

- type: llm
- prompt: ../../../etc/passwd
EOF

uv run pflow --validate-only /tmp/test-traversal.pflow.md
```

**Expected**: Error message containing "escapes workflow directory".

## What to Check for Regressions

1. **`make test`** — All 4162+ tests pass
2. **`make check`** — All lint/type checks pass
3. **Existing workflows** — Run any workflow you regularly use to confirm no behavior change
4. **Nested workflows** — If you have workflows with `- workflow: ./sub.pflow.md`, verify they still work
5. **Node params with paths** — Verify that `file_path`, `url`, `workflow` and similar params are NOT treated as file references
