# Braindump: Task 118 — Code Block Linting & Shell Node Variable Injection

## Where I Am

Task 118 was created during a Task 107 (Markdown Workflow Format) design session. We were deciding linting scope for markdown code blocks and the user asked a question that opened up a bigger idea: should shell nodes work like the code node, with variables injected rather than inlined?

No implementation was done. No codebase exploration specific to the shell node refactor was done. This task emerged organically from the linting discussion and was captured as a future task. The task file at `.taskmaster/tasks/task_118/task-118.md` has the full spec.

## User's Mental Model

### How the idea emerged

We were discussing linting scope for Task 107. I presented three levels: no linting, syntax validation (`ast.parse()`), full linting (ruff/shellcheck). I recommended syntax validation as the sweet spot.

The user then asked: **"do you think bash should be handled like code node with templated variables being inserted as variables at beginning programmatically rather than replaced inline?"**

This wasn't about linting — it was about the shell node's fundamental design. The user saw the inconsistency: the code node (Task 104) injects inputs as typed variables, keeping the code clean. Shell nodes inline-replace `${...}` in the command string, making the command not valid bash on its own.

Follow-up: **"can you define types in shell like in code? and what about output?"** — I explained that bash has no type system, everything is strings in/out. The user understood this means shell can't get the same benefits as Python, which reinforced that the code node is the right tool for data transformations and shell should be for genuinely shell-specific things.

The user then asked about ruff's install size, I checked (~26 MB), and the user decided: **"yes we should add linting later, then we should evaluate both code node and bash node, this task could probably also include refactor bash to allow for better linting."**

### What they care about

The user sees consistency between node types as important. The code node has a clean pattern (inputs declared separately, code is clean Python). Shell being different feels wrong to them. But they're pragmatic — this is future work, not blocking Task 107.

## Key Insights

### The code node pattern is the template

Task 104 established the pattern: template variables in `inputs` param (frontmatter), code is clean and lintable. This pattern should extend to shell. The implementing agent should read Task 104's design thoroughly — it's the blueprint.

### Shell's limitations are real

Bash has no types. No structured output. Everything is strings. The variable injection pattern gives you lintable bash, but NOT the type safety or structured I/O that the code node has. Don't try to make shell nodes into code nodes — they serve different purposes.

### The `${...}` ambiguity is a real problem

Currently in shell commands, `${fetch.response}` is a pflow template and `${HOME}` is a bash variable — but they use IDENTICAL syntax. After the refactor, pflow-injected values become regular bash variables. But the implementing agent needs to figure out: how do you distinguish between "this `${var}` should be injected by pflow" and "this `${var}` is a regular bash variable"?

In the code node this is clean: the `inputs` param lists what pflow injects, everything else is Python. Shell could follow the same pattern: `inputs` lists what pflow injects as bash variables, everything else in the command is regular bash.

### ruff wrapper generation is non-trivial

The code node's input convention (bare type annotations like `records: list[dict]`) is NOT valid standalone Python — ruff would flag `records` as undefined on the next line. The wrapper needs to turn annotations into assignments (`records: list[dict] = ...  # type: ignore`). This requires parsing the code block's AST to find bare annotations, which is doable but not trivial.

## Assumptions & Uncertainties

**ASSUMPTION**: The shell node refactor is a breaking change that's acceptable because we have zero users. This was not explicitly confirmed for Task 118 specifically, but the user has said "no backwards compatibility" repeatedly in the Task 107 context.

**ASSUMPTION**: shellcheck is worth supporting even though it can't be bundled. The user didn't explicitly say they want shellcheck — the discussion was about ruff (Python) and the shell refactor. shellcheck was my suggestion.

**UNCLEAR**: Whether ruff should be a runtime dependency or optional. We checked the size (26 MB, ~9% of install) but the user didn't decide. The task file lists this as an open question.

**UNCLEAR**: The exact mechanism for shell variable injection. Should it literally prepend `var='value'` lines? Use `export`? Use `env` command? How to handle values with single quotes, newlines, binary data? None of this was discussed.

**NEEDS VERIFICATION**: How the current shell node template resolution actually works. I described it as "inline string replacement" but didn't verify the implementation. Check `src/pflow/nodes/shell/` and `src/pflow/runtime/template_resolver.py`.

**NEEDS VERIFICATION**: Whether any existing workflows depend on the `${...}` being bash-compatible. For example, does anyone write `${HOME}` in a shell command expecting it to be a bash variable? If so, the refactor could break that.

## Unexplored Territory

**UNEXPLORED**: How does stdin work with the shell node refactor? Currently `- stdin: ${fetch.response}` pipes data to the command via stdin. Does this interact with variable injection? If inputs are injected as variables, is stdin still separate?

