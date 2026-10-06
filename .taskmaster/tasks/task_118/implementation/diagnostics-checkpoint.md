# Task 118 — diagnostics checkpoint (show before code)

Every message this task adds or changes, and the rule that decides when each one fires.
**BEFORE** blocks are verbatim output of today's code (`b2cd92e3`, macOS, probe workflows run
with `uv run pflow`). **AFTER** blocks are drafts — nothing is built yet; they follow the
renderer's real layout (`Error N: Title` / message / `At:` / fixes / `See also:` at column 0).
Nine rulings were asked for; **all nine were ruled as recommended on 2026-10-06** (main orchestrator, under
the user's end-to-end grant) — see the progress log. The drafts below are the ruled text.

---

## 1. The rule: when is a `${…}` in a command (or code block) an error?

A shell command becomes plain sh and a code block plain Python. pflow parses the body once with
its normal template parser — only to *look* — and sorts each `${…}` it finds by the **step's own
scope**: the workflow's inputs, the step's own `inputs:` keys, a step id when a field follows it
(`${fetch.stdout}`), and — only on a step that is itself batched or looped — its batch alias,
`${__index__}`, `${__iteration__}`.

| What the body contains | Verdict | Why |
|---|---|---|
| `$X`, `$$`, `$(…)`, `${1}`, `${arr[@]}`, `${X%.*}`, `${X:-y}`, `${#X}` where `X` is **not** a name in scope (`${HOME}`, `${CI}`, `${TMPDIR}`, a shell variable of your own) | **shell — never flagged** | pflow never knew that name |
| a bare `${count}` where `count` is a step id | **never flagged** | a bare step id was never a valid reference; `count=…; echo "${count}"` is ordinary sh |
| `${name}`, `${name.field}`, `${name[0]}` whose root **is** in scope | **ERROR** | pflow resolved this before the change; sh would run it wrong or empty |
| `${limit:-10}`, `${#item}`, `${name%.*}` — a shell expansion form whose leading name is in scope | **ERROR** | pflow rejected this before the change; sh would now silently use the default — the author meant the pflow value |
| `$${…}` anywhere in the body (not `$$${…}`, which is sh's pid followed by `${…}`) | **ERROR** | the escape has no meaning in sh |
| in a shell body: `${a.b}`, `${a[0].b}`, `${a ?? "x"}` with a root **not** in scope | **WARNING** *(ruling 2)* | sh cannot expand these shapes; most likely a misspelled step id |

A **code block** is read through Python's own parser: only the text of its string literals is
looked at (the constant parts of an f-string included), so `f"Total: ${total}"` — a dollar sign
followed by a Python interpolation — is never flagged, while `"${name}".upper()` is. A `${…}`
outside a string is a Python syntax error already (the parser reports it today).

The check is static; it runs at validation and again at compile, so a workflow handed to the
compiler as plain IR fails the same way.

**Ruling 1 — accept this rule?** *Recommended: yes.* Alternatives considered: flag by shape only
(every `${a.b}` an error) — leaves no way to write another language's template literal inside a
command and misses the plain `${item}`; use the validator's workflow-wide reference scope — flags
`for item in …; do echo "${item}"` on a step that is not the batch step, with a fix that then fails
at run time.

### The hard cases, resolved by the rule

| Case | Example | Result |
|---|---|---|
| **(a)** a pflow name that is also a shell name | `- inputs: {HOME: …}` or `batch.as: PATH`, body uses `${HOME}` | **ERROR** naming *why* (`'HOME' is a key of this step's inputs:`). Fixes offered both ways: bind it in `env:`, or — if the shell's own variable was meant — write `$HOME` without braces. Unbraced `$NAME` is never checked, so there is always a way out. |
| **(b)** a shell loop variable with the batch alias's name, **on the batch step itself** | `for item in a b; do echo "${item}"; done` | **ERROR**, same message; fix 2 says: only if the command itself assigns `item`, write `$item` or rename it. On any other step the same text is plain sh and is not flagged. |
| **(c)** a `${name}` declared nowhere | `${ENDPONT}` (typo) or `${TMPDIR}` (ambient) | **not flagged** — indistinguishable without running the shell. A misspelled *bare* `$ENDPONT` is silent today; the braced form is loud today and becomes quiet — the same class, owned by Task 182 (shellcheck reports exactly this, executed: SC2153 when the right name is assigned). |
| **(d)** another language's syntax in the body | ``node -e 'console.log(`${user.name}`)'`` | passes (with the ruling-2 warning) unless `user` is in scope; then it is the ERROR and the fix names the collision: rename the name in that program. `${a + b}` is never pflow grammar. |
| **(e)** bash arrays | `${arr[0]}` | passes unless `arr` is in scope. `${arr[@]}` is never pflow grammar. |
| **(f)** a Python f-string printing a dollar amount | `result: str = f"Total: ${total}"` with `total` in `inputs:` | **not flagged** — Python's parser sees `$` + `{total}`; pflow reads only string literals' text. |
| **(g)** a command that *is* a value | `command: ${producer.stdout}` (a generated command) | **ERROR**; the fix says bind it and run it: `eval "$CMD"`. |

---

## 2. Leftover reference — the three likeliest mistakes

### 2a. Batch `${item}`

Probe: a batch step over `["ada", "bob"]` whose command is `echo "hello ${item}"`.

BEFORE (works — pflow pastes the value into the command):
```
✓ Workflow is valid
…
[{"stdout": "hello ada", … "command": "echo \"hello ada\"", "item": "ada", …}, {"stdout": "hello bob", …}]
```
What sh alone does with that text (executed): `echo "[${item}]"` → `[]`, exit 0.

AFTER (`--validate-only` and the run print the same error; nothing executes):
```
✗ Validation failed (1 error):

Error 1: Validation Error

Step 'greet': the command contains ${item} (line 13 of the workflow file) — a pflow reference (this step's batch item). A shell command is plain sh: pflow never fills in ${…} there.
  At: node 'greet', nodes[id=greet].params.command

To fix this:
  1. Bind the value and read it as a shell variable: add `- env: {ITEM: ${item}}` to the step, then replace ${item} with "$ITEM" (${ITEM} where a letter, digit or _ follows; inside single quotes sh expands nothing — close them around it: '…'"$ITEM"'…').
  2. Only if the command itself assigns `item` (a shell variable of your own, e.g. `for item in …`): write $item without braces, or rename it.

See also: pflow guide shell
```
When the step already has `env:`, fix 1 reads `add ITEM: ${item} under the step's existing env:`.

### 2b. A hyphenated step id

Probe: `echo "got: ${fetch-data.stdout}"`.

BEFORE:
```
✓ Workflow is valid
…
got: payload
```
What sh alone does (executed): `${fetch-data.stdout}` → the text `data.stdout` (sh reads
`${name-default}`), exit 0.

AFTER:
```
Error 1: Validation Error

Step 'show': the command contains ${fetch-data.stdout} (line 21 of the workflow file) — a pflow reference (step 'fetch-data'). A shell command is plain sh: pflow never fills in ${…} there.
  At: node 'show', nodes[id=show].params.command

To fix this:
  1. Bind the value and read it as a shell variable: add `- env: {FETCH_DATA_STDOUT: ${fetch-data.stdout}}` to the step, then replace ${fetch-data.stdout} with "$FETCH_DATA_STDOUT" (${FETCH_DATA_STDOUT} where a letter, digit or _ follows; inside single quotes sh expands nothing — close them around it: '…'"$FETCH_DATA_STDOUT"'…').
  2. If ${fetch-data.stdout} belongs to another program inside the command (a JavaScript template literal, say), it collides with step 'fetch-data' — rename the name in that program.

See also: pflow guide shell
```

### 2c. An `inputs:` key (the pattern both tooling workflows use today)

Probe: `- inputs: {cwd_override: ${cwd}}` and
`if [ -n "${cwd_override}" ]; then echo "override:${cwd_override}"; else echo "auto"; fi`, run with `cwd=/tmp`.

BEFORE:
```
✓ Workflow is valid
…
override:/tmp
```
What sh alone would do: `${cwd_override}` is empty → prints `auto` — silently the wrong branch.

AFTER:
```
Error 1: Validation Error

Step 'resolve': the command contains ${cwd_override} (2 places, line 21 of the workflow file) — a pflow reference (a key of this step's inputs:). A shell command is plain sh: pflow never fills in ${…} there.
  At: node 'resolve', nodes[id=resolve].params.command

To fix this:
  1. Bind the value and read it as a shell variable: add `- env: {CWD_OVERRIDE: ${cwd_override}}` to the step, then replace ${cwd_override} with "$CWD_OVERRIDE" (…same clause…).
  2. Only if the command itself assigns `cwd_override` (a shell variable of your own): write $cwd_override without braces, or rename it.

See also: pflow guide shell
```
Several different leftovers in one body produce **one** error for the step, each with its line and
owner, and one paste-able `env:` line:
```
Step 'report': the command contains 3 pflow references — ${fetch.stdout} (line 31, step 'fetch'), ${item} (line 33, this step's batch item), ${limit} (line 33, workflow input 'limit'). A shell command is plain sh: pflow never fills in ${…} there.
  → Bind them: add `- env: {FETCH_STDOUT: ${fetch.stdout}, ITEM: ${item}, LIMIT: ${limit}}` to the step, then replace each with "$FETCH_STDOUT", "$ITEM", "$LIMIT" (…same clause…).
```
Suggested names: the reference upper-cased, every run of non-alphanumerics → `_`; a name the
shell or common tools own (`PATH`, `HOME`, `LANG`, `USER`, `TERM`, `TZ`, `TMPDIR`, `SHELL`, `PWD`,
`CI`, `DEBUG`, …) gets `_VALUE` (`${path}` → `PATH_VALUE`). The JSON diagnostic carries the same
list structurally (`context.body_references: [{reference, owner, line, binding}]`). A workflow
input used only through such a leftover does **not** also get the "Declared input(s) never used"
error — one mistake, one diagnostic.

### 2d. The same check on a code block

Probe: `result: str = "${name}".upper()` with input `name=bob`.

BEFORE (the guide forbids this; nothing enforces it):
```
✓ Workflow is valid
…
BOB
```

AFTER:
```
Error 1: Validation Error

Step 'up': the code contains "${name}" (line 21 of the workflow file) — a pflow reference (workflow input 'name') inside a Python string. A code step's code is plain Python: pflow never fills in ${…} there.
  At: node 'up', nodes[id=up].params.code

  → Declare it in inputs: — add `- inputs: {name: ${name}}` to the step (or `name: ${name}` under the existing inputs:), declare its type in the code (`name: str`), and use the variable `name` in place of the string.

See also: pflow guide code
```
When the root is already one of the step's `inputs:` keys: `→ 'name' is already bound by inputs:
— use the variable name instead of the string "${name}".`

### 2e. A misspelled step id (not in scope, pflow-only shape) — *ruling 2*

Probe: `echo "got: ${fecth.stdout}"` beside a step named `fetch`.

BEFORE (an error with did-you-mean):
```
Error 1: Validation Error

Node 'show' references non-existent node 'fecth' in parameter 'command'.
  At: node 'show', nodes[id=show].params.command

Did you mean one of these?
  - fetch
```
What sh alone does (executed): `bad substitution`, exit 1 — but inside `$(…)` or a pipeline's
earlier stage the step can still finish with exit 0.

AFTER (recommended — a warning; the run proceeds and sh reports what it reports):
```
  ⚠ [show] Step 'show': ${fecth.stdout} in the command is not something sh can expand, and 'fecth' is not a step or input in this workflow. pflow never fills in ${…} in a command.
    → Did you mean 'fetch'? Bind it: add `- env: {FETCH_STDOUT: ${fetch.stdout}}` and read "$FETCH_STDOUT". If the text belongs to another program inside the command, leave it.
```
(without a close match: `→ To use a pflow value, bind it in env: and read "$NAME". If the text
belongs to another program inside the command, leave it.`)

**Ruling 2 — unknown-root, pflow-only shapes in a shell command:**
- **W (recommended): warning** as above. Keeps the typo catch pflow has today; costs a standing
  warning for the rare command that embeds another language's `${a.b}`.
- **E: error.** Strongest typo catch, but hard case (d) then has no way to be written inside a
  command (the embedded program would have to move to a file).
- **N: nothing.**
Not proposed: a did-you-mean on a plain `${endpont}` / `$ENDPONT` beside `ENDPOINT` — it needs to
know what the command itself assigns, and shellcheck already does it (Task 182).

---

## 3. `$${…}` in a body

Probe: `echo "Price: $${PRICE} home=$HOME"`.

BEFORE (the escape hands `${PRICE}` to sh, which expands it — to nothing here):
```
✓ Workflow is valid
…
Price:  home=/Users/andfal
```
What sh alone does with the unconverted text (executed): `$${HOME}` → `<pid>{HOME}`.

AFTER:
```
Error 1: Validation Error

Step 'price': the command contains the escape $${PRICE} (line 13 of the workflow file). A shell command is plain sh, so there is nothing to escape — sh would run $$ as its process id, followed by {PRICE}.
  At: node 'price', nodes[id=price].params.command

  → Write ${PRICE} for a shell expansion.

See also: pflow guide shell
```
When the escaped text is a pflow reference in scope — the three shipped examples write
`$${generate.llm_usage.cost_usd}` meaning "a dollar sign, then the value", and print nothing for
it today (executed: `Execution cost:  for 0.25`) — the fix is instead:
`→ For a dollar sign followed by the value: add `- env: {COST: ${generate.llm_usage.cost_usd}}`
to the step and write \$$COST inside double quotes — e.g. "cost: \$$COST".`
Same error for a code block, with: `→ Python needs no escape: write ${PRICE} as plain text. For the
literal characters $${ split the string: "$$" "{PRICE}".`

**Ruling 3 — `$${` is an error in both bodies, with these fixes?** *Recommended: yes.*

---

## 4. `env:` binding

### 4a. A non-string value — no message; it starts working

Probe: `- env: {PORT: 8080, N: ${count}}` (number input `count=3`), command `echo "port=$PORT n=$N"`.

BEFORE (`--validate-only` says valid, the run crashes with a traceback):
```
✓ Workflow is valid
…
TypeError: expected str, bytes or os.PathLike object, not int
ERROR: Command execution failed: expected str, bytes or os.PathLike object, not int
  show... ✗ Failed

Error: Execution Failed

Command failed with exit code -2: expected str, bytes or os.PathLike object, not int
  At: node 'show'
```

AFTER:
```
port=8080 n=3
```
Values bind as the decided text (`core/templates.to_string`): `3`, `True`, empty for null,
`{"a": 1, "b": [1, 2]}`; a string — JSON-looking or not — arrives byte-for-byte **when bound
directly** (`env: {DATA: ${up.stdout}}`). A value routed through the step's `inputs:` first
(`inputs: {raw: ${up.stdout}}`, `env: {RAW: ${raw}}`, and every loop Carry) is JSON-parsed there
today and re-serialized on binding (`{"a":1}` → `{"a": 1}`) — exactly what the old inline form
produced, unchanged by this task (#686, Task 120).

**A literal YAML value follows the same rule** — `- env: {DEBUG: true}` binds the text `True`
and `[ "$DEBUG" = true ]` is then false. New warning at validation for a literal boolean:
```
  ⚠ [show] Step 'show': env DEBUG is the YAML boolean true and binds as the text True.
    → Quote it ("true") if the command compares text.
```

### 4b. A name sh cannot read

Probe: `- env: {my-var: hello}`, command `echo "v=$my-var"`.

BEFORE (valid, runs, wrong output — sh reads `$my` then `-var`):
```
✓ Workflow is valid
…
v=-var
```

AFTER (validation error; the compiler repeats it for IR handed to it directly; the shell step
repeats it before spawning when the name only appears at run time):
```
Error 1: Validation Error

Step 'show': env name 'my-var' cannot be read as a shell variable.
  At: node 'show', nodes[id=show].params.env.my-var

  → Use letters, digits and underscores, not starting with a digit — e.g. MY_VAR — and read it as "$MY_VAR" in the command.
```
A YAML key that is not text (`1:`, `true:`, `null:`) gets the same error, naming the key as written.

### 4c. Two names that differ only by case

```
Error 1: Validation Error

Step 'show': env names 'Path' and 'PATH' differ only by case — on Windows they are one variable.
  At: node 'show', nodes[id=show].params.env

  → Keep one of them.
```

### 4d. A name the shell itself relies on — *warning, not refusal*

`PATH`, `HOME`, `IFS`, `ENV`, `BASH_ENV`, `PS4`, `LD_PRELOAD`, compared case-insensitively.

```
  ⚠ [show] Step 'show' sets PATH in env:, replacing the PATH the command inherits — commands outside the new value will not be found.
    → To add a directory, leave PATH out of env: and extend it in the command: export PATH="/opt/bin:$PATH" (env: values are not shell-expanded). To pass data, use another name — e.g. TOOL_PATH.
```
(per name: `HOME` — "`~` and tools' config files"; `IFS` — "how the shell splits words"; `ENV` /
`BASH_ENV` — "a file the shell runs before the command"; `PS4` — "expanded by the shell when
tracing"; `LD_PRELOAD` — "a library loaded into every program the command starts".)

Why a warning: `env:` legitimately sets real variables; a refusal would forbid working workflows.

### 4e. `env:` that is not a map

Literal (validation): `Step 'show': env must be a map of NAME: value — got a list.` Whole-value
template that resolves to something else (run time, before spawn): `env must be a map of NAME:
value; ${cfg.env} resolved to a str.`

### 4f. A value that cannot be bound (run time, before the command starts; cannot be swallowed by
`ignore_errors: true`; not retried)

NUL byte:
```
Error: Validation Error

The value bound to DATA in env: contains a NUL byte, which an environment variable cannot hold. Pass that value through stdin instead (`- stdin: ${…}`, read it with cat) and remove DATA from env:.
  At: node 'show'
```
Text the operating system cannot encode (a lone surrogate from a truncated JSON escape): same
shape, "contains a character the operating system cannot put in an environment variable".

Too large (the operating system refuses to start the command; today this is `exit code -2: [Errno
7] Argument list too long`, and `ignore_errors: true` turns it into success):
```
Error: Validation Error

The command could not start: its environment and arguments are too large for the operating system (largest: BODY 1.2 MB bound in env:, the command 3 KB). Pass large values through stdin instead and remove them from env: — on macOS the limit is about 1 MB for everything together.
  At: node 'show'
```
Only the current platform's limit is named; the Linux and Windows figures come from CI before the
guide states them.

**Ruling 4 — accept 4a–4f** (text rule for literals with the boolean warning; clobber list as a
warning; case-duplicates as an error)? *Recommended: yes.*

---

## 5. `inputs:` on a shell step — the loop-carry warning, generalized

Probe: a looped shell step with `inputs: {n: 0}` and `carry: {n: ${count.stdout}}` whose command
never reads it.

BEFORE:
```
  ⚠ [count] Node 'count' carries input 'n', but the shell node's command text does not reference `${n}`. Carrying into `inputs:` alone is inert for shell nodes.
    → Reference `${n}` in the node's command text, or remove the carried key.
```
(Following that advice is exactly the leftover error of section 2.)

AFTER — the same check now covers **every** `inputs:` key of a shell step, carried or not: it
fires when no param of the step other than `inputs:` references the key (`env:`, `stdin`, `cwd`
count), because on a shell step `inputs:` is only the namespace those params read from:
```
  ⚠ [count] Step 'count' carries 'n', but no param of this step except inputs: references ${n}, so the carried value never reaches the command.
    → Bind it: add `- env: {N: ${n}}` (or N: ${n} under the existing env:) and read "$N" in the command — or remove the carried key.
```
```
  ⚠ [fetch] Step 'fetch': inputs: key 'url' is not visible to the command — a shell step reads values through env:.
    → Bind it: add `- env: {URL: ${url}}` and read "$URL" in the command — or remove the key.
```
llm steps keep their carry warning, reworded to match: `Step 'x' carries 'n', but no param of this
step except inputs: references ${n}.` / `→ Reference ${n} in the prompt, or remove the carried key.`

**Ruling 5 — accept, including the new warning for an unread `inputs:` key on a shell step?**
*Recommended: yes* (an agent that knows `inputs:` binds variables for a code step will write it for
a shell step and get an empty value with exit 0).

---

## 6. The shell failure block

Probe (old form): `echo "calling ${endpoint} with ${api_token}" >&2; exit 3`.

BEFORE — the values are visible because they were pasted into the command; so is the secret:
```
Error: Execution Failed

Command failed with exit code 3: calling users with sk-secret-123456

  At: node 'call'

  Shell details:
    Command: echo "calling users with sk-secret-123456" >&2; exit 3
    Stderr: calling users with sk-secret-123456
```

BEFORE, same step already written with `env:` (works today for strings) — the values are gone:
```
  Shell details:
    Command: echo "calling $ENDPOINT" >&2; exit 3
    Stderr: calling users
```

AFTER:
```
Error: Execution Failed

Command failed with exit code 3: calling users

  At: node 'call'

  Shell details:
    Command: echo "calling $ENDPOINT" >&2; exit 3
    Env:
      ENDPOINT=users
      API_TOKEN=<REDACTED>
      (<REDACTED>: hidden because the name looks like a secret)
    Stderr: calling users
```
**Display rule (part of ruling 6).** What a failing step records about its environment is a
*display-safe copy*, made once at the source: masked by key name through the one shared function
(`security_utils.redact_sensitive`, the same path `pflow report` and the web UI use); each value
the exact text the command received (`True`, `3`, `{"a": 1, "b": [1, 2]}` — `to_string`'s default
separators, as in §4a); each value capped at **200
characters** (the cap the `Command:` line already has) ending `… (4,812 chars — full value: pflow
report)`; a newline inside a value shown as `\n`. That one copy is what every surface carries —
the terminal block, the JSON error, the error records of a failed batch item or sub-workflow — so a
secret or a large payload can never reach a surface that does not mask or cap. Full values live in
the trace and `pflow report`. Never `sanitize_parameters` (which cuts anything over 100 characters
to 20).

The JSON error (`--output-format json`, MCP) gains `shell_env` beside `shell_command`, the same copy:
```json
{
 "message": "Command failed with exit code 3: calling users\n",
 "node_id": "call",
 "shell_command": "echo \"calling $ENDPOINT\" >&2; exit 3",
 "shell_env": {"ENDPOINT": "users", "API_TOKEN": "<REDACTED>"},
 "shell_exit_code": 3,
 "shell_stdout": "",
 "shell_stderr": "calling users\n"
}
```
The same `Env:` lines appear in the block shown when a later step references this failed step.

**Ruling 6 — accept the block and the one display-safe copy (masked + 200-char cap everywhere it
travels; full values in the report)?** *Recommended: yes.* Alternative: an uncapped JSON copy —
rejected because the same record reaches batch and sub-workflow error output, where raw item
payloads must not appear.

---

## 7. `pflow report` — a shell step's page

BEFORE, old form (a templated command) — `## Command` shows the resolved text:
```
## Command

```bash
echo "calling users with sk-secret-123456" >&2; exit 3
```
```

BEFORE, the same step written with `env:` — **no `## Command` at all** (it is rendered only for
a templated command), and the values sit under a generic heading:
```
## Resolved Parameters

```json
{
  "env": {
    "ENDPOINT": "users",
    "API_TOKEN": "<REDACTED>"
  }
}
```
```

AFTER — every shell step's page, and every batch item's page, shows its command; bound values get
their own section, as the text the command received, full length, masked by key name:
```
## Command

```bash
echo "calling $ENDPOINT" >&2; exit 3
```

## Env

```json
{
  "ENDPOINT": "users",
  "API_TOKEN": "<REDACTED>"
}
```
```
`env` no longer repeats under `## Resolved Parameters`. A step without `env:` shows `## Command`
only. The trace format does not change.

**Ruling 7 — accept?** *Recommended: yes.*

---

## 8. Messages that disappear

- `Shell node 'show': cannot use ${make.result} (type: object) in command parameter — embedded
  object breaks shell parsing.` with its three fixes. The check is deleted: an object bound through
  `env:` arrives as JSON text, which is the decided rule. (`echo ${make.result}` itself now gets the
  section-2 error.)
- `Node 'forms' references '${HOME}' in parameter 'command' but no inputs are declared…` and
  `Malformed template syntax … '${NAME:-world}' is not a valid template…` no longer fire for a
  command or code block — #621's shell half. Probe after: `X=abc; echo "${NAME:-world} ${#X} ${HOME}"`
  validates and prints `world 3 /Users/…`.

**Ruling 8 — acknowledge.**

---

## 9. One thing that is no longer caught

`rm -rf ${dir}/*` with an empty `dir` resolves to `rm -rf /*` today and is blocked by the
dangerous-command check. Written as `rm -rf "$DIR"/*` the check sees only the text and passes it
(decided 2026-10-06). The guide and the shell step's description will say so in these words:

> The dangerous-command check reads the command text only. It cannot see what a variable will
> hold — guard destructive commands yourself (`[ -n "$DIR" ] || exit 1`).

**Ruling 9 — accept the wording?** *Recommended: yes.*
