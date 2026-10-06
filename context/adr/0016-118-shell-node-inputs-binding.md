# Code-bearing bodies are never pflow templates — values bind as variables, the body stays the embedded language

Status: accepted

pflow's `${…}` template syntax is also the native syntax of shell and JavaScript. Today every node
param is scanned and interpolated the same way (`runtime/engine/template_resolution.py:111-114`,
`core/workflow/template_surfaces.py:77-80`) — including the shell node's `command` AND the code
node's `code` body; the guide's "templates go in `inputs`, never in the code block" is an authoring
rule, not a mechanism. The consequence is measured: in a shell command `${NAME:-world}` and `${#X}`
are rejected as malformed templates, `${HOME}` as an undeclared input, and a value interpolated into
a quoted shell context breaks on quotes (#621, #59). The `$${…}` escape works but must be applied to
every brace of an embedded program.

**Decision (Task 118):** the body of a code-bearing node (`shell.command`, `code.code`) is exempt
from template scanning and resolution — it is plain POSIX sh / plain Python — and values reach it
only through declared bindings that pflow sets as variables (shell variables for the shell node; the
code node already binds `inputs` into its exec namespace, `nodes/python/python_code.py:704-708`).
The one surface that stays interpolated is code handed to a third-party MCP tool (JavaScript for
`evaluate_script` and the like), because pflow cannot inject variables into a string another
process executes. There, non-grammar `${…}` (`${a + b}`, `${x:-y}`) is tolerated and passed
through, and a `${var|json}` filter makes interpolated strings quote-safe (#550). Under Task 170's
single parser this tolerance is policy per surface over parse results, never a second grammar.

## Considered Options

- **Strict everywhere, `$${` escape as the opt-out (status quo).** One rule, maximal typo
  detection; but a long embedded script needs `$$` on every brace and a missed escape in either
  direction is a silent runtime difference.
- **Tolerate non-grammar `${…}` inside code-bearing params.** A policy switch on the existing
  parser — but for shell and code bodies it would be built, documented, then deleted by the binding
  change; it survives only for MCP code params, which is where it lands here.
- **Tolerate everywhere as a warning.** Weakens agent typo detection globally; a stray `${…}` in an
  LLM prompt would be sent literally.
- **Bodies exempt + declared bindings (chosen).** One way to bind values into code across both
  code-bearing nodes; shell injection disappears by construction; bodies become lintable.

## Consequences

- **Breaking for every inline-templated shell command** (examples, guide, docs, tests) — accepted
  because pflow has no external users and the system's own corpus converts in-task.
- **The exemption is new machinery, per node type and param, applied at both the validator surface
  walk and the runtime split** — there is no existing exemption to reuse.
- **The shell binding param is the existing `env:`** (`shell.py:437`), which already binds values as
  environment variables quote-safely. `inputs:` was rejected for shell: it means "template variables"
  on every node type, so shell-specific semantics would redefine an existing key, and a second
  binding mechanism beside `env:` fails the deletion test. Environment binding carries real limits —
  strings only, no NUL bytes, ~128 KiB per variable on Linux (large values keep going through
  `stdin`, the documented channel), case-insensitive names on Windows, and `PATH`/`IFS`-style names
  clobber the shell.
- **Typo detection moves and some shell checks go dead or invert.** A misspelled `$endpont` expands
  to empty in POSIX sh where today it is a loud validation error; the dangerous-pattern check on the
  resolved command (`shell.py:777`) would see `rm -rf "$dir"` instead of the value; the
  dict/list-param type check on `command` and the loop-carry warning for shell lose their object.
  Task 118 settles each — not silently.
- **ADR-0013 is unchanged.** The Windows path-translation bridge (`shell.py:78-96`) stays on the
  body (it also rewrites paths the author typed); shell variable expansion does not touch
  backslashes, so bound values most likely need no translation.
- **In MCP code params a JavaScript template literal with an identifier (`` `${user.name}` ``) is
  indistinguishable from a pflow typo.** Decided: that surface tolerates every non-pflow `${…}`,
  identifier-shaped included — it is explicitly another language's text, and the cost (typo detection
  lost on that one surface) is paid there only; everywhere else identifier-shaped unknowns stay
  errors.
- Commands loaded from a file (`core/file_resolver.py:38-46`) follow the body rule of the param they
  feed. `write-file` content, HTTP bodies and prompts that happen to carry code stay templated — the
  `$${` escape remains their opt-out.