**UNEXPLORED**: Performance impact of variable injection. For large template values (e.g., `${fetch.response}` being a 100KB string), prepending it as a bash variable assignment could be slow or hit argument length limits. Inline replacement doesn't have this problem because it becomes part of the command string.

**CONSIDER**: Bash variable assignment has a maximum size on some systems (typically ~128KB for `ARG_MAX`). Large node outputs injected as variables could hit this. The current inline approach avoids this by building one big string. Consider using heredocs or temp files for large values.

**CONSIDER**: Should the shell `inputs` pattern be optional? Maybe some shell commands are simple enough that inline `${...}` is fine (e.g., `echo ${greeting}`). Forcing the inputs pattern on everything adds verbosity. But having TWO patterns (inline for simple, inputs for complex) is exactly the inconsistency the user dislikes.

**MIGHT MATTER**: The shell node might need an `outputs` declaration too, not just `inputs`. Currently shell output is always stdout (captured as a string). But if we're aligning with the code node pattern, should shell nodes declare what they produce?

**MIGHT MATTER**: How does this interact with Task 107's `shell command` code blocks? The markdown format was designed with inline `${...}` in shell commands. If we change shell to use variable injection, the markdown format for shell nodes changes too — inputs would need to be declared in the `- inputs:` param, and the code block would use regular bash variables.

## What I'd Tell Myself

1. **This task is less urgent than it looks.** The user explicitly deferred it — Task 107 ships with `ast.parse()` only. Don't let this block markdown format work.

2. **Start with the shell node refactor, not ruff.** The shell change is the architectural decision. ruff integration is mechanical work that follows from it. Get the variable injection pattern right first.

3. **Study the code node implementation first.** Task 104's `PythonCodeNode` is the blueprint. Understand how it handles `inputs`, how it injects variables, how it captures `result`. Then figure out what the shell equivalent looks like.

4. **The `${...}` ambiguity is the hardest design problem.** How to transition from "all `${...}` are pflow templates" to "pflow injects named bash variables, bash `${...}` is just bash." This needs careful thought.

5. **Test with real workflows.** The `examples/real-workflows/` directory has shell-heavy workflows. Convert them to the new pattern and verify identical behavior.

## Open Threads

### Thread 1: ruff as runtime vs optional dependency

26 MB. Not huge but not nothing. If it's optional, `pflow validate --lint` degrades gracefully. If it's runtime, it always works. The user seemed leaning toward evaluating this during implementation rather than deciding now.

### Thread 2: The markdown format implications

Task 107's format spec shows shell commands with `${...}` inline:
```markdown
### fetch
- type: shell

```shell command
curl -s "https://api.example.com/${endpoint}"
```
```

After the shell refactor, this would become:
```markdown
### fetch
- type: shell
- inputs:
    endpoint: ${some-node.output}

```shell command
curl -s "https://api.example.com/${endpoint}"
```
```

The `${endpoint}` in the shell block is now a BASH variable (injected by pflow from inputs), not a pflow template. This is cleaner but changes the markdown format for shell nodes. Task 107 should be implemented with the CURRENT inline pattern since the refactor is future work.

### Thread 3: Should this be one task or two?

The user suggested bundling the shell refactor with ruff/linting. But they're somewhat independent:
- Shell refactor is an architectural change to one node type
- ruff integration is a tooling addition to the validation pipeline
- shellcheck integration depends on the shell refactor

Could be: Task 118a (shell refactor) → Task 118b (ruff + shellcheck linting). Or keep as one task. Implementing agent should decide based on scope.

## Verified Technical Details (from Task 107 codebase investigation)

These findings were verified against the actual code during Task 107's design session. They're relevant context for this task.

### Why inline templates don't work for the code node (and implications for shell)

Template resolution for dict/list values uses `json.dumps()` (`template_resolver.py:464-471`). When `${fetch.result}` resolves inside a string, a Python list becomes a JSON string literal embedded in code — which breaks `ast.parse()`. That's why the code node MUST use the separate `inputs` dict with `resolve_nested()` (which preserves native Python types).

For shell, this is actually different: bash variables are always strings, so JSON serialization is fine. A shell command can receive `records='[{"id": 1}, {"id": 2}]'` and pipe it to `jq`. The problem with inline templates in shell is lintability and syntax ambiguity, not type preservation.

### Code node validation pattern (the blueprint)

The code node (`python_code.py`) validates inputs in `prep()`:

1. `_check_input_annotations(inputs, annotations)` — every key in `inputs` must have a matching bare type annotation in the code (`records: list[dict]`). Missing annotation → error with suggestion.
2. `_check_input_types(inputs, annotations)` — `isinstance()` check that the resolved input value matches the declared type. Mismatch → error with suggestion.

