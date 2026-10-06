# Task 118: Code Block Linting and Shell Node Variable Injection

## Description

Make the shell node bind values the way the code node already does — declared `inputs:` become
shell variables, the body is plain POSIX sh and never a pflow template — and settle, in the same
task, the one residual place where code is still interpolated (code handed to MCP tools). Then add
linting for code blocks (ruff for Python, shellcheck for shell), which the clean bodies make possible.
Phase 1 (binding) is the language fix for #621/#59; phase 2 (linting) is the pay-off.

## Status
not started

## Priority

medium

## Roadmap

next

> **Refreshed 2026-10-05 against main `90b891cb` (session-10).** Blocker cleared: Task 170 merged
> 2026-10-01 (PR #673) and the deferred language ruling was taken today — see Design Decisions. ADR-0016
> records it. Phase 1 serializes behind the open lane for #678 (it edits
> `core/workflow/validator.py` — which params are templated — the surface phase 1 changes).

## Problem

Task 107 (markdown workflow format) ships with minimal code block validation: `ast.parse()` for Python syntax and `yaml.safe_load()` for YAML config blocks. This catches syntax errors but misses:

- **Python**: Undefined names, unused imports, common bugs (ruff catches these)
- **Shell**: Quoting issues, bash pitfalls (shellcheck catches these)

