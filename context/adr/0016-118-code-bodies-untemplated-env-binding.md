# Code-bearing bodies are never pflow templates — values bind as variables, the body stays the embedded language

Status: accepted

pflow's `${…}` template syntax is also the native syntax of shell and JavaScript. Today every node
param is scanned and resolved the same way (`runtime/engine/template_resolution.py:111-114`,
`core/workflow/template_surfaces.py:77-82`) — including the shell node's `command` AND the code
node's `code` body; the guide's "templates go in `inputs`, never in the code block" is an authoring
rule, not a mechanism. The consequence is measured: in a shell command `${NAME:-world}` and `${#X}`
are rejected as malformed templates, `${HOME}` as an undeclared input, and a value pasted into a
quoted shell context breaks on quotes (#621, #59). The `$${…}` escape works but must be applied to
every brace of an embedded program.

**Decision (Task 118):** the body of a code-bearing node (`shell.command`, `code.code`) is exempt
from template scanning and resolution — it is plain POSIX sh / plain Python — and values reach it
only through declared bindings that pflow sets as variables: environment variables bound in the
shell node's existing `env:` param; the code node already binds `inputs` into its exec namespace
(`nodes/python/python_code.py:704-708`).

**Decision (Task 181):** code handed to a third-party MCP tool (JavaScript for `evaluate_script`
and the like) cannot receive variables — another process executes the string — so on those params
the rule is the same one, inverted: the text is the embedded language, a bare `${…}` in it is
never a pflow template, and a pflow value enters only through an explicit `${x|json}` reference,
which yields a JSON/JS literal that is quote-safe by construction (#550).

## Considered Options

- **Strict everywhere, `$${` escape as the opt-out (status quo).** One rule, maximal typo
  detection; but a long embedded script needs `$$` on every brace and a missed escape in either
  direction is a silent runtime difference.
- **Tolerate non-grammar `${…}` inside code-bearing params.** A policy switch on the existing
  parser — but for shell and code bodies it would be built, documented, then deleted by the binding
  change.
- **Tolerate everywhere as a warning.** Weakens agent typo detection globally; a stray `${…}` in an
  LLM prompt would be sent literally.
- **Bodies exempt + declared bindings (chosen).** One way to bind values into code across both
  code-bearing nodes; shell injection disappears by construction; bodies become lintable.
- **For MCP code params — tolerate every non-pflow `${…}` while still resolving pflow references
  (ruled first, then replaced).** Whether a `${…}` is "pflow" would depend on what is in scope, not
  on its syntax: a JavaScript `` `${item.id}` `` inside a batch, or `` `${user.name}` `` when an
  input is named `user`, is silently replaced by the pflow value; and at run time "unknown" means
  "absent from the shared store", so a reference to a step on a skipped branch would pass through
  as literal text. The explicit `${x|json}` marker removes both and keeps typo detection on every
  pflow reference.

## Consequences

- **Breaking for every inline-templated shell command** (examples, guide, docs, tests — a few
  hundred sites) — accepted because pflow has no external users and the system's own corpus
  converts in-task.
- **The exemption is new machinery, keyed on (node type, param), and every param walk must consult
  it** — not only the validator surface walk and the runtime split: the type-validation pass, the
  workflow graph builder, the canvas ref-chip scan and the TypeScript grammar mirror each walk
  params on their own. One classification, consulted by all.
- **The shell binding param is the existing `env:`** (`shell.py:438`). `inputs:` was rejected for
  shell: it means "template variables" on every node type — and stays exactly that on a shell step
  (the namespace `env:`, `stdin` and `cwd` draw from, and where loop carry lands) — so
  shell-specific semantics would redefine an existing key, and a second binding mechanism beside
  `env:` fails the deletion test. A looped shell step therefore declares a carried key in
  `inputs:` and binds it in `env:`.
- **A value bound in `env:` becomes exactly the text `${x}` produces inside any string** — one
  function, `core/templates.to_string` — and a string is itself (never re-parsed: no JSON
  auto-parse of `env:` leaves). So a boolean is `True`, null is empty, and an object is
  `{"a": [1, 2]}` (default separators), as inline today. Converted workflows receive byte-for-byte
  what they received inline; JSON-style scalars were rejected because they would change that and
  make `env:` render differently from every other string. Before this decision `env:` accepted
  only strings — any other value passed validation and crashed at spawn. Task 120 (declared input
  types) inherits this rule.
- **Environment binding carries real limits** — no NUL bytes; a total size limit shared by
  arguments and the whole environment (about 1 MiB on macOS; about 128 KiB per variable on Linux);
  names must be valid shell identifiers; names are case-insensitive on Windows; and
  names such as `PATH`, `HOME`, `IFS`, `ENV`, `BASH_ENV`, `PS4`, `LD_PRELOAD` clobber the shell. Large values keep going through
  `stdin`.
- **Typo detection moves from the parser to a static check.** An old-form `${item}` left in a
  shell body is valid sh that expands to empty, `${step-id.stdout}` expands to the text
  `id.stdout`, and `$${X}` becomes the shell's PID followed by `{X}` — so validation flags, inside a
  code-bearing body, a `${…}` that pflow would have resolved before this decision, and the `$${`
  escape. Shell strictness (`set -u`)
  was rejected as the guard: inside `$(…)` or a non-final pipeline stage it prints "unbound variable" but
  the step still exits 0, and ADR-0013 holds that the meaning of an unadorned shell step never changes.
- **Some shell checks lose their object.** The dangerous-command block (`shell.py:776-780`) stays
  on the body text and no longer sees value-driven cases (`rm -rf "$DIR"/*` with an empty value) —
  accepted and documented rather than re-implementing shell expansion; the dict/list block on
  `command` retires with the templated body (objects bind through `env:` as text); the loop-carry
  warning looks at `env:` and `stdin` values instead of the command.
- **ADR-0013 is unchanged.** The Windows path-translation bridge (`shell.py:78-97`) stays on the
  body; whether a Windows path bound through `env:` needs translation is settled by a test in
  Task 118, not assumed here.
- **On a code-bearing MCP param everything outside a `${x|json}` reference is emitted from the
  source text unchanged** — so `$${` stays `$${` there (in JavaScript that is a dollar sign followed
  by an interpolation; collapsing it would drop the `$`), and this is policy over one parse result,
  never a second tokenization. Adding a tool to the set of code-bearing params later changes what
  an existing bare `${x}` in that param means, silently — the validation warning for a
  pflow-shaped `${…}` on such a param is the safety net.
- **`${x|json}` is a grammar extension of the single template parser** (Task 170): it lands in
  `core/templates` and its TypeScript mirror in the same step, with parity rows. It is accepted
  only on code-bearing MCP params at first — widening later is a code change, narrowing after
  workflows use it everywhere would be a corpus sweep.
- Commands loaded from a file (`core/file_resolver.py:38-46`) follow the body rule of the param
  they feed. `write-file` content, HTTP bodies and prompts that happen to carry code stay
  templated — the `$${` escape remains their opt-out.