For shell, #1 has no equivalent (bash has no type annotations). #2 is meaningless (everything is a string). So shell validation would be limited to: verifying that `inputs` keys match bash variables referenced in the command (via regex for `${var}` or `$var`). This is weaker than the code node's validation but still catches mismatches.

### Registry interface metadata structure

Verified: `interface["params"]` is a list of dicts `{"key": str, "type": str, "description": str}`. No `required: bool` field exists — required/optional is only in description text. See [Issue #76](https://github.com/spinje/pflow/issues/76) for the required param validation improvement.

Task 107 adds **unknown param warnings** during compilation (comparing actual params against `interface["params"]` keys). After the shell refactor, if shell nodes gain an `inputs` param, the interface metadata would need updating. The unknown param warning would automatically catch agents who use the old inline pattern after the refactor.

### YAML type coercion matters for shell variable injection

PyYAML coerces types: `- timeout: 30` → int, `- enabled: true` → bool. For the code node, this is desirable (Python uses these types natively). For shell variable injection, ALL values need to become strings for bash assignment. The injection logic must handle: `int` → `"30"`, `bool` → `"true"`, `list` → JSON string, `dict` → JSON string, `None` → empty string or `""`.

### `additionalProperties: True` on node params

The IR schema allows any params (`ir_schema.py:207`). Nodes use `.get()` and ignore unknown keys. After the shell refactor, old-style workflows with inline `${...}` would have template resolution happen on the `command` string (old behavior). New-style workflows with `inputs` would have template resolution on the `inputs` dict. The transition needs to be clean — either support both patterns temporarily or break the old one (acceptable with zero users).

### Large value injection: heredocs over variable assignment

Bash variable assignment (`var='...'`) hits `ARG_MAX` limits (~128KB-2MB depending on system). For large node outputs (common — LLM responses, fetched web pages), consider:

```bash
# Instead of:
response='<100KB of text with quotes and newlines>'

# Use heredoc:
read -r -d '' response <<'PFLOW_EOF'
<100KB of text, no escaping needed>
PFLOW_EOF
```

Or use temp files / stdin for very large values. The shell node already supports `- stdin: ${node.output}` which avoids this problem entirely — stdin has no size limit. The `inputs` pattern might be best limited to small/medium values, with stdin remaining the path for large data.

### The stdin interaction question

Currently `- stdin: ${fetch.response}` pipes data to the shell command via stdin. If shell gains an `inputs` param for variable injection, stdin remains separate — it's a different input mechanism (piped data vs environment/local variables). Both can coexist:

```markdown
### transform
- type: shell
- inputs:
    format: ${config.output_format}
- stdin: ${fetch.response}

```shell command
# 'format' is a bash variable (injected from inputs)
# stdin has the response data (piped)
cat | jq -r ".items[] | .${format}"
```
```

This is clean — `inputs` for config values, `stdin` for data streams.

## Relevant Files & References

### Must-read before implementation
- `.taskmaster/tasks/task_118/task-118.md` — the task spec created in this session
- `.taskmaster/tasks/task_107/research/design-decisions.md` — Decision on linting scope, verified assumptions section
- `src/pflow/nodes/python/python_code.py` — the code node implementation (the pattern to follow)
- `src/pflow/nodes/shell/` — current shell node implementation (what gets refactored)
- `src/pflow/runtime/template_resolver.py` — how `${...}` template resolution works today

### Context from Task 107 design
- `.taskmaster/tasks/task_107/research/format-spec-decisions.md` — the markdown format spec (shows current shell command format with inline `${...}`)
- `.taskmaster/tasks/task_107/starting-context/braindump-task104-design-implications.md` — how Task 104 design influenced Task 107, relevant patterns

### Example workflows with shell nodes
- `examples/real-workflows/generate-changelog/workflow.json` — heavy shell usage with jq
- `examples/real-workflows/webpage-to-markdown/workflow.json` — shell nodes with template variables

## For the Next Agent

**Start by**: Reading the code node implementation (`src/pflow/nodes/python/python_code.py`) to understand the input injection pattern. Then read the shell node implementation to understand what changes.

**Don't bother with**: The braindumps in Task 107's `starting-context/` — they're pre-design exploration. The task file and the design-decisions doc have everything you need.

**The user cares most about**: Consistency between node types (code node pattern = good, shell should follow). And lintability — the whole point is that code blocks in markdown should be lintable with standard tools.

**Key risk**: The `${...}` syntax ambiguity between pflow templates and bash variables. Get this design right before writing code.

**This is not urgent**: Task 107 ships first with `ast.parse()` only. This task is a follow-up for when the markdown format is stable and working.

---

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