Shell blocks have a deeper problem: template variables like `${fetch.response}` are replaced **inline** in the command string. This means:
- The shell command is not valid bash on its own (can't lint it)
- `${fetch.response}` looks like bash variable expansion, confusing both tools and humans
- There's no separation between pflow template syntax and bash syntax
- **Observed (#621, measured 2026-10-05 on main):** ordinary shell syntax is unusable in a body —
  `${NAME:-world}` and `${#X}` are "malformed template" errors, `${HOME}` is "references an
  undeclared input"; the only way through is the `$${…}` escape on every brace (the guide tells
  authors to write `$VAR` instead). **#59:** a value interpolated into a quoted shell context breaks
  on quotes — injection by construction.
- **Observed (#550):** the same interpolation into JavaScript handed to MCP tools (`evaluate_script`)
  breaks pflow's own screenshot workflows on apostrophes (`Don't Stop`); pflow cannot inject
  variables into a string another tool executes, so that surface stays interpolated and needs a
  quote-safe filter.

The Python code node (Task 104) already solved this — template variables are in the `inputs` param, not inside the code. Shell should follow the same pattern.

## Solution

Three parts:

### 1. Shell node refactor: variable injection

Change shell nodes from inline template replacement to variable injection:

**Current behavior** (inline replacement):
```bash
# pflow replaces ${fetch.response} with the actual value in the string
curl -s "https://api.example.com/${endpoint}" | jq '.name'
```

**New behavior** (variable injection):
```bash
# pflow injects variables at the top, command is clean bash
endpoint='api.example.com/users'

curl -s "https://${endpoint}" | jq '.name'
```

This makes the shell command valid bash that shellcheck can lint.

### 2. ruff integration for Python code blocks

- Generate wrapper code around each Python code block (declaring input variables so ruff doesn't flag them as undefined)
- Run `ruff check` on the wrapped code
- Parse ruff output and map line numbers back to markdown source
- Evaluate whether ruff should be a runtime dependency (~26 MB binary) or optional

### 3. `pflow validate --lint` command

- Extract code blocks from markdown workflows
- Run ruff on Python blocks, shellcheck on shell blocks
- Report errors with markdown line numbers
- Graceful degradation if shellcheck isn't installed (it's not a Python package)

## Design Decisions

**Decision ledger (user rulings, session-10, 2026-10-05).** Context: Task 170 deferred ONE language
ruling on non-pflow `${…}` (#621, #550, #59; recorded in its "Deferred by design"). Four options were
weighed — (1) strict everywhere + `$${` escape (status quo), (2) tolerate non-grammar `${…}` inside
code-bearing params only, (3) tolerate everywhere as a warning, (4) code-bearing bodies are never
templated; values bind through `inputs:` (the code node's existing pattern). The orchestrator first
recommended (2) now + (4) later; the user: *"isnt the real fix to do 4. task 118 or?"* — correct: (2)
would be built for shell/code bodies and then deleted by (4). Ruling, *"yes to all"*:

- **DECIDED — code-bearing bodies are never pflow templates.** `shell.command` AND `code.code` are
  exempt from scanning/resolution (CORRECTION from the ADR review, 2026-10-05: the code body is
  templated today too — `template_resolution.py:111-114`, `template_surfaces.py:77-80` have no
  per-param exemption; the guide's "never templates in the code block" is an authoring rule). Values
  reach a shell body only as shell variables; `${…}` in it is plain POSIX sh. #621's shell half and
  #59 close structurally. The exemption is new machinery at both the validator surface walk and the
  runtime split. Contract: ADR-0016.
- **DECIDED 2026-10-05 (user: *"yes go ahead witht this"*) — the shell binding param is the existing
  `env:`** (`shell.py:437`; binds as environment variables, quote-safe today). Rejected: `inputs:` with
  shell-specific semantics — `inputs:` already means "template variables" on every node, so it would be a
  redefinition, and a second binding mechanism beside `env:` fails the deletion test. Limits the plan
  states in the guide: strings only, ~128 KiB per value on Linux (large values via `stdin`, the
  documented channel), case-insensitive names on Windows, never `PATH`/`IFS`-style names.
- **DECIDED 2026-10-05 — MCP code-bearing params tolerate every non-pflow `${…}`, identifier-shaped
  included** (that surface is explicitly another language's; `` `${user.name}` `` works unescaped;
  typo detection is given up THERE only). Rendering of the resulting diagnostics stays show-before-code
  (the planner drafts the before/after). Everywhere else identifier-shaped unknowns remain errors.
- **DECIDED — the residual is MCP code-bearing params only.** Code handed to a third-party tool
  stays interpolated. There, and only there, non-grammar `${…}` (`${a + b}`, `${x:-y}`) is tolerated
  and passed through; on every OTHER templated surface identifier-shaped unknowns (`${nod.result}`)
  stay errors (typo detection — Task 170's constraint); the MCP-code-param case is the OPEN item
  above. How a param is identified as code-bearing (tool schema, allowlist, node-type knowledge) is
  an Open Question. Under Task 170's AST this is policy over Issues per surface, never a parse mode.
- **Shell-specific checks the plan must re-home or retire, not silently drop** (ADR review):
  the dangerous-pattern check on the resolved command (`shell.py:777`, would see `$dir` not the value),
  the dict/list type check on `command` incl. its quote-escape tier (`type_validation.py:158-295`),
  the loop-carry warning whose text says `inputs:` is inert for shell (`validator.py:443-490`), and
  the trace/audit view (raw body vs. what ran). The Windows bridge (`shell.py:78-96`) stays on the body.
- **DECIDED — a `${var|json}` template filter** (#550) substitutes a JSON/JS literal, quote-safe by
  construction; the in-tree screenshot workflows and the skill docs drop the "use double quotes
  inside" caveat. Shell needs no sibling filter once values are variables.
- **DECIDED — linting is phase 2, not the fix.** The original bundling rationale ("the refactor's
  value is proven by linting working") is inverted: the binding change is the language fix and
  stands alone; linting is its pay-off. If phase 2 grows a tail it becomes its own task
  (ORCHESTRATION: a slice gated on work outside the task is its own task).
- **Deferred by design:** file-referenced code (`- command: ./cmd.sh`) follows the body rule of the
  node it feeds; a raw/untemplated mode for other params (#621 option 3) is not built — nothing calls it.

- **Shell refactor bundled with linting** (superseded by the ledger above — kept for history): The shell variable injection and shellcheck linting are interdependent — linting shell blocks is pointless without clean bash, and the refactor's value is proven by linting working
- **ruff as potential runtime dependency**: ~26 MB, about 9% of current install size. Already a dev dependency. Decision on runtime vs optional deferred to implementation
- **shellcheck is external**: Not a Python package — can't be bundled. `pflow validate --lint` should work without it (just skip shell linting with a message)
- **Wrapper generation for ruff**: Python code blocks have injected input variables (bare type annotations like `records: list[dict]`). ruff needs these declared as actual assignments to avoid false "undefined name" errors

## Dependencies

- **Task 170 (One Template Language) — MERGED 2026-10-01 (PR #673)**; the language ruling it
  deferred is taken (Design Decisions). The one parser (`core/templates`) is where the per-surface
  policy and the `|json` filter land; read `task_170/task-review.md` first.
- **Serialize behind #678** (open lane, `core/workflow/validator.py` + `runtime/template_validation/`
  — the "which params are templated / field-checked" surface this task changes). Disjoint from Task 179
  (engine/resume/trace).
- **ADR-0013** (POSIX sh everywhere, Git Bash on Windows) is unchanged and binds the injection: quoting
  must be POSIX-sh-safe, and the `tests-windows` CI gate is blocking for the shell node.
- Related issues this task closes or re-homes: #621 (shell half structurally; JS half via tolerance),
  #59 (shell injection), #550 (`|json`); re-read #620 (the `$${` escape stays as the opt-out elsewhere).
- Task 107: Markdown Workflow Format — must be implemented first (this task lints markdown code blocks)
- Task 104: Python Code Node — already implemented, defines the input injection pattern that shell should follow

## Implementation Notes

### Shell node refactor considerations

- Template values may contain newlines, quotes, special characters — bash variable assignment needs proper escaping
- The `inputs` pattern from the code node could be reused: declare inputs in node params, inject as bash variables
- Existing shell workflows use `${node.output}` inline — this is a breaking change to shell node behavior
- Need to convert existing example workflows and verify equivalent behavior
- Consider: should shell nodes get an `inputs` param like code nodes?

### ruff wrapper generation

The code node convention: bare type annotations (`records: list[dict]`) are inputs injected by pflow. ruff sees these as undefined. The wrapper needs to:
1. Parse type annotations from the code block
2. Generate assignment stubs: `records: list[dict] = ...  # type: ignore`
3. Prepend to the code block
4. Run ruff on the combined file
5. Offset line numbers by the header size when mapping back

### Template variable handling in shell

Currently `${...}` in shell commands is ambiguous — is it pflow template or bash variable? After refactor:
- Bash `${var}` = actual bash variables (including pflow-injected ones)
- No pflow `${...}` syntax inside shell commands
- Template resolution happens in the `inputs` param (frontmatter), not in the command string
- **Breaking by design (no external users):** every inline-templated shell command in `examples/`,
  `src/pflow/guide/nodes/shell.md` (which today teaches `$VAR` vs `${var}` and the `$${` escape),
  `docs/`, the `.pflow.md` validator's shell-param handling, the Windows path-translation bridge
  (`nodes/shell/shell.py:78-96` rewrites paths inside the resolved command — values now arrive as
  variables), and the tests convert. The plan lists them from `grep`, not from memory.
- **Silent-failure risk the plan must settle:** a misspelled variable in the body (`$endpont`) expands
  to empty in POSIX sh — today the same typo is a loud validation error. Options the planner weighs:
  run bodies with unset-variable strictness, validate body references against declared `inputs`
  (shellcheck does this statically), or accept with a documented rule. Not silently.

## Verification

- Existing shell workflows produce identical results after refactor (behavior preservation)
- `pflow validate --lint` catches ruff errors in Python blocks with correct line numbers
- `pflow validate --lint` catches shellcheck errors in shell blocks with correct line numbers
- Template variables in shell work correctly with the injection pattern (including values with special characters, newlines, quotes)
- ruff doesn't produce false positives on code block input declarations
- Graceful behavior when shellcheck is not installed
- Performance: linting doesn't add unacceptable latency to validation

## Open Questions (resolve at start)

- Should ruff be a runtime dependency or optional (`pflow validate --lint` fails gracefully if not installed)? (phase 2)
- ~~Should shell nodes get a formal `inputs` param like code nodes, or inject all template-referenced values automatically?~~ DECIDED: declared `inputs:` (parity with the code node; see the ledger).
- ~~How to handle shell commands that genuinely need bash variable expansion alongside pflow-injected variables?~~ Dissolved: the body is plain sh; `$HOME`, `${HOME}`, `${X:-y}` are all shell.
- How does the validator identify an MCP param as code-bearing for the tolerance policy — by the tool's
  JSON-Schema description/name, a registry allowlist, or node-type knowledge (`evaluate_script`,
  `browser_run_code_unsafe`)? State the mechanism and its failure mode (a tolerant non-code param
  loses typo detection).
- Unbound-variable strictness for shell bodies (Implementation Notes).
- Does the `|json` filter belong to the template grammar generally (Jinja-style `|filter`, one filter
  today) or as a one-off? A grammar extension needs its parity rows in the Task 170 corpus.
