# Task 118 — implementation plan

Shell and code bodies are plain code; `env:` is the shell binding.
Spec: `../task-118.md` · Contract: `context/adr/0016-118-code-bodies-untemplated-env-binding.md` ·
Planner: Fable task-planner, 2026-10-06, on `b2cd92e3` (line numbers below were read on that commit —
re-verify before editing; three lanes merge around this task).

**Read with this plan:** `diagnostics-checkpoint.md` (same folder — every new/changed message, BEFORE
executed, AFTER drafted; **an embedded user checkpoint, already built — do not rebuild it**) and
`inventory.py` (same folder — the counted corpus; re-run it, do not re-derive it).

**Shape:** two PRs (§4.0 — the planner's proposal; the main orchestrator rules at launch).
Part 1 = `env:` as a working channel + the two tooling workflows. Part 2 = display, corpus
conversion, the flip, web, docs. **Engine contact in both parts** (`runtime/engine/template_resolution.py`,
`runtime/engine/types.py`) → the build serializes with all other engine work (#503 edits the same file).
**No trace-format change** (D12). **Platform-sensitive** (subprocess environment) → the blocking
`tests-windows` job; Part 1 is where it is first exercised (D8).

---

## 1. The mechanism in one paragraph

One function, `param_mode(node_type, key)` in `core/workflow/template_surfaces.py`, says how pflow
reads a param's text: `"template"` (default) or `"body"` (`shell.command`, `code.code` — plain
code, never a Template); a sibling predicate, `binds_as_text(node_type, key)`, says that `shell.env`
values bind as text (their leaves are never JSON-parsed). Every param walk reaches bodies through
that one decision: the surface enumeration (`iter_node_surfaces`), Pass 6 and the graph builder
iterate `template_params(node)` (params minus bodies); the runtime split, the resolver, the canvas
`is_dynamic` flag, file-reference detection, the MCP single-node env expansion and the TypeScript
mirror consult the functions directly. The shell node binds `env:` in `prep()` through one
function, `bind_env` (names checked, each value `core/templates.to_string(value)`, NUL and
unencodable text refused), so every entry path — engine, batch item, single-node probe — gets the
same binding, and a binding failure is raised before the command runs, non-retriable, where
`ignore_errors` cannot swallow it. Old-form bodies never run wrong: data-flow validation (which
also runs at compile) reads each body once — a shell body through the template parser, a code
body through Python's own parser, string literals only — and reports any `${…}` whose root is a
pflow name in the step's own scope, and any `$${`. What ran stays answerable: a failing shell step
records one display-safe copy of its bound values beside `command`, and `pflow report` reads the
body and the bound values from the trace it already has.

---

## 2. Investigation record

Verified = read at file:line or executed on `b2cd92e3` by the planner; (S) = a
`pflow-codebase-searcher` citation the planner checked the reasoning of but did not re-read.

### 2.1 Where params are read for `${…}` (the consumer list — complete as far as grep reaches)

| # | Site | Today | Node type in scope? |
|---|---|---|---|
| 1 | `core/workflow/template_surfaces.py:77-82` `iter_node_surfaces` | yields every param as a surface — feeds `data_flow.py:789`, the Issue pass (`runtime/template_validation/validator.py:624`), `operands.py:50` (Pass 5, Pass 8, unused inputs), `path_validation.py:384` | `node.get("type")` |
| 2 | `runtime/template_validation/type_validation.py:75-82` Pass 6 | own loop over `params.items()` | yes (`node_type`, :76) |
| 3 | `type_validation.py:176-299` Pass 7 `validate_shell_command_types` (+ `_build_quoted_templates` :158) | dict/list block on `command`, quote-escape tier | shell-only |
| 4 | `runtime/template_validation/validator.py:447-499` loop-carry warning (`_loop_prompt_sink_text` reads `command`/`prompt`/`system`) | warns when the carried key is not a root in that text | yes |
| 5 | `runtime/engine/template_resolution.py:89-120` `split_params` | `has_templates` → template_params | **no** — sole caller `runtime/compilation/compiler.py:331` has `node_type` (:282) |
| 6 | `template_resolution.py:267` `resolve(template, context, auto_parse=isinstance(template, (dict, list)))` | JSON-parses dict leaves — `env: {D: ${x.stdout}}` with JSON text becomes a dict (executed by the spec battery; mechanism read) | no — `TemplateConfig` has no type |
| 7 | `core/workflow/graph/build.py:586` → `_params_strings` (:852) | a DATA_FLOW edge per ref in every string leaf | `raw_node` |
| 8 | `core/workflow/graph/renderers/react_flow.py:306-311` `_param` → `_param_is_dynamic` (:473) | `is_dynamic` from refs in the value; `echo ${HOME}` → `True` (S, executed) | `node.kind` |
| 9 | `mcp_server/services/execution_service.py:731-736` `run_registry_node` | `expand_env_vars_nested` over **all** params incl. `command` (the env-var language of `mcp/auth_utils.py:14`, `raise_on_missing=True`) — a shell body `for f in *; do echo "${f}"; done` raises "missing variable" | `node_type` arg |
| 10 | `core/file_resolver.py:66-67` `is_file_reference` — called from **four** param loops: `resolve_file_references` (:143-145), `_collect_param_file_refs` (:256 → `has_file_references` → `execution/workflow_resolver.py:254-267`, `core/workflow/save_service.py:383-405`), `core/workflow/dependency_discovery.py:132-134` (→ `save_service.py:342-346`, raises `FileNotFoundError`) and its batch twin (:200-202) | `"${"` ⇒ not a path; `./scripts/$NAME.sh` ⇒ a path (executed: `discover_dependencies` raises on it) | every loop has `node`, `key` |
| 14 | `core/prompt_cache_analysis/stages/discrepancy/predict.py:362-380` `_node_templates_touch` | an ad-hoc `TEMPLATE_PATTERN` walk over every string in a node, bodies included (over-match only skips a prediction) | node |
| 11 | `web/src/graph/scan.ts:129-150` `paramTextReads` | marks producer outputs read from refs in every param | `reader.kind`, `param.name` |
| 12 | `web/src/utils/batchItems.ts:26` via `components/ReadPanel.tsx:74` | per-item substitution preview for every param of a literal-batch node | `kind` passed alongside |
| 13 | `web/src/graph/sourceDecorate.ts:32` | instant tier teals refs in **all** fence content until shiki arrives (:301); full tier teals markdown only (:320) | fence info string only |
| — | `tests/test_docs/test_guide_example_validation.py:108, 173` | the docs harness declares every bare `${name}` in a file as a workflow input — a `${HOME}` inside a shell fence would become an in-scope root | harness, not product (fixed in PC) |
| — | `web/src/utils/format.ts:9` `REF_PATTERN` chips | canvas chips only when `param.is_dynamic` (Python, #8) — fixed by #8 | — |

Automatically exempt once a body is a static param (S): `resolve_templates` and its callers
(`engine.py:1755`, `plan_node.py:144`, `batch_executor.py:219`, `execution/plan.py:1533/1706`),
`loop_control.apply_carry_overrides` (uses `dataclasses.replace`, :82 — verified), `error_context`,
trace `template_resolutions`. Not a template walk (S): Pass 9 (AST over `code`), `markdown_parser`,
`cli/commands/_probe_impl.py:111-148` (no resolution at all — bodies already pass verbatim; binding
arrives through `prep()`), `core/prompt_cache_analysis/*` (llm only), registry, save, UI server.

Node type strings: `"shell"` (derived, `nodes/shell/shell.py:334`), `"code"` (explicit `name`,
`nodes/python/python_code.py:619`); no aliases reach the IR; `node["type"]` is never rewritten by
batch/loop/nesting (S). Assumed (nothing confirms the registry's collision policy): no user node
registers as `shell`/`code`.

### 2.2 Validation layering

- `WorkflowValidator.validate` (`core/workflow/validator.py:172-278`): step 4 `validate_data_flow`
  (always; **also run by the compiler**, `runtime/compilation/compile_validation.py:130-132`,
  `check_inputs=False`), step 5 template passes (only with `extracted_params`), step 9
  `_validate_node_param_semantics` (always; per-type dispatch at :836-852 — agent, code, llm,
  workflow; lazily imports node-owned helpers, `validator.py:892/970/1016/1136`), step 10 children
  (same passes, recursively). `--validate-only`, the run, `pflow save`, MCP `workflow_validate` all
  reach the full call (S).
- Scope today (verified `data_flow.py:426-457, 784-787`): `valid_simple_refs = declared inputs |
  every batch alias in the workflow | {__index__ if any batch} | {__iteration__ if any loop}`; per
  node `node_refs = valid_simple_refs | keys of the node's own inputs:`; node ids via `nodes_by_id`.
  Carry keys must be `inputs:` keys (`data_flow.py:596-610`).
- Parser facts (S, executed): `${HOME}`, `${item}`, `${a.b}`, `${arr[0]}`, `${fetch-data.stdout}`,
  `${X-default}` (root `X-default` — `-` is an identifier char) parse as References; `${1}` is a
  Literal; `${NAME:-world}`, `${#X}`, `${X%.*}`, `${arr[@]}`, `${!X}`, `${X:0:3}`, `${X:=v}`,
  `${X/a/b}`, `${X^^}`, `${a + b}` are Issues; `$${HOME}` is Text with `Template.escaped=True`
  (no escape positions recorded).
- A param diagnostic can carry a line: `_format_location` prints `path:line` from
  `context["source_line"]` (`core/diagnostic_render.py:205-228`); the parser stores the first
  content line of a code block in `node["_source_lines"][param]` (`core/markdown_parser.py:1229-1234`).
  No param diagnostic uses it today.
- `env` is declared `dict` (`shell.py:438`); Pass 6 recurses into dict values with
  `expected_type=None` (never type-checks them); `coerce_param_for_node` leaves a dict alone; the
  IR schema does not constrain it. YAML scalars arrive typed: `PORT: 8080` → int, `FLAG: yes` →
  `True`, `X: null` → `None`, `OCT: 012` → `10` (S, executed).

### 2.3 The shell node (read directly, `nodes/shell/shell.py`)

- `prep()` (:758-847) reads `env` at :803 with no validation; `exec()` merges
  `{**os.environ, **env} if env else None` (:865). Everything `prep()` raises bypasses
  `exec_fallback` and `ignore_errors` (`core/node.py:44-46`; the Windows bash resolution relies on
  this, :291-331).
- Any exception in `exec()` → `Node._exec` (`core/node.py:95-101`, `max_retries=1`) →
  `exec_fallback` (:1072-1090) → `{exit_code: -2}` → `post()`'s `ignore_errors` branch
  (:1006-1017) returns `"default"`. Executed: `env: {N: ${count}}` → traceback + "exit code -2".
- Windows: `_prepare_windows_shell_env` (:61-70) reads the exact key `"PATH"` and prepends Git
  Bash's support paths; `MSYS_NO_PATHCONV=1` is a `setdefault`; the path-translation bridge
  (:79-97) is applied to the command string only (:169).
- Checks on the body text: `DANGEROUS_PATTERNS` (:776-780), `WARNING_PATTERNS` +
  `PFLOW_SHELL_STRICT` (:783-793), `[AUDIT]` log (:827). The docstring's "Pattern Detection"
  (:425-427) describes Pass 7, which is not in the node.
- `post()` writes `shared["command"]` (:988, undeclared in `Writes:`) "for error reporting".
- macOS probes (S, executed): `ARG_MAX` 1048576; a 900 KB value binds, 1.1 MB →
  `OSError [Errno 7] Argument list too long`; NUL → `ValueError: embedded null byte`; `my-var`,
  `1x`, `a.b` reach the child but sh cannot read them; empty name is dropped silently; `A=B` →
  `ValueError: illegal environment variable name`.

### 2.4 Display surfaces

- Failure block: `executor_service._enrich_error_from_node_output(context, node_output, category)`
  (`execution/executor_service.py:340-364`) sees **only the node's output dict** — it copies
  `command`/`exit_code`/`stdout`/`stderr` into `shell_*` context keys; `diagnostic_render.py`
  renders them twice: `_format_shell_error_lines` (:814-825, the failing step's own block) and
  `_render_shell_failure_block` (:611-623, shown when a later step references the failed one; data
  filtered by `_SHELL_DISPLAY_FIELDS`, `runtime/engine/template_errors.py:299`). JSON errors expose
  the context keys at top level (`Diagnostic.to_display_dict`); the MCP error shape reuses the same
  formatter (S).
- `pflow report`: `core/trace_report.py:1297-1348` `_format_resolutions` renders `## Command` only
  when `command` is in `template_resolutions` (:1321-1323); `## Code` reads `node_params` (:1326-1328);
  everything else lands in `## Resolved Parameters` through `redact_sensitive` (:1343). Executed on
  this commit: a step written with `env:` shows no `## Command` and `{"env": {…, "API_TOKEN": "<REDACTED>"}}`.
- Trace: `node_params` is the merged static + resolved params, raw (no redaction at write time);
  `template_resolutions` holds `{template, resolved}` per templated top-level param (S, read from a
  real trace). Nothing needs to be added.
- Redaction: `security_utils.redact_sensitive(obj)` (`core/security_utils.py:74`, since #715) —
  by key name, any depth, no truncation; used by `trace_report.py` and `ui/run_node.py`.
  `gate.masked_preview` (`core/gate.py:125-146`) is a second copy with the same semantics (left
  alone). `sanitize_parameters` truncates >100 chars to 20 — never used for bound values.
- Approval preview and UI run panel already show resolved params including nested `env` (S).

### 2.5 Baselines on `b2cd92e3` (executed by the planner — the "before" every phase diffs against)

- `inventory.py`: **428 templated bodies in 128 files.** In scope: examples 39 (20 files) + 1
  (`examples/workflow_manager_demo.py`); `workflows/` 2; guide 8 fences + 2 inline (4 files); docs 3
  (2 files); **`src/pflow/mcp_server/resources/instructions/*.md` 16 (2 files — not in the spec)**;
  Task-159 baseline workflows 6 (3 files); tests 237 dict + 34 fence + 35 inline + 18 f-string
  (≈75 files), plus ≈50 helper-argument sites the scan cannot see (§6). Templated code bodies: one
  (`tests/test_core/test_graph_build.py:1399`). Out of scope (history): other `.taskmaster/tasks/*`,
  `releases/` — 23 sites. Shapes: 190 plain, 131 dotted, 35 dotted-hyphenated, 14 index, 9 coalesce;
  104 sites have a reference inside single quotes; 9 contain `$${`; 7 are batch steps; 3 already
  have `inputs:`; none has `env:`.
- `.taskmaster/tasks/task_159/baseline/verify.sh`: **75 pass / 12 drift, 0 harness errors.**
  Drifted before this task: `02-validator-errors/03`, `02-validator-errors/05`,
  `03-analyze-cache-modes/05..09`, `04-warning-catalog/03`, `04-warning-catalog/09d`, `09e`,
  `10-live-recordings/03`, `12-real-world-lyrics-generator/04-guide-auto-detect`. Two of them
  (`02/03`, `04/03`) are the cases with a templated shell body.
- `.taskmaster/tasks/task_170/implementation/examples-baseline/capture.py --check`: 29 examples,
  **1 differing before this task** (`examples/error-handling/typo-on-failed-node.pflow.md`).
- BEFORE captures of every message: `diagnostics-checkpoint.md`.

### 2.6 Cross-task scan (`./scripts/tasks`, 2026-10-06)

- **Task 170** (done) — the substrate: one parser, `iter_template_surfaces`, invariants 1-8 of its
  task-review hold here (notably 3: `parse()` on author text only — a body is author text; 6: one
  surface list; 8: no trace field). Meta-test 2 (`tests/test_core/test_template_grammar_seam.py`)
  forbids a `${` regex outside `core/templates` — the `$${` detection below uses `str.find`, never `re`.
- **Task 116** (done) — Windows shell contract; its task-review and ADR-0013 say `MSYS_NO_PATHCONV`
  has no default, the code sets one (`shell.py:64`); code wins (S, confirmed in that task's log).
- **Task 181** (pending, builds after) — reuses `param_mode`: it adds a mode for code-bearing MCP
  params identified by tool-name suffix, which a function over `(node_type, key)` can express and a
  table cannot. `split_params` gains the node type here.
- **Task 120** (pending, builds after) — inherits the value-to-text rule (`bind_env` →
  `to_string`) and the `"text"` mode (no JSON parse of `env:` leaves); #686 is the same mechanism
  on code `inputs:` and stays Task 120's.
- **Task 182** (pending) — shell linting; the bare-variable did-you-mean is left to it (D6).
- **Task 101** (later) — unaffected.
- Collision: #503, #710, #711, #458 queue on the engine seam behind this build.

### 2.7 Spec corrections made on this branch (provenance here, current truth in the spec)

1. Consumer list gains the MCP single-node env-var expansion (§2.1 #9) and drops the claim that
   `_probe_impl.py` needs the exemption (it never resolves).
2. Stale-surface list gains the two MCP instruction resources, `docs/how-it-works/loops.mdx:47`,
   `docs/reference/nodes/code.mdx:67`, `core/workflow/CLAUDE.md:60-64`, `guide/features/batch.md:138`;
   drops `core.md:394-398` and `code.md:64` (not stale).
3. Measured size replaced by the inventory's counts.
4. `tests/test_core/test_types.py` holds no shell text; the vehicle file is
   `tests/test_runtime/test_template_validation/test_union_types.py` (and `test_types.py` there is
   retired-behaviour tests, not vehicles).
5. `trace_report.py` citation moved by #715.
Not edited (another task's spec — reported in the hand-back): `task-181.md` cites the unused-input
check at `core/workflow/validator.py:555-600`; it is `runtime/template_validation/validator.py:555-612`.

---

## 3. Decisions (all resolved; ledger rulings are not re-opened)

Governing lens, applied at each fork: *"prioritize simplicity of the FINAL code… the right solution
the top 10% of codebases similar to this one would implement… more simple code that is optimized
for AI agents to understand and add features to."* Plan-review findings folded in are marked (R).

### D1 — The classification is a function on the `${…}`-meaning axis; the text rule is a sibling predicate

```python
# core/workflow/template_surfaces.py
ParamMode = typing.Literal["template", "body"]

def param_mode(node_type: str | None, key: str) -> ParamMode:
    """How pflow reads one param's text: "template" (the default — `${…}` is a Template) or
    "body" (plain code in another language — never scanned, validated or resolved)."""

def binds_as_text(node_type: str | None, key: str) -> bool:
    """A Template param whose values bind as text: its leaves are never JSON-parsed
    (`shell.env`). The consumer-keyed half of the parse decision — Task 120 adds the
    source-keyed half beside it (#686); replace, do not grow, when it does."""

def template_params(node: dict[str, Any]) -> dict[str, Any]          # a node's params minus bodies
def code_bodies(node: dict[str, Any]) -> Iterator[tuple[str, str]]    # (param, text) per string body
def body_references(node, scope) -> list[BodyReference]               # D5's detector, reused by the unused-input pass (and by Task 181's safety net)
```

Backed by two private tables: `{("shell", "command"), ("code", "code")}` for bodies and
`{("shell", "env")}` for text binding. Part 1 ships `binds_as_text` only; Part 2 adds the rest.

- *Why a function, not a set:* Task 181 identifies params by tool-name suffix of
  `mcp-{server}-{tool}`; a function absorbs that without reshaping callers.
- *Why `"text"` is not a third mode (R, architecture-fit):* every walk except the resolver treats
  `env:` as a template; what the text rule decides is leaf parsing, a different axis. A third mode
  invites a future `mode == "template"` comparison that silently stops walking `env:` references.
  No caller compares against `"template"`; callers ask `== "body"`.
- *Why the predicate and not a declared `dict[str, str]`:* the right long-term carrier is the
  declared type (#686), but it re-plumbs the registry type path Task 120 is about to design, and
  Task 112's literal check would then reject `PORT: 8080`, which ADR-0016 accepts — the carrier
  must mean "coerced to text", not "must be str". One predicate is replaceable in one edit.
- *Where it is consulted (and only there):* `template_surfaces` itself, `split_params`, the
  resolver's `parses_leaves` (D2), `react_flow._param`, `file_resolver` (one node-aware predicate
  for all four callers — D7), the MCP single-node expansion, `prompt_cache_analysis` prediction
  walk, and the TypeScript mirror `isCodeBody`. Pass 6 and the graph builder iterate
  `template_params(node)` — two bypass walks removed rather than patched.
- *Rejected:* an AST meta-test "no walk skips the classification" — "a param walk" has no
  syntactic definition without false positives; the guard is the behavioural consumer table (PB
  test 1, per-row inputs) plus fewer walks.

### D2 — Binding lives in the shell node; the engine only stops parsing

`nodes/shell/env_binding.py` (new, node-owned; the validator and the compiler import it lazily
like the agent helpers):

```python
class EnvBindingError(NodeError):       # param="env"; retriable = False, batch_fatal = False
def env_problems(env: object) -> list[tuple[str | None, str]]   # (name-or-None, message): non-map, unreadable name, non-text key, case collision — ONE rule for the validator, the compiler and prep()
SHELL_OWNED: Mapping[str, str]          # upper-cased name -> consequence phrase (7 names) — the warning list
AMBIENT_NAMES: frozenset[str]           # SHELL_OWNED ∪ {LANG, USER, TERM, TZ, TMPDIR, SHELL, PWD, CI, DEBUG, EDITOR, DISPLAY, HOSTNAME, LOGNAME} — only for choosing a suggested name (D5)
def bind_env(env: object) -> dict[str, str]     # raises EnvBindingError; always a FRESH dict
def merge_env(inherited: Mapping[str, str], bound: Mapping[str, str], *, ignore_case: bool) -> dict[str, str]   # never mutates either input
```

- `bind_env`: `None`/`{}` → `{}`; `env_problems` non-empty → raise; each value
  `to_string(value)` (`core/templates.py:621`) — one function, idempotent on strings; a NUL in the
  text, or text the OS cannot encode (`os.fsencode` on POSIX — a lone surrogate from a truncated
  JSON escape; R, concurrency) → raise naming the variable.
- `prep()` calls `bind_env(self.params.get("env"))` and keeps the result in `prep_res` (no
  instance state; `params["env"]` is never written back — it may be the compiled config's own
  dict). `exec()` calls `merge_env(os.environ, env, ignore_case=sys.platform == "win32") if env
  else None`.
- `merge_env` with `ignore_case` (R, concurrency S3): the author's spelling wins; an inherited
  key equal ignoring case is dropped. `_prepare_windows_shell_env` then finds `PATH` and
  `MSYS_NO_PATHCONV` case-insensitively (a four-line helper) so a bound `Path` is extended, not
  duplicated. Whether Git Bash reads a mixed-case name by its authored spelling is a D8 row.
- Engine: `TemplateConfig` gains `node_type: str = ""` (the IR type string; the compiler passes
  it; 31 keyword-only test constructions keep working; a default rather than a required field
  because there is exactly one constructor and the PA mutation test guards the seam). In
  `template_resolution.py` one module-level predicate replaces the inline flag at :267:
  ```python
  def parses_leaves(template_config: TemplateConfig, key: str) -> bool:
      """Whether a dict/list param's string leaves are JSON-parsed on resolution.
      Consumer-keyed today (an `env:` value binds as text); Task 120 adds the source-keyed rule (#686) here."""
      return not binds_as_text(template_config.node_type, key)
  …
  resolution = resolve(template, context, auto_parse=isinstance(template, (dict, list)) and parses_leaves(template_config, key))
  ```
  The whole-value rule at :271-277 (`env: ${x}` holding a JSON object string → a dict of values)
  is untouched. **Known and accepted (R, validation-consistency W3):** a value routed through the
  step's `inputs:` first — and every loop Carry — is JSON-parsed at :262 (`inputs` always
  auto-parses) and re-serialized by `to_string`; that is #686, Task 120's, and it reproduces what
  the old inline form produced, so converted loops are unchanged. The guide says: bind directly
  in `env:` when the bytes matter.
- *Why node-owned stringification:* the probe path and direct node use never pass the engine;
  `prep()` is the one place every path crosses. *Cost accepted:* the trace's `node_params.env`
  holds typed values (`true`); the child receives `True`; readers that show bound values apply
  `to_string` (D11).

### D3 — Size limits: translate the OS refusal inside `exec()`, non-retriable

In `exec()`, before the generic `except Exception`: `except OSError as e` with `e.errno ==
errno.E2BIG` → raise `EnvBindingError` naming the largest of the bound values **and the command
itself** with their byte sizes and only the current platform's limit (checkpoint §4f). Being
`retriable = False, batch_fatal = False` (the `LLMOutputSchemaError` pair, `core/exceptions.py:638`)
it skips the node's own `retry:` loop and the batch's item retries, fails the item, and lets
`continue` mode continue (`batch_executor.py:388-396`, verified) (R, concurrency W1).
`exec_fallback` re-raises any `PflowError` instead of building the `-2` dict, so neither
`ignore_errors` nor `post()` sees it. Error routing is action-only (`engine.py:1533-1536`), so a
binding failure does not take an `on_error` edge — the same as every `prep()` failure today.
- Windows: the error class for an over-limit environment is **unknown** — PA's Windows test
  observes it (D8) and the branch is written from what CI shows; if Windows accepts the tested
  size no branch is added.
- *Rejected:* pre-computing from `sysconf("SC_ARG_MAX")` minus the inherited environment plus a
  Linux per-string constant — platform tables that mirror kernel behaviour and still race the real
  limit.

### D4 — Static `env:` checks: one rule, three callers

`core/workflow/validator.py` gains `shell_env_diagnostics(node_id, params) -> list[Diagnostic]`
beside `code_param_type_diagnostics` (same shape, same two consumers): the ERRORs come from
`env_problems` (D2) — unreadable name, non-text key, case collision, non-map literal — plus the
WARNINGs for a `SHELL_OWNED` name (case-insensitive) and for a literal YAML boolean value
(checkpoint §4a, §4d). Called by step 9 (`_validate_node_param_semantics`, new `shell` branch)
and by the compiler next to `_reject_non_string_code` (ERRORs only, as a `CompilationError`), so
the UI's compile-only preflight (`ui/server.py:1019, 1269`) and a dynamic child reject the
workflow at launch instead of dying invisibly later (R, validation-consistency W2). A
whole-templated `env: ${x}` is checked at `prep()` only. Paths: `nodes[id=X].params.env.<NAME>`;
`nodes[id=X].params.env` for a collision or a non-map. A literal string holding a NUL (`"a\0b"`
is valid YAML) is reported here too — the same `env_problems` call sees it.

### D5 — The leftover rule (checkpoint §1; pending ruling 1)

In `core/workflow/data_flow.py::_validate_node_params`, after the surface loop, for each
`(param, text)` of `code_bodies(node)` **that contains `${`** (R: a `${`-free script never enters
the parse cache):

1. **Scope for this step** (R: the validator's workflow-wide set is too wide — FI W1, VC W1):
   `declared_inputs | keys of the step's own inputs: | (batch alias, __index__ if node.batch) |
   (__iteration__ if node.loop)`, and a step id **only when the reference has a path**
   (`${count.stdout}` yes, a bare `${count}` never — it was never a valid reference and is
   ordinary sh). The old runtime resolved no more than this.
2. **Escape:** a `$${` not preceded by another `$` (so sh's `$$${X}` passes) → one ERROR. When
   the escaped text is itself a reference in scope, the fix is the `\$$COST` form (checkpoint §3).
   Detection by `str.find`, never a regex (grammar-seam meta-test).
3. **Shell body — pflow-shaped:** `parse(text)` (author text — invariant 3). An `Expression` any of
   whose `.references` (dependency view) has a root in scope → a leftover. An `Issue` whose
   leading name (the text after `${` and an optional `#`/`!`, up to the first non-identifier
   character — `str` methods) is in scope → a leftover too (`${limit:-10}` on an input `limit`
   was loud before and would otherwise become a silent default — R, silent-failures C1).
4. **Code body:** `ast.parse(text)`; on `SyntaxError` skip (the markdown parser already reported
   it). Walk `ast.Constant` string nodes — the literal parts of an f-string included — and apply
   step 3 to each constant's text with the node's line. `f"Total: ${total}"` is never flagged
   (its constants are `"Total: $"`), `"${name}".upper()` is (R, review-plan W4 / VC W5).
5. All leftovers of one body → **one** ERROR listing each with its line and owner and one
   paste-able fix (checkpoint §2), `context["body_references"] = [{reference, owner, line,
   binding}]`, `source_line` = the first leftover's line. Lines: `node["_source_lines"][param]` +
   newlines before the span; for a file-loaded body (`node["_source_files"]` has the param) cite
   `<script path>:<line in the script>` instead (R, FI W3). Suggested binding name: the reference
   upper-cased, non-alphanumerics → `_`, `_VALUE` appended when it hits `AMBIENT_NAMES`
   (`${path}` → `PATH_VALUE`; R, agent-ux C2); for a code body lower_snake, `_value` appended on a
   Python keyword or `result`/`next`. The fix text branches on whether the step already has
   `env:`/`inputs:` (R, C3), carries the quoting clause (braces when a name character follows;
   split single quotes — R, C1), offers the "your own shell variable" alternative only as "only if
   the command itself assigns it" (R, silent-failures W1), the embedded-language alternative for
   dotted references (R, W2), and `eval "$CMD"` when the whole body is one reference (R).
6. (ruling 2, recommended W) shell bodies only: an `Expression` that is not a leftover but holds a
   `Field` segment or a Coalesce → one WARNING per body, with `find_similar_items` did-you-mean
   against the in-scope names.
7. Everything else: nothing.

- `body_references(node, scope)` is the one detector (steps 3–4); data_flow filters by scope and
  builds the diagnostic; the unused-input pass (`runtime/template_validation/validator.py:95-114`)
  adds its roots to the "used" set — one mistake, one diagnostic. Task 181's safety-net warning
  reuses it; Task 182's line mapping reuses the line helper (R, architecture-fit S2).
- Because `validate_data_flow` also runs at compile, a dict IR that skips `WorkflowValidator`
  fails loudly; nested children are validated recursively with provenance.
- Hard cases (a)–(g): checkpoint §1 table.
- *Rejected:* `set -u` (ledger); a quote-aware scan (a shell lexer); shape-only flagging; the
  validator's permissive workflow-wide scope (flags correct sh on non-batch steps and suggests a
  fix that fails at run).

### D6 — Not built: did-you-mean for a bare `$ENDPONT` or a plain `${endpont}`

Both need to know which names the body assigns — half a shell parser; false positives on awk/jq
text. Task 182 (shellcheck) owns it; executed there-side fact for its spec: shellcheck reports
`SC2153 Possible misspelling: ENDPONT may not be assigned. Did you mean ENDPOINT?` once a preamble
assigns the bound names, so the UPPER_SNAKE convention does not block it (R, architecture-fit S3).
The braced form was loud today and becomes quiet — recorded in checkpoint hard case (c).

### D7 — Checks that lose their object

| Check | Fate |
|---|---|
| Pass 7 + `_build_quoted_templates` + `validator.py:152-153` call + their tests | **deleted** (ledger). `tests/test_runtime/test_template_extract_pattern.py:14` imports `_build_quoted_templates` at module level — its 9 Pass-7 tests go, its 11 `TEMPLATE_EXTRACT_PATTERN` tests stay |
| Loop-carry warning | generalized to **every `inputs:` key of a shell step** (R, silent-failures W2): "used" = a root of any Reference in `template_params(node)` **except `inputs`**; a carried key gets the carry wording, any other key the "not visible to the command" wording (checkpoint §5); llm keeps the carry case only. `_loop_prompt_sink_text` deleted |
| Dangerous-command block, `WARNING_PATTERNS`/`PFLOW_SHELL_STRICT`, `[AUDIT]` | unchanged code, on the body text; the loss of value-driven cases is documented in the guide and the docstring (checkpoint §9); the docstring's "Pattern Detection" paragraph is removed |
| File-reference detection | one node-aware predicate in `core/file_resolver.py` — `is_param_file_reference(node_type, key, value)`: a `"body"`-mode value containing `$` is never a file reference — used at **all four** param-loop sites: `resolve_file_references` (:143-145), `_collect_param_file_refs` (:256, behind `has_file_references` → `workflow_resolver.py:254-267`, `save_service.py:383-405`), `dependency_discovery._collect_param_deps` (:132-134) and its batch-item twin (:200-202) (R, review-plan W3 / impact W1). `is_file_reference(value)` itself is unchanged |
| MCP single-node expansion | `expand_env_vars_nested` applied per param, skipping `"body"` params |
| `core/prompt_cache_analysis/stages/discrepancy/predict.py:362-380` `_node_templates_touch` | an ad-hoc walk over every string in a node — iterate `template_params(node)` (R, impact S5) |

### D8 — Windows: what a test settles, and when

First exercised by Part 1's PR (`tests-windows`, blocking, Python 3.13, whole suite incl. e2e — S).
Tests written in PA, evidence only on their Windows leg (the POSIX leg is a regression guard —
label it so):
1. a native temp-file path bound through `env:` is readable as `cat "$FILE"` (no translation —
   values are data; the bridge stays on the body);
2. `env: {Path: X}` yields exactly one `PATH`-named variable in the child, **containing `X`**
   (a known inherited entry absent — presence, not just count; R, test-fidelity W7) and the Git
   Bash support paths still first; a mixed-case non-PATH name that collides with an inherited one
   (`Temp`) is readable by its authored spelling;
3. a value with quotes, newline, `$`, backticks, `$(…)`, a leading `-` and non-ASCII arrives
   byte-identical (`printf '%s' "$V"`);
4. size: a 200 KB value — strict per-platform expectation (darwin: binds; linux: the translated
   error, hypothesis `MAX_ARG_STRLEN` = 128 KiB; win32: **whatever CI shows**, recorded in the
   progress log and then pinned), and in every case never "exit code -2" and never swallowed by
   `ignore_errors`.
**If (1), (2) or (3) fails on Windows the phase STOPS and hands back** (a design fork — translate
values? document `cygpath`? — is the user's; checkpoint CP-2). The guide's limit numbers are
written from what CI confirmed.

### D9 — What a failing shell step records: one display-safe copy, made at the source

`post()`, on the two `return "error"` paths only, writes `shared["env"] =
displayable_env(prep_res["env"])` when non-empty — `redact_sensitive` by key name, each value
capped at 200 characters with the length suffix, newlines escaped; on the success paths it pops a
stale `env` (a graph-loop revisit that recovers must not keep visit 1's copy — R, silent-failures
S2). `_enrich_error_from_node_output` copies it to `context["shell_env"]`; `_SHELL_DISPLAY_FIELDS`
gains `"env"`; one renderer helper formats `Env:` lines for both shell blocks, adding the one-line
`<REDACTED>` explanation when something is masked. JSON gets `shell_env` — the same copy.
- *Why the copy is display-safe at the source (R, feature-interactions C1 — verified at
  `runtime/workflow_executor.py:662-672`, `execution/formatters/batch_errors.py:99-104`,
  `batch_executor.py:484-486`):* a failed child's output rides the child-failure bundle into batch
  error records, which the CLI text, `--output-format json` and MCP emit unredacted and uncapped.
  Making every consumer redact is N patches; making the one record safe is one function. Full
  values stay in the trace (`node_params.env`) for `pflow report`.
- *Why failure-path output, not a failure-record field:* enrichment sees only the node's output
  dict; carrying resolved params on the failure record is the general mechanism #698 asks for, but
  it touches every `mark_node_failed` site for one consumer today — a hypothetical seam. If #698
  builds it, shell moves over and this write is deleted; `env` stays out of the `Writes:` line,
  which is what keeps that reversible.
- Residual, accepted: an on-error fallback step can read `${failed.env}` (the safe copy).

### D10 — `pflow report`

`_format_resolutions` takes the parent event for batch items: for a shell event or a batch item
of a shell step (`_build_batch_item_file`, `core/trace_report.py:1523-1550` — item events carry
no `node_params`; R, FI W2 / impact W2), `## Command` from the host's `node_params["command"]`
(always, not only when templated) and `## Env` — `redact_sensitive({name: to_string(value)})`
from `node_params["env"]` or, for an item, from `item["template_resolutions"]["env"]["resolved"]`
— JSON block, full length; `env` joins `shown`; `"env"` joins the output section's `shown_keys`.
Code steps unchanged. The node-type field is the one the report already prints as `Type:
ShellNode` — read its name in `_build_node_file`, do not guess.

### D11 — One text for a bound value on every reader

`to_string` is called in exactly two places: `bind_env` (what the child receives) and the report's
`## Env` (re-derived from typed trace values). The failure block shows `prep_res["env"]`'s
display-safe copy, already text. The approval preview and the UI run panel keep showing the typed
resolved params (unchanged, out of scope).

### D12 — No trace-format change

`node_params` and `template_resolutions` already carry the body and the resolved `env:`; D9's
write is node output, which the trace already records. No version bump. The Task-159 baseline is
used as a corpus regression net (§2.5), compared actual-against-actual (PC gate).

### D13 — Conversion order: corpus first, flip second — braces never, in PC

The corpus converts to `env:` form **while the old semantics still accept both forms** (`env:`
works for strings today and for everything after Part 1), with outputs diffed against the
baseline; then the flip lands on an already-clean corpus. Every commit stays green only if (R,
review-plan W1/W2, VC W4): (a) PC never writes a braced `${NAME}` in a body — under the old
semantics that is still a Template; delimit with `"$NAME"suffix` and let PF teach braces; (b) the
guide/docs/MCP-resource **fenced examples** convert in PC too (`test_guide_example_validation.py`
validates every fence with `## Steps`), with the two edits to that test's harness; PF rewrites the
prose.

### D14 — Memo-cache keys and the golden hashes

A formerly templated body moves from `config["template_params"]` to `config["params"]`
(`runtime/engine/instrumentation.py:165-170`): one cache miss per such step, once.
`tests/test_runtime/test_prompt_cache_hash.py::test_golden_baseline_hashes_match`
(`tests/test_runtime/fixtures/golden_config_hashes.json`, generator
`scripts/generate_config_hash_baseline.py`) drifts in **PC only**, and only at the node ids the PC
log lists as converted — bound the diff to those before regenerating. At PB the expected drift is
**zero** (no baseline workflow holds a templated body after PC); a PB drift is a finding, never a
regeneration (R, test-fidelity W5). Batch memo (#675) is untouched.

---

## 4. Phases

### 4.0 PR shape — RULED 2026-10-06: two PRs

**Ruling (main orchestrator, under the user's end-to-end grant):** two PRs as proposed. **Part 1**
(P0 + PA + the two tooling workflows in a form that runs identically on today's code) is
non-breaking and may merge as soon as it is green. **Part 2** (the breaking part) goes PR-ready and
is **NOT merged until the user rules on a release first** — the task orchestrator hands back at
`create-pr` and stops. Phase E on Opus, not design-bearing: ruled. CP-1's nine rulings: all as
recommended; the checkpoint file is the ruled text.

**Two PRs.** Part 1 (P0 + PA) is small, stands alone, fixes a live validate-passes/run-crashes bug
that a second lane hit independently this week, unblocks Task 120, and is the only way to get a
`tests-windows` run on the three unverified Windows questions *before* 400 sites are moved onto the
channel. It also carries the two tooling workflows: their converted form runs identically on
today's code, so merging it early means the breaking PR changes no shared tooling at all.
Part 2 is the breaking change, landed on a corpus that is already converted.

Consequence: Part 1's branch is squash-merged and its worktree torn down; Part 2 runs in a new
worktree from the then-current `main`, from this plan + the progress log. `task-review.md` is
written once, at the end of Part 2; Part 1's PR body is its record and the spec's `## Status`
becomes `in progress`, not `done`.

*If the ruling is one PR:* run P0, PA, PD, PC, PB, PE, PF, PZ in one branch, skip Part 1's
close-out, and treat D8's Windows tests as unconfirmed until the final CI run — a failure there
then lands after the corpus has moved.

### Agent assignment (phases ≠ agents)

| Launch | Phases | Tier · effort | Why this boundary |
|---|---|---|---|
| I1 | P0 + PA | Opus · **high** | engine contact, Windows unknowns to design tests for |
| — | Part 1 close-out | task orchestrator | gate, PR |
| I2 | PD → PC1 | Opus · medium | fully specified; PD first so PC's display assertions are written once |
| I3 | PC2 | Opus · medium, **fresh** | volume (≈370 test sites): a degrading window is the stated reason. May be split into two parallel launches on disjoint directories (`tests/test_runtime` + `tests/test_core` / everything else), each running only its own directories; the orchestrator runs the full gate after |
| I4 | PB | Opus · **high**, fresh | the seam logic (engine split, validator rule); needs a clean window |
| I5 | PE | Opus · medium, fresh — the specialist `task-phase-implementer` hand-off for `web/` | not design-bearing (no look/feel judgment: refs stop being decorated where they are no longer refs) |
| I4 resumed, else fresh Opus · medium | PF | — | the docs belong to whoever holds the rule; rotate if I4's window is past ~350k |
| — | PZ | task orchestrator commissions | completion gate |

Per-phase gate: `make check` + `make test` (PE adds `npm run typecheck` + `npm test` in `web/`),
then the "FULLY happy?" resume. Completion adds `make test-all-local`.

---

### P0 — Baseline (inside I1's first step)

- Run and record in the progress log, **by name**: `make test` pass/fail set; `inventory.py`
  totals; `verify.sh` drift set; `capture.py --check` result. Expected values: §2.5 — a difference
  from §2.5 is a finding (main moved), logged before any edit.
- The named runnable set for "same results": the six templated-shell examples already in
  `capture.py` (`bundling/sub-echo`, `core/stdin-echo`, `core/stdout-result`,
  `core/stateful-loop-tournament`, `nested/to-uppercase`, `test-nested-index`) plus one captured by
  hand — `examples/nested/document-processor.pflow.md` (`--output-format json`, fresh `HOME`, fixed
  inputs; store the command line and the output under `implementation/baseline/`).
- **Handoff:** the four baselines are in the log.

### PA — `env:` is a working channel  ·  ENGINE CONTACT  ·  first Windows exercise

**Goal:** any value bound in `env:` reaches the command as the decided text; a string arrives
byte-for-byte; names and unbindable values fail before spawn; validate-only and the run agree.

**Files:** `core/workflow/template_surfaces.py` (`ParamMode`, `param_mode`, the `text` entry),
`runtime/engine/types.py` (`TemplateConfig.node_type`), `runtime/compilation/compiler.py:367`
(pass it), `runtime/engine/template_resolution.py:267`, `nodes/shell/env_binding.py` (new),
`nodes/shell/shell.py` (`prep`, `exec`, `exec_fallback`, the `env` Interface line),
`core/workflow/validator.py` (step 9 shell branch), `workflows/search/run-searcher.pflow.md`,
`workflows/review/run-review-lenses.pflow.md`, `src/pflow/guide/nodes/shell.md` (one new section,
"Environment variables (`env:`)": the pattern, names, the text rule incl. literal YAML values,
size → `stdin:`, the name-masking rule — nothing about bodies yet),
`runtime/engine/CLAUDE.md` + `core/workflow/CLAUDE.md` + `nodes/CLAUDE.md` (one line each: the
`text` mode; where binding lives), tests.

**Decisions:** D1 (`binds_as_text` only), D2, D3, D4, D8. Messages: checkpoint §4 **as ruled**.
Also in PA: `architecture/core-concepts/data-type-coercion.md:88-100, 216` — one sentence that an
`env:` value is the first leaf the inline-object JSON parse does not apply to (R, impact S1).
- Interface line: `- Params: env: dict  # Environment variables for the command (each value binds as text; optional)` —
  **no comma-separated `NAME: value` in the comment**: the metadata extractor splits on `, ` and
  would register a fake param (R, impact C1 — executed). PA asserts the shell param list is exactly
  `stdin, command, cwd, env, timeout, ignore_errors, strip_newline`.
- Tooling workflows — in both files replace
  ```
  - inputs:
      cwd_override: ${cwd}
  ```
  with
  ```
  - env:
      CWD_OVERRIDE: ${cwd}
  ```
  and the body's `"${cwd_override}"` (twice) with `"$CWD_OVERRIDE"`. Nothing else in either file
  changes (verified: one templated body each).

**Tests — the failure scenarios they must catch** (a row that also passes on today's code is a
regression guard and is labelled so in its docstring):
1. *Validation passes, run crashes.* One table over `(value, text)`: `3`→`3`, `3.0`→`3.0`,
   `True`→`True`, `None`→``, `{"a": 1, "b": [1, 2]}`→`{"a": 1, "b": [1, 2]}`, `[]`→`[]`,
   `"x"`→`x`, as a literal and as a Reference (workflow input, upstream output, `${__index__}` in
   a batch — sequential **and parallel**, an unset optional input): `--validate-only` valid
   **and** the run prints the text. After the parallel run `os.environ` and the compiled
   `params["env"]` are unchanged (R, concurrency S1).
2. *A JSON-looking string is re-serialized.* Upstream prints compact `{"a":1}`;
   `env: {DATA: ${up.stdout}}`; `printf '%s' "$DATA"` is `{"a":1}` byte-for-byte — in a plain
   step and as a batch item value. Mutation to record: restore the inline flag at `:267` → this
   test must go red (it is the only thing the engine edit does). A sibling row pins the accepted
   limit: the same value routed through `inputs:` (and a carried loop round) arrives as
   `{"a": 1}` — unchanged from today, #686's.
3. *Injection (#59) — regression guard.* The D8-3 value arrives intact; `$(touch <marker>)`
   creates no file.
4. *A binding failure looks like a command failure.* The failing name, NUL and lone surrogate
   must arrive **dynamically** (`env: ${whole}` or a Reference — a literal is already rejected at
   validation, so the run never starts; R, test-fidelity W8): the step fails with
   `EnvBindingError` naming the variable, **also under `ignore_errors: true`** (the workflow is
   not successful, no exit code is recorded, no `-2`), the node's own `retry: {max: 3}` does not
   re-run it (assert one attempt), and a batch under `continue` records the item as failed once
   and finishes. (darwin) a 1.1 MB value → the E2BIG translation names it with its size.
5. *Validate-only and run disagree on names.* `my-var`, `1x`, `a.b`, empty, a non-text YAML key
   (`1:`, `true:`): ERROR at validation with the `params.env.<name>` path; the same IR through
   `compile_workflow` directly raises `CompilationError` with the same text; the same name
   arriving through `env: ${whole}` fails in `prep()` with the same sentence.
6. *Case.* `{Path: …, PATH: …}` is an ERROR; `{path: …}` warns (shell-owned, case-insensitive) and
   still runs; with `sys.platform` patched to `win32`, `merge_env` keeps the authored key and drops
   the inherited case-variant, and `_prepare_windows_shell_env` extends it rather than adding a
   second `PATH`.
7. *The clobber warning refuses.* `env: {PATH: …}` validates (warning only) and the existing
   PATH-override tests (`tests/test_nodes/test_shell/test_shell.py:322-357`) still pass; a literal
   `DEBUG: true` warns and binds `True`.
8. *Regression guards (true before):* a changed `env:` value changes the memo key; the gate
   preview still masks a secret-named `env` key (`tests/test_cli/test_paused_cli.py:~120`); a
   step without `env:` passes `env=None` to the spawn (inherits); `bind_env` returns a fresh dict
   even for an all-string input.
9. *The probe path.* A bare `ShellNode` with `params={"env": {"N": 3}, …}` (no engine) runs.
10. Windows tests D8-1..4 (run on every platform; the POSIX legs are regression guards).
11. Parity corpus (`tests/test_integration/test_template_parity.py`): a `shell_env` surface entry
    (§6.2) with rows for a non-string, a **compact** JSON string (`DEFAULT_PAYLOAD["json_str"]`
    already carries a space — override the row's payload; R, test-fidelity W9), and an unresolved
    Reference (validator ERROR and runtime strict failure both still fire inside `env:` —
    presence check that the text rule exempted nothing).

**Real-surface exercise before the PR (not tests):** the six rows of checkpoint §4 run through
`uv run pflow`; one real `run-searcher` run without `cwd` and one with `cwd=<another checkout>`
(assert the reported root); the review fan-out is exercised by Part 1's own completion gate, once
with a `cwd` override.

**Handoff:** `env:` binds every type on macOS/Linux; CI on the PR answers D8 for Windows; both
tooling workflows run converted; nothing about bodies has changed.

**Mid-task review:** none separate — Part 1's completion gate follows immediately.
**Hand-back note for Part 1 (R, architecture-fit W1):** converting the two tooling workflows
changes their content hash — a paused or failed run of either, started before the merge, resumes
only with `pflow resume --force`.

### Part 1 close-out (task orchestrator)

`make check`, `make test-all-local`; code-mode `deep-review` on the branch diff — sensitive paths
(engine, `nodes/shell/`) ⇒ the full floor: `review-silent-failures`, `review-impact-completeness`,
`review-feature-interactions`, `review-test-fidelity`, plus `review-validation-consistency`
(validator + runtime twin), `review-agent-ux` (new messages), `review-concurrency-safety`
(subprocess env), and `review-falsifier` last, by direct launch. Completion-gate-only lenses
(`review-simplicity`, `review-spec-conformance`) wait for Part 2. `create-pr`; hand back with the
head SHA, the `gh pr checks` snapshot **naming `tests-windows` and its D8 outcomes**, and a request
to merge in a quiet moment (the PR changes `workflows/`). **Checkpoint CP-2 fires here if D8-1..3
failed on Windows.**

---

### PD — What ran stays answerable

**Goal:** the failure block, the JSON error and `pflow report` show the body and the bound values.

**Files:** `nodes/shell/shell.py` (`post`), `execution/executor_service.py:359-364`,
`runtime/engine/template_errors.py:299` (+ the redaction where the block's data is built),
`core/diagnostic_render.py:611-623, 814-825` (one shared `Env:` formatter), `core/trace_report.py`
(`_format_resolutions`, the output `shown_keys`), tests.

**Decisions:** D9 (the display-safe copy), D10 (batch item pages included), D11; text per
checkpoint §6/§7 **as ruled**. **Mid-task review:** no — PD's own tests plus the completion gate.

**Tests must catch:**
1. *The values are missing.* A failing step with `env: {ENDPOINT: ${endpoint}, API_TOKEN: ${t}}`:
   the text block has `ENDPOINT=users` **and** `API_TOKEN=<REDACTED>` (presence), and the secret
   value is absent from stdout+stderr+JSON (absence paired with the presence in the same output).
2. *The sanitizer's truncation.* A 150-char value appears whole in the text block and in JSON
   `shell_env`; a 5,000-char value is cut at 200 with the suffix naming its length in both; the
   report holds all 5,000; an empty secret-named value shows as `API_TOKEN=<REDACTED>` (the shared
   function's behaviour — a follow-up, §10).
3. *The shown text is not what ran.* `env: {FLAG: ${b}}` with a boolean shows `FLAG=True` in the
   block and `"FLAG": "True"` in the report (not `true`).
4. *`## Command` disappears.* A shell step with a static command and no `env:` has `## Command`;
   one with `env:` has `## Command` and `## Env` and no `env` under `## Resolved Parameters`; **a
   batch item's page** has both, its `## Env` from the item's own resolved values (update
   `tests/test_core/test_trace_report.py:899, 1571, 2457`).
5. *Outputs grew.* A successful shell step's namespace and a successful batch item's result have
   no `env` key (regression guard); a failed step's has it.
6. *The second block.* A later step referencing the failed step renders the same `Env:` lines.
7. *A code step's report page is unchanged* (regression guard).
8. *A batch item's payload or a secret leaks.* (a) A failing top-level batch shell step with
   `env: {ITEM: ${item}}` (a large item): the item's summary is present, a marker from the
   payload's tail is absent (batch error records carry no node output — `batch_executor.py:40-69`).
   (b) **A batch of sub-workflows** whose child shell step fails with `env: {API_TOKEN: …, ITEM:
   ${item}}`: in text stdout, in `--output-format json` (`execution.steps[].batch_error_details[]
   .child_failure`) and in the MCP `workflow_execute` response, the secret value is absent,
   `<REDACTED>` is present, and no more than 200 characters of the item appear — the child-failure
   bundle carries D9's safe copy, verified at `workflow_executor.py:662-672` (R, FI C1).
9. *A stale copy survives recovery.* A step that fails on graph-loop visit 1 and succeeds on
   visit 2 has no `env` in its namespace afterwards.

**Handoff:** checkpoint §6/§7 reproduce through `uv run pflow` + `pflow report`.

### PC — The corpus converts (old semantics still in force)

**Goal:** no in-scope body holds a pflow Reference; results unchanged.

**PC1 (I2) — files:** the 20 example files + `examples/workflow_manager_demo.py`; the three
Task-159 baseline workflows; **the fenced examples** in `src/pflow/guide/**`, `docs/**` and
`src/pflow/mcp_server/resources/instructions/*.md` (inventory-listed; prose untouched — PF) and
the two harness edits to `tests/test_docs/test_guide_example_validation.py` named under PF (D13);
`tests/test_runtime/test_worktree_creator_workflow.py:57`; `tests/test_core/test_graph_build.py:1372-1378`
(asserts an edge ending in `"command"` parsed from `examples/test-nested-index.pflow.md` — the
converted edge ends in the env **key**, e.g. `"PREV"`, not `"env"`: an env leaf's edge is labelled
with its dict key, `build.py:872-880`; R, impact W3); react-flow contract fixtures
(`uv run python -m tests.fixtures.react_flow_contracts._generate` — `prompt-caching-multi-chunk.json`
changes its edge `input_name` to the env key); `tests/test_runtime/fixtures/golden_config_hashes.json`
(D14 — diff bounded to the converted node ids). Hand case: `git-worktree-task-creator`'s
`parse-result` pre-escapes `safe_description` for the heredoc **pasting** layer ("Layer 0",
`workflow.pflow.md:308-309`) — delete that layer with the conversion, and exercise `launch-cli`
with `osascript` stubbed on `PATH` (R, silent-failures C2).
**PC2 (I3) — files:** the test tables in §6.

**Tools (kept in `implementation/`, written in P0/PC1):**
- `baseline/node_outputs.py` — runs a workflow (fresh `HOME`, fixed params) and dumps every
  node's `stdout`/`stderr`/`exit_code` (and batch items') from the trace, `command` excluded. The
  workflow result alone does not see converted steps (`document-processor`'s `combine` never
  reaches the output — R, test-fidelity C1).
- `equivalence.py` — for every shell node whose body changed between the merge base and the
  worktree: resolve the OLD body with pflow's `resolve()` over a sample context, bind the NEW
  `env:` over the same context with `to_string`, run both under `sh` with a stub `PATH` whose every
  external command prints its argv and stdin; transcripts must be identical, twice — once with
  benign values containing spaces, once with hostile values (`it's "q" $5 \ back`) where the NEW
  transcript must carry the value intact. Every difference is explained in the log (an old form
  that relied on word splitting, or that was injectable) (R, test-fidelity W6).

**Rules (every decision):** §5 — and in PC **never a braced `${NAME}` in a body** (D13).

**Gate (this is the phase's test):**
- `inventory.py`: zero sites in `examples/`, `workflows/`, `.taskmaster/tasks/task_159/`,
  `src/pflow/guide`, `docs`, `src/pflow/mcp_server/resources`; in `tests/` only the T3 files listed
  in §6 (deleted in PB) — list them in the log. Plus a grep gate for JSON-IR snippets in
  `architecture/` (the inventory cannot see `"command": "…${…}"` inside prose — R).
- **Instrumented suite run (R, test-fidelity W3 / silent-failures W4):** with a temporary,
  uncommitted hook in `split_params` and `iter_node_surfaces` that appends `(PYTEST_CURRENT_TEST,
  node id, param)` to a file whenever a `shell.command`/`code.code` value holds an Expression or
  an escape, run `make test` once. Every hit outside the §6 T3 list is an unconverted site —
  helper-argument, f-string or inline — convert it by the same rules. Remove the hook. This is the
  net for the sites the inventory cannot see.
- `node_outputs.py` for the runnable set: identical to P0's dump.
- `capture.py --check`: clean, or every hunk explained; then re-capture.
- `verify.sh`: compare each case's **actual** output against P0's saved actual output (not the
  expected files — 12 cases already drift and `regenerate.sh` would launder it; R, test-fidelity
  W4): identical except where the converted workflow's own text or source lines appear, each
  explained; regenerate expected files only for cases that passed at P0 and now show an explained
  drift.
- `equivalence.py` clean for every non-runnable real workflow and example.
- `make test` green.
- The five non-runnable real workflows, `plan-to-code/execute-plan`, the three agent examples,
  `batch-test*`, `template-variables`, `prompt-caching-multi-chunk`: `--validate-only` valid.

**Tests must catch:** a conversion that changes what the command receives — the node-output
dump, the equivalence harness and the instrumented run above are the tests; the phase has no
other.

**Mid-task review:** no — the gates above are the review.

**Handoff:** corpus is in `env:` form and green under the old engine semantics.

### PB — The flip  ·  ENGINE CONTACT  ·  **triggers a mid-task review**

**Goal:** bodies are never scanned, validated or resolved; old-form bodies fail loudly at
validation and at compile; re-homed checks done.

**Files:** `core/workflow/template_surfaces.py` (`"body"`, two entries, `template_params`,
`code_bodies`, `body_references`; `iter_node_surfaces` iterates `template_params`),
`runtime/engine/template_resolution.py` (`split_params(params, expected_types, node_type: str |
None = None)` — a `"body"` param is static whatever it contains; 36 two-arg test calls keep
working), `runtime/compilation/compiler.py:331` (pass `node_type`),
`runtime/template_validation/type_validation.py` (Pass 6 iterates `template_params(node)`; Pass 7
and `_build_quoted_templates` deleted), `runtime/template_validation/validator.py` (Pass 7 call
removed; loop-carry warning per D7; unused-input accounting per D5),
`core/workflow/graph/build.py:586` (`_params_strings(template_params(raw_node))` — and every other
`_params_strings(` caller the grep shows), `core/workflow/graph/renderers/react_flow.py:306-311`
(`is_dynamic` is `False` for a body), `core/workflow/data_flow.py` (D5),
`core/file_resolver.py` (D7), `mcp_server/services/execution_service.py:731-736` (D7),
`tests/test_runtime/test_template_extract_pattern.py` (D7), `tests/fixtures/golden_config_hashes.json`
(D14), `inventory.py` (an `ALLOWED_FILES` tuple naming the new negative-fixture tests), the T3
tests of §6, new tests.

**Decisions:** D1, D5, D7, D14; messages per checkpoint §1-§3, §5 **as ruled**.
Also: `runtime/engine/engine.py:138-142` docstring cites a code body's `${tick.result.next}` —
rewrite (R, impact S4).

**Tests must catch:**
1. *A consumer still reads the body.* One parametrized table, a row per consumer of §2.1, each
   calling **that consumer's own entry point** with a body chosen so that the consumer WOULD
   report it if it still read bodies, and the same text in `env:` as the presence half (R,
   test-fidelity W1 — one fixture cannot serve every row):
   data-flow: `${ghost.x}` (today "non-existent node"; after: only the ruling-2 warning) —
   Pass 5: `${up.nope}` — Pass 8: `${item.nope}` on a batch step — the Issue pass: `${1:-x}` —
   unused-input: an input used only in a body → "never used" fires, paired with the leftover
   case where it must not — the source-file hint: a `${x}` from a file-loaded body —
   Pass 6: a mock registry declaring `command: int` fed a `str` output (no real output type
   trips a `str` param; R, W2) — `split_params`: `${up.stdout}` stays static — graph build:
   `${up.stdout}` draws no edge, the env leaf draws one labelled by its **key** —
   `_param_is_dynamic`: `False` for the body, `True` for `env` — file references:
   `./scripts/$NAME.sh` is a command through all four callers (`resolve_file_references`,
   `has_file_references`, `discover_dependencies`, and `pflow workflow save`) while
   `./prompts/${var}.md` on `prompt` is still not a path — MCP expansion: `${PFLOW_TEST_X}` set in
   `os.environ` is expanded in `env` and left alone in `command` — prediction walk:
   `_node_templates_touch` ignores a body.
   Mutation ledger: remove the body rule at each site in turn → that row goes red; record it.
2. *The escape is collapsed.* `$$` and `$${X}` in a body reach `split_params`' static side
   unchanged (the exemption keys on the param before `has_templates`).
3. *An old-form workflow runs wrong.* Each shape — `${item}` (batch step), `${fetch-data.stdout}`,
   `${a.b}`, `'${overwrite}'` in single quotes, `${__index__}` (batch step), `${__iteration__}`
   (loop step), an `inputs:` key, a carry key, a forward reference, **`${limit:-10}` and `${#item}`
   on an in-scope name**, a whole-body `${producer.stdout}` — is the ERROR at `--validate-only`,
   at the run, **and** through `compile_workflow` on a dict IR that declares its inputs (no
   `WorkflowValidator`); the message names the fix (assert the suggested `env:` line, the quoting
   clause and, for the whole-body case, `eval "$CMD"`). In a child workflow the error carries the
   parent provenance. A file-loaded body's leftover cites the script path and its own line.
4. *False positives.* `$HOME`, `${HOME}`, `${CI}`, `${X:-y}`, `${#X}`, `${arr[@]}`, `${1}`,
   `$$${X}`, an unbraced `$item` on a batch step, `for item in …; do echo "${item}"` on a
   **non-batch** step beside a batch step, a bare `${count}` where `count` is a step id,
   `${arr[0]}` with no `arr` in scope: valid, and the body runs unescaped printing what sh prints.
5. *Hard cases a, b, d, e, f, g* of checkpoint §1, one test each, asserting the exact verdict.
6. *`$${`* in a shell body and in a code body: ERROR with the checkpoint's fix; `$${x.cost}` with
   `x` in scope gets the `\$$COST` fix.
7. *Code.* `"${name}".upper()` → ERROR naming `inputs:`; `f"Total: ${total}"` with `total` bound
   → valid and prints `$42`; a body without `${` runs unchanged; a code body with a syntax error
   gets the parser's error and no leftover error.
8. *Two diagnostics for one mistake.* A workflow input referenced only through a leftover yields
   the leftover ERROR and **no** "never used" error; removing the leftover brings "never used" back.
9. *`inputs:` on a shell step.* A looped shell step with `inputs: {state: …}`, `carry: {state: …}`,
   `env: {STATE: ${state}}` reads round N-1's value in round N; the carry warning fires when no
   param but `inputs:` references the key and is silent when `env:` or `stdin` does (nested path
   and coalesce forms too — `tests/test_core/test_loop_validation.py:393, 460`); a non-carried
   `inputs: {url: …}` that nothing reads warns with the "not visible to the command" text; an llm
   step's carry warning is unchanged in meaning.
10. *File references.* A file-loaded `./cmd.sh` containing `${HOME}` and `${NAME:-x}` runs; see
    row 1 for the four callers.
11. *MCP single-node run.* `registry_run shell command='for f in a b; do echo "${f}"; done'`
    returns `a`/`b` (today: a missing-variable error); `env` params are still expanded.
12. *Pass 6 still works* — see row 1.
13. *Parity corpus:* `shell_body` and `code_body` surface entries (§6.2) — `${HOME}`: validator
    `Ok()`, runtime `StaticLiteral()` with the body echoing the template verbatim
    (`printf '%s' '…'`), end-to-end the text; `${p.out_str}` (an in-scope root): validator
    `Error(...)`, runtime `Raises(CompilationError, <leftover text>)` (R, W9).
14. The checkpoint §8 probe (`${NAME:-world} ${#X} ${HOME}`) through the real CLI.
15. *Golden hashes unchanged at the flip* (D14) — a drift is a finding.

**After the flip, the suite is the oracle — in one direction only.** A site the inventory could
not see whose root is in scope fails loudly (a leftover error) — fix it by the §5 rules. A site
whose root is **out of scope** (`${missing}`, an undefined node) does the opposite: the body now
passes validation and a test expecting an error either fails or, worse, keeps passing because some
other error still fires. So the phase closes only when every T2 row of §6 is checked off **by
name** in the log, each failure-expecting T2 test is confirmed to fail for the reason its name
states (read the asserted message, not just the status), and the permissive assertions the
test-fidelity lens named are tightened to the original error class
(`tests/test_cli/test_validate_only.py:841`, `tests/test_integration/test_template_resolution_hardening.py:89, 163, 471`,
`tests/test_core/test_workflow_data_flow.py:838-844`, `tests/test_execution/test_runner.py:831`,
`tests/test_cli/test_validate_only.py:783`). PC's instrumented run is what makes the list complete.

**Mid-task review (yes — engine contact, a validator/runtime contract changes here):**
`review-validation-consistency` (data-flow rule ↔ `split_params`, both sides),
`review-impact-completeness` (the consumer list), `review-silent-failures` (old-form bodies; the
unused-input coupling), `review-feature-interactions` (batch, loop carry, nested, cache keys) — on
PB's diff. Fixes fold in before PE.

**Handoff:** `make test` green; checkpoint §2/§3/§5/§8 reproduce through the CLI; the two tooling
workflows validate under the new rule.

### PE — Web (specialist hand-off; not design-bearing)

**Use case:** an author reading a shell step on the canvas, in the read panel and in the source
pane sees `${HOME}` in a command as plain shell text — no chip, no edge, no teal, no per-item
substitution — and still sees the `env:` References as References.

**Files:** `web/src/utils/format.ts` (`isCodeBody(kind, name)` beside `paramLanguage` — the mirror
of Python's `param_mode(...) == "body"`, with a comment naming the Python source of truth),
`web/src/graph/scan.ts:129-150` (skip a body param), `web/src/graph/scan.test.ts:194-229` (parity
rows: a shell `command` and a code `code` holding `${a.out}` read nothing; the same Reference in
`env` reads `a.out` — its edge/row is labelled by the env **key**; the fixture's `node()` needs a
`kind` override),
`web/src/components/ReadPanel.tsx:74` (no batch-item expansion for a body param),
`web/src/graph/sourceDecorate.ts:301` (the instant tier teals only where the full tier would — not
inside a fence whose grammar is not markdown; inline `- command:` key lines are left as they are:
the decorator has no node type there, and the form is rare), the web tests that use a shell
`command` as the ref-bearing param (`SourcePane.test.tsx:127`, `useWorkflowGraph.test.tsx:106, 397`,
`GraphView.test.tsx:115` — move the ref to `stdin`/`env`), `web/src/graph/CLAUDE.md`.

**Acceptance (driven with the `screenshot-pflow-web-ui` skill — every item screenshotted):** one
workflow with `up` → a shell step whose body holds `${HOME}` and `"$DATA"` and whose
`env: {DATA: ${up.stdout}}`: (1) the command row shows no chip and is not marked dynamic; (2) the
edge from `up` lands on the `env` row; (3) the read panel shows the command as bash, no teal;
(4) the source pane's shell fence shows no teal `${HOME}` in either tier; (5) a batch step's read
panel offers item expansion for `env` and not for `command`.
**The `pflow ui` server slot is shared** (ORCHESTRATION → Worktree & git flow, step 7): ask the
main orchestrator for it before starting; use a free port; stop it by PID; declare
`dev servers: none` at hand-back.

**Handoff:** `npm run typecheck`, `npm test`, `make test` green; screenshots in the log.
**Mid-task review:** no.

### PF — Guide, docs, instruction files

**Goal:** no shipped text teaches the old form. Inventory: §7. **Decisions:**
- `pflow guide` `nodes/shell.md` is rewritten around one pattern: bind in `env:`, read `"$NAME"`
  (always double-quoted), UPPER_SNAKE names chosen for the content. It states: the text rule (with
  the literal-YAML note), names, limits as CI confirmed them (D8), `stdin:` for large or
  structured data, the masking rule ("a name containing `token`, `secret`, `password`, `auth`,
  `credential`, or `…_key` is masked in approval previews, the web UI, error blocks and reports —
  name secrets that way; an ordinary value named `TOKEN_LIMIT` is hidden from the person
  approving the step"), `inputs:` on a shell step (the namespace for `env:`/`stdin`/`cwd`; where
  loop Carry lands), the dangerous-command sentence (checkpoint §9). The `$VAR`-not-`${VAR}` rule
  and the `$${` paragraph are deleted.
- `nodes/code.md:18, 61`: "the code block is plain Python; values come from `inputs:`" — stated as
  the mechanism.
- The two MCP instruction resources are hand-maintained copies of guide content: apply the same
  edits at the lines in §7 (16 fences + 5 rule lines each).
- `docs/how-it-works/template-variables.mdx`: the escape section keeps `$${` with a non-shell
  example (a `write-file` `content`), and says it is an error in a command or code block.
- CLAUDE.md files state the constraint, never the incident; grep each new sentence's distinctive
  phrase across `src/pflow/` and the CLAUDE.mds before committing it (one home per invariant —
  `param_mode`'s docstring owns the mode definitions).
- `.claude/agents/pflow-codebase-searcher.md`: add `mcp_server/resources/instructions/*.md` (a
  second, hand-maintained copy of guide content) and `nodes/shell/env_binding.py` to its location
  map; then `make sync-claude-assets`.
- `context/CONTEXT.md` is **not edited here** — proposals in §11 go up; the main orchestrator
  writes it.
- Guide claims about bytes: a value bound directly in `env:` arrives byte-for-byte; a value that
  passed through `inputs:` (or a loop Carry) is JSON-parsed there and re-serialized (D2).
- **Mid-task review:** no — docs-only; `make check` and the docs tests are the gate.
- Task-159 baseline case `12-…/04-guide-auto-detect` snapshots guide text (already drifted):
  regenerate that case after the guide lands and say so.

**Tests must catch:** `tests/test_docs/test_guide_example_validation.py` validates every guide/docs
block containing `## Steps`. Two edits keep it honest: (1) its negative case `drifted_node_ref`
(`:294-298`) proves a drifted ref is caught using `echo "${ghost-node.result}"` in a shell body;
under the new rule that text is no longer a reference — move it to
`- env:` / `V: ${ghost-node.result}` (body `echo "$V"`) so the case keeps failing for the reason it
names; (2) `_BARE_VAR_RE` (`:108`, applied to the whole file text at `:173`) declares every bare
`${name}` it finds as a workflow input — including one inside a shell fence, which would turn a
legitimate `${HOME}` in a guide example into an in-scope root and a false leftover error: collect
names from the parsed IR's `template_params` instead of the raw text. **Both edits land in PC
(D13), not here.** `tests/test_cli/test_guide.py` and
`tests/test_mcp_server/test_instruction_resources.py` pass. `inventory.py`: zero in
`src/pflow/guide`, `docs`, `src/pflow/mcp_server/resources`.

### PZ — Completion (task orchestrator)

1. Merge `origin/main`; `make check`; `make test-all-local`; `verify.sh` (drift set = P0's, plus
   the explained cases); `capture.py --check` clean against the re-captured baseline;
   `inventory.py` zero outside `ALLOWED_FILES` and history.
2. Real-surface runs — the spec's Verification list, one by one (§8), through `uv run pflow`;
   one real `run-searcher` run and one review fan-out run with a `cwd` override **on the final
   branch** (the completion gate's own dispatch is the second).
3. Code-mode `deep-review`, full branch: the sensitive-path floor (`review-silent-failures`,
   `review-impact-completeness`, `review-feature-interactions`, `review-test-fidelity`) +
   `review-validation-consistency` + `review-agent-ux` + **`review-simplicity`** (deletion and a
   multi-phase build) + **`review-spec-conformance`**; `review-falsifier` last, direct launch,
   handed the spec and the conformance lens's Requirement Inventory.
4. Spec `## Status` → `done`, `## Completed`; `create-task-review` (covers both parts; states for
   Task 120 and Task 181 exactly what they inherit — §2.6); `create-pr` (closes #59; "Refs #621 —
   not a closing PR": its JavaScript half is Task 181; Refs #620, #686, #698).
5. Hand-back asks the main orchestrator to tell the user (a) saved workflows under
   `~/.pflow/workflows/` in the old form now fail validation with the fix, converting them is the
   user's call, and until then the skill symlinks (`core/workflow/skill_service.py:249`) keep
   showing agents the old form; (b) a paused or failed run of an old-form workflow resumes only
   after the file is converted **and** with `pflow resume --force` (the content hash changes —
   `execution/resume_preflight.py:158-172`; R, architecture-fit W1); (c) a live worktree whose
   `workflows/` copy predates Part 1 must merge `main` before the main checkout's `pflow` can run it.

---

## 5. Conversion rules (PC — mechanical; every decision made)

5.1 **Bind every Reference a body holds** in the step's `env:` (create it; nested-map form in
`.pflow.md`, a dict in IR) and replace it in the body with the variable.

5.2 **Names.** Examples and guide: UPPER_SNAKE chosen for the content (`ENDPOINT`, `WORKTREE`,
`REPO`). Tests: derive mechanically — the reference upper-cased, non-alphanumerics → `_`
(`${fetch-data.stdout}` → `FETCH_DATA_STDOUT`, `${item}` → `ITEM`, `${__index__}` → `INDEX`).
Rename on a hit of `AMBIENT_NAMES` (`${path}` → `PATH_VALUE`, never `PATH`; R) and run
`is_sensitive_parameter(name)` on every name chosen for ordinary data, renaming on a hit (`token`
singular, `secret`, `auth`, `password`, `credential`, `api_key`-style); real secrets keep a
sensitive name on purpose (`API_TOKEN`).

5.3 **Quoting — reproduce what the command received.**
- unquoted `${x}` → `"$X"`; inside double quotes `"…${x}…"` → `"…$X…"`; when a name character
  follows, split the quotes (`"$X"_suffix`) — **never `${X}` during PC** (D13);
- a whole single-quoted token `'${x}'` → `"$X"`;
- inside a longer single-quoted string (a jq/awk/python program, a quoted heredoc): tests splice
  — `'…'"$X"'…'` — which is byte-identical; examples and guide use the embedded tool's own
  argument passing where it has one (`jq --arg name "$NAME" '… $name …'`,
  `python3 -c '…' "$X"`), because examples teach;
- an unquoted heredoc expands `$X` as written; a quoted one (`<<'EOF'`) does not — pass the
  value as an argument or read it inside the program rather than unquoting the delimiter (which
  would turn on every `$`, backtick and `\` in the text; R);
- a value whose **producer** escaped it for the old pasting layer (a code step that pre-escapes
  `$`, backticks and `\` so the pasted text survives sh — `git-worktree-task-creator`'s Layer 0)
  loses that layer at the producer: the bound value is data, sh never re-scans it (R).
If the old unquoted form relied on word splitting of the value (`for f in ${files}`), keep `$X`
unquoted there and say so in a comment — the runnable baselines reveal these.

5.4 **`inputs:` on a shell step** that existed only to alias a value for the body is deleted and
the value bound directly in `env:`; it stays only as a loop Carry target.

5.5 **Batch:** `${item}`, `${item.field}`, `${__index__}` bind like any Reference.

5.6 **`$${x.cost}` (three agent examples — `claude-basic.pflow.md:32`,
`claude-git-workflow.pflow.md:123`, `claude-debug.pflow.md:82`):** bind the value
(`COST: ${generate.llm_usage.cost_usd}`) and write `\$$COST` inside the double-quoted string.

5.7 **Test classes** (§6): **T1** → rules 5.1-5.5; expected output must stay byte-identical — if
it does not, stop and look (it is a finding, not a fixture to update). **T2** → move the template
to the replacement param §6 names; keep the assertion's meaning; where an assertion names
`params.command` it becomes the new param's path. **T3** → untouched in PC, deleted or replaced in
PB as §6 says. **T4** → assert the static body where the test asserted the resolved command, and
the bound values through the surface PD built (`template_resolutions["env"]`, `shell_env`,
`## Env`, `preview["env"]`).

5.8 **Do not touch:** `.taskmaster/tasks/*` other than `task_118` and `task_159/baseline`,
`releases/`, `architecture/historical/`, `docs/changelog.mdx`, and anything under `~/.pflow/`.

---

## 6. Test classification (from two searcher passes that read every listed site)

T1 incidental → `env:` · T2 vehicle → another templated param · T3 retired behaviour (PB) ·
T4 asserts resolved command text on a display surface · T5 templated `code`.
`rt` = `tests/test_runtime`, `tv` = `…/test_template_validation`, `wfx` = `…/test_workflow_executor`.

### 6.1 `tests/test_runtime`, `tests/test_core`

| File | T1 | T2 | T3 | T4 | Notes |
|---|---|---|---|---|---|
| core/test_graph_build.py | 1 | 1 | | | 841: asserts **no** edge with `input_name == "command"` — would pass vacuously; bind `env: {T: ${item.text}}` and assert the edge whose `input_name == "T"` (an env leaf's edge is labelled by its dict key, `build.py:872-880`). 1532 T1. **1399 (T5)** pins an edge from `compute('${input_x.y}')` in a code body (`:1447` `next(…)` raises once the edge is gone) → rewrite with `inputs: {x: ${input_x.y}}`; in PB add the opposite assertion (no edge from the body). 1372-1378 follows the example (PC1) |
| core/test_ir_schema.py, core/test_markdown_parser.py | 2 | | | | schema/parse only — convert for the inventory, behaviour unaffected |
| core/test_loop_validation.py | | 2 | 1 | | 132, 145 → `stdin`. 460 (carry key via nested path, no warning) → PB: same assertion with the key in `env` |
| core/test_prompt_cache_validation.py | 1 | | | | 566 |
| core/test_trace_report.py | | | | 2 | 899, 1571 (`## Command` from `template_resolutions`), plus 2457 (`env` under Resolved Parameters) — all rewritten in PD |
| core/test_validation_utils.py | | 1 | | | 170 → `- stdin: ${sub.reslt}` (the positive control `.replace`s the same text) |
| core/test_workflow_data_flow.py | 3 | 19 | | | T1: 109, 110, 816. T2 → `env` values (data-flow recurses into dicts): 493 keeps `${array[@]} ${#count}` in the body and asserts `[]`; 521 keeps one error naming the ref; 547-602, 733-838, 957-1102. **Edit point:** helper `_wf(command)` at 1061 (7 tests the inventory cannot see) |
| core/test_workflow_validator.py | 1 | 2 | | | 336, 366 → `stdin` (their filter would match a leftover error) |
| core/test_approval_field.py, core/test_sub_workflow_validation.py | 8 | 2 | | | not in the inventory (inline/helper): approval 94, 106, 131 T1; sub-workflow 997, 1048, 1103, 1351, 2022 T1; 386, 501 T2 → `- stdin:` |
| rt/test_approval_gate.py | | | | 2 | helper `_shell_ir` (:50, 4 callers): `preview["command"] == "echo from-hello"` → the static body + `preview["env"]` |
| rt/test_gate_trace.py | | | | 1 | helper `_gated_ir`; `:57` exact-dict equality on the preview — add `env` |
| rt/test_batch_node.py | 6 | | | | stdout assertions only |
| rt/test_cache_integration.py, test_cache_opt_out.py, test_memoization_integration.py | 5 | | | | depend on the memo key including the resolved value — it does through `env` (regression guard in PA) |
| rt/test_compiler_output_wrapping.py | | | | | inventory false positive (`"code"` is an output name) |
| rt/test_initial_params_override_removal.py | 3 | | | | `engine.run` directly |
| rt/test_loop_control.py | 1 | | | | 101: a hand-built `static_params` — leave |
| rt/test_node_wrapper_template_validation.py | | 2 | | | 595, 610 call `split_params` with a `command` key and no node type → rename the key to `prompt` |
| rt/test_null_defaults.py | 4 | | | | compile-only |
| rt/test_only_snapshot.py | 7 | | | | 780 depends on the memo key; 1062 false positive |
| rt/test_prepare_inputs_extras.py, test_prompt_cache_dict.py | 3 | | | | |
| rt/test_resume_engine.py | 9 | | | | **edit points:** `_write_three_step_workflow` (:57, 10 callers), `WF_RECOVERED_COALESCE`; 763 false positive |
| rt/test_template_escape.py | | | 4 | (1) | #620 through real shell workflows: retarget the escape tests to `stdin` + `cat` (keeps #620 coverage — T2 move, in PC); the batch test's `results[0]["command"]` assertion goes; PB adds: `${X:-world}` runs unescaped, `$${` in a body is the error |
| rt/tv/test_array_notation.py | 8 | 1 | | | 366 → llm `prompt` like its siblings |
| rt/tv/test_batch_item_validation.py | 3 | | | | unfiltered `len(errors)` — must convert |
| rt/tv/test_malformed.py | | 15 | | | → `stdin` (mock shell `params: []`); 8 sites invisible to the inventory (39, 61, 82, 260, 318, 374, 432, 440). `TestIssuePassCoversEverySurface` `:389` lists `nodes[id=a].params.command` → `params.stdin`; in PB add `command` holding a malformed `${` to the fixture and assert it is **not** reported |
| rt/tv/test_literal_operands.py | | ≈13 | | | helper `_ir(command)` (:30-38) → `stdin` (invisible to the inventory) |
| rt/tv/test_types.py | | | 28 | | all Pass-7 behaviour (`TestShellCommand*` classes at 816, 920, 974, 1198, 1287; 640-813; 1421). PB: delete; replace 1385 with "a dict bound through `env:` arrives as `to_string` JSON, apostrophes intact" and add "a `${producer.response}` left in a command is the leftover error". 692 and 1264 (stdin allows a dict) become vacuous → delete |
| rt/tv/test_union_types.py | | 11 | | | path validation of union types — **vehicle, not retired** → `stdin` |
| rt/tv/test_validator.py | 3 | 2 | | | 974 → `stdin`; 1443 ("inputs-as-context works on any node type") → keep the shell node, `env: {OUTPUT: ${output}}`. Edit point `_write_child_with_outputs` (7 callers) |
| rt/test_trace_integration.py | 5 | 2 | | 2 | T4: 65 (`template_resolutions["command"]`) and 234 (per-item resolved commands) → `template_resolutions["env"]`. T2: 571 → `stdin`; 664 names `command` literally in a partial-resolution assertion → `stdin`, ordered before the failing `cwd` |
| rt/test_compile_once_regression.py, test_meta_inputs.py, wfx/test_ir_cache.py | ≈11 | | | | invisible to the inventory; T1 |
| rt/wfx/test_prep_error_action.py, wfx/test_workflow_executor.py | 5 | | | | 191 inline |
| rt/test_template_extract_pattern.py | | | 9 | | D7 — drop the `_build_quoted_templates` import and its 9 tests |

### 6.2 `tests/test_cli`, `test_integration`, `test_execution`, `test_mcp_server`, `test_nodes`, `test_docs`

No test in these directories asserts the param name (`params.command`, "in parameter 'command'"),
so every T2 here moves into an **`env` value** (the template still resolves; the diagnostic still
fires) unless noted. "missed" = invisible to the inventory.

| File | T1 | T2 | T3 | T4 | Notes |
|---|---|---|---|---|---|
| test_cli/test_dry_run.py | 2 | | | | 200 expects a missing-input failure — convert, or it passes for the wrong reason (leftover error) |
| test_cli/test_dual_mode_stdin.py | 4 | | | | old `'${data}'` single-quote form; `:317` real subprocess |
| test_cli/test_enhanced_error_output.py | 2 | 1 | | | edit points `_large_batch_failure_workflow`, `_degraded_large_batch_workflow`: bind **only** `${item.label}` (the tests assert `PAYLOAD-START` is absent from output — see PD test 8). 382 T2 |
| test_cli/test_guide.py, test_main.py, test_ui.py, test_unknown_flag_handling.py, test_unified_error_output.py, test_workflow_resolution.py, test_resume_no_hang_subprocess.py | 8 | | | | fixtures `_WF_IR`, `_WF` |
| test_cli/test_paused_cli.py | 3 | | | | constants `_ESC_WF` :519, `_REFORK_WF` :631, `_ESC_THEN_GATE_WF` :712. `_GATE_WF` :47 already uses `env` (the masking assertion at :120 — PA regression guard) |
| test_cli/test_resume_cli.py | 4 | | | | `_SHELL_WF` :69/:79 is one edit point for ≈30 tests (asserts `done upstream-value step2-ran`); 234; 878 `'${rounds.survivors[0]}'` |
| test_cli/test_ui_interaction_server.py | 3 | | | | `_VALID_IR` :49 (module fixture); missed :466 (`_workflow_with_input` — the input must stay referenced: keep it in `env`); 1315 |
| test_cli/test_validate_only.py | 5 | 4 | | | T1: 177, 202, 803-804, missed 762. T2 → env: 145 (undefined node — **passes vacuously if left in the body**), 629 (the second error that makes "Error 1:" appear), 827-828 (forward ref) |
| test_cli/test_approval_gate_cli.py (missed, :40) | | | | 1 | `:80` asserts `"posting-hello" in gate.preview.command` → the static body + `preview.env` |
| test_cli/test_cli_error_boundary.py :44, test_nested_workflow_cli.py :39/:53/:388 (helper `_make_parent_workflow`), test_run_node.py :604, test_run_tailer.py :848 (helper `_write_declared_defaults_wf`) — all missed | 6 | | | | |
| test_docs/test_guide_example_validation.py | | 1 | | | PF (see there) |
| test_execution/test_plan.py, test_plan_batch_sub_workflow.py | 14 | | | | helper `_write_first_item_bad_batch`; `fanout.count` int → `2` |
| test_execution/test_plan_drift.py | 22 | | | | incl. missed 2319, 2356 and the f-string sites 1786, 1906, 1912, 2103, 2204 (`${{seed}}`); 2789 false positive |
| test_execution/test_runner.py | 3 | 2 | | | T2 30-31 (cycle via data deps). **1060:** the vehicle is `cwd`; its `command: ${producer.stdout}` would now pre-empt the runtime path error with a validation error → make the command static. missed 819 |
| test_integration/test_branch_convergence.py, test_conditional_branching.py, test_task153_extras_stderr_agent_ux.py, test_inputs_forwarding_e2e.py (missed :51) | 5 | | | | |
| test_integration/test_cli_mcp_parity.py | 3 | | | 1 | fixture `batch_shell_workflow_ir`; `_gated_ir` :259 — the paused preview text asserts `posting-hello` → body + `env` (use a non-secret name) |
| test_integration/test_failed_node_invariant.py | 4 | 1 | | | 640 bind `.label` only; 1866 T2 (runtime strict error on a failed producer); `:1532`, `:97`, `:347` use static bodies — unaffected |
| test_integration/test_iteration_pattern.py | 1 | | | | f-string :81-84 — a shell step's `inputs:` keys read in the body → `env` |
| test_integration/test_loop_config.py | 1 | | | | missed :1135 — shell `inputs: state` + Carry: **keep `inputs:`**, add `env: {STATE: ${state}}`; rename the test (`…threads_into_command_text`). 1380 false positive |
| test_integration/test_json_nested_access_e2e.py | 9 | | | | numbers arrive as `1`/`2`/`123`; `:170` expects `ValueError` "Unresolved variables" — unchanged for an `env` value (strict resolution is generic); confirm when converting |
| test_integration/test_sigpipe_regression.py | 6 | | | | booleans → `True`/`False`, matched by `*[Tt]rue*`; emitted through `tests/shared/markdown_utils.py:128-130` (inline-map `env`) — confirm the round trip on the first conversion |
| test_integration/test_template_resolution_hardening.py | 2 | 12 | | | T1: 114, 232. T2 → env: 71, 147, 182, 259, 288, 321, 345, 377/382, 411/416, 456 (assert status and the ref text in the message) |
| test_integration/test_template_parity.py | | | | | no shell/code rows today. New `SURFACES` entries `shell_body` / `code_body` whose `build` puts `row.template` inside the body string, driven by `_resolve_param(row, config, shared, "<param>")` (returns `"static"` when the key is not in `template_params`, :396-397 → the existing `StaticLiteral()` outcome); and `shell_env` for PA |
| test_mcp_server/test_execution_workflow.py, test_registry_template.py | 2 | | | | `.label` only (payload assertion :203) |
| test_mcp_server/test_mcp_warnings.py | | 1 | | | asserts `context["template"]` holds `${fetch.stdout.nested_field}` → env value |
| test_mcp_server/test_validation_service.py | 1 | 5 | | | T2 → env: 66 (undefined — vacuous if left), 95/100 (cycle), 130 (unused input), missed 215. T1 234 asserts exactly `✓ Workflow is valid` — the converted form must add no advisory |
| test_nodes/test_shell/test_command_validation.py | | | 3 | | call `ShellNode` directly; `${dir}` there is already plain sh. Their premise (Pass 7) is gone → PB: replace with node-level `bind_env` tests |

### 6.3 Other breakage the conversion or the flip causes (not template sites)

- `tests/test_runtime/test_prompt_cache_hash.py::test_golden_baseline_hashes_match` — D14.
- `tests/test_core/test_react_flow_contract_fixtures.py` — only
  `examples/core/prompt-caching-multi-chunk.pflow.md` feeds a templated body into the contract
  fixtures; regenerate in PC1.
- `tests/test_docs/test_example_validation.py` validates all of `examples/` — the net for an
  unconverted example after the flip.
- Hand-built `shell_command` contexts (`tests/test_cli/test_agent_ux_fixes.py:30-110, 409-450`,
  `tests/test_cli/test_shell_stderr_display.py:149-150`, `tests/test_core/test_diagnostic.py:300-322`)
  break only if the block's labels or keys change — D9 adds `Env:` lines and a key, renames nothing.
- No existing test covers a non-string `env` value or the `exec_fallback` → `-2` path (PA adds both).

---

## 7. Stale-surface inventory (PF) — file:line on `b2cd92e3`, re-verify

**Guide (`src/pflow/guide/`):** `nodes/shell.md` 9, 12, 19, 24, 29-31, 40; `core.md` 580, 585, 643;
`nodes/code.md` 18, 61; `features/loop.md` 60; `features/batch.md` 26, 30, 138;
`features/branching.md` 71, 82, 110, 121; `features/sub-workflows.md` 52, 82, 194-201.
**MCP instruction resources (`src/pflow/mcp_server/resources/instructions/`):**
`mcp-agent-instructions.md` 255, 413, 722, 727, 733, 827, 1168, 1225, 1233, 1688, 1833, 1844, 1872,
1883, 1928-1930; `mcp-sandbox-agent-instructions.md` 257, 415, 718, 723, 729, 811, 1147, 1204, 1212,
1675, 1820, 1831, 1859, 1870, 1917.
**Docs:** `docs/reference/nodes/shell.mdx` 20, 35-39, 55-65, 80-118; `docs/reference/nodes/code.mdx`
67; `docs/how-it-works/loops.mdx` 47; `docs/how-it-works/template-variables.mdx` 247-249, 302,
312-330.
**Architecture:** `architecture/reference/template-variables.md` 493-497, 715-720, 1042, 1365-1418,
1420-1470 (the "Shell Command Limitations" section), 114-127 and 1161 (escape, generic — keep,
add the body exception); `architecture/features/simple-nodes.md` 228, 233.
**Source text:** `nodes/shell/shell.py` 83 (comment), 367-427 (docstring section, 5 templated
examples, "Pattern Detection"), 438; `registry/context_builder.py` 560-571 (shows `stdin` as the
only channel — add `env:`); `runtime/template_validation/type_validation.py` 4, 22-28 (module
docstring); `runtime/template_validation/validator.py` 8, 152 (Pass 7 mentions); `core/templates.py`
63-70 (comment "Enables embedding arrays/objects in shell commands"); `core/workflow/data_flow.py`
264-266 (docstring "bash syntax … is the Issue pass's to report").
**Instruction files:** `runtime/template_validation/CLAUDE.md` 15, 26-27, 56-58, 113-115 (and
92-93: the "do not populate `shell_command`" rule now holds — Pass 7 was its only violator);
`core/workflow/CLAUDE.md` 60-64; `core/CLAUDE.md` 101-103 (escapes: add "not in a code body");
`runtime/engine/CLAUDE.md` (Parameters section: bodies are static; `text` mode);
`nodes/CLAUDE.md` (where binding lives; the failure-path `env` output);
`tests/test_runtime/test_template_validation/CLAUDE.md` 13; `web/src/graph/CLAUDE.md` (the mirror
rule covers `isCodeBody`); `.claude/agents/pflow-codebase-searcher.md` (+ `make sync-claude-assets`).
**Also:** `architecture/core-concepts/data-type-coercion.md` 88-100, 216 (PA); `runtime/engine/engine.py:138-142`
docstring (PB). **Reported up, not edited (other tasks' specs):** `task-112.md:73` lists the shell
command type check (Pass 7) as existing coverage; `task-181.md` cites the unused-input check at
`core/workflow/validator.py:555-600`.
**Not stale (checked):** `README.md`, root `CLAUDE.md`, `architecture/architecture.md`,
`overview.md`, `guides/mcp-guide.md` (MCP server env), `.claude/skills/screenshot-pflow-web-ui/SKILL.md:34-35`
(an MCP code param — Task 181), `nodes/mcp.md:~112` (Task 181).

---

## 8. Verification matrix (spec → evidence)

| Spec Verification line | Evidence |
|---|---|
| `${NAME:-world}`, `${#X}`, `${HOME}`, `$$` validate and run unescaped | PB tests 4, 14; PZ real run |
| a value with quotes/newlines/`$`/backticks/leading `-` intact, POSIX and Windows; compact JSON unchanged | PA tests 2, 3, 10; `tests-windows` on Part 1's PR |
| number/boolean/null/object/array arrive as the decided text; validate-only = run | PA test 1 |
| each leftover shape is a validation error with a one-step fix; ambient not flagged; validate-only = run | PB tests 3, 4, 5 |
| a code body containing `${x}` fails validation; one without runs | PB test 7 |
| a looped shell step reads its carried value through `env:`; the warning on/off | PB test 9 |
| file-loaded `./cmd.sh` with `${HOME}` runs; `./scripts/$NAME.sh` is a command | PB test 10 |
| failing step's block and `pflow report` show body + bound values, secret masked, long value whole | PD tests 1-4 (the terminal block's 200-char cap is the stated display rule — checkpoint ruling 6; the spec line is tightened on the branch once ruled) |
| invalid name, oversized value, NUL fail before spawn naming the variable, incl. `ignore_errors` | PA tests 4, 5 |
| changing an `env:` value changes the memo key (regression guard) | PA test 8 |
| no edge or chip from a body; `env:` References keep theirs; Python and TS agree | PB test 1; PE parity rows + screenshots |
| the named corpus set identical before/after; fan-out and searcher run for real | PC gate; PA and PZ real runs |

---

## 9. Embedded checkpoints (flagged so the orchestrator plans them as hand-backs)

- **CP-1 — diagnostics, show before code. BUILT BY THE PLANNER AND RULED** (`diagnostics-checkpoint.md`
  is the ruled text; the progress-log entry of 2026-10-06 records the nine rulings — all as
  recommended). The task orchestrator's first act is to find that entry; it exists, so build. PA depends on ruling 4; PD on 6 and 7; PB on
  1, 2, 3, 5; PF on 8, 9. A ruling that changes text changes strings and assertions only; a ruling
  that changes rule 1 or 2 changes D5 — re-read D5 against it before PB.
- **CP-2 — Windows oracle (conditional).** D8-1, -2 or -3 failing on `tests-windows` is a design
  fork → hand back with the CI output and options; never add value translation on your own.
- **CP-3 — coordination, not user:** Part 1's merge changes `workflows/` (ask for a quiet moment);
  PE needs the `pflow ui` server slot; Part 2's merge is the breaking change (PZ step 5).

---

## 10. Risks, unverified, follow-ups

- **Unverified (settled only by CI):** every Windows behaviour in D8; the Linux per-value limit;
  the Windows error class for an oversized environment.
- **Assumed:** no user node registers as `shell`/`code`; the Codex-side searcher offload is
  runnable from the build's environment for the PA/PZ real runs — if it is not, hand back rather
  than skip (the spec requires the run).
- **The inventory is a map, not the gate.** It cannot see commands passed through helper arguments
  or built by `.format`; PB's suite run is what finds the tail.
- **A body is parsed read-only at validation.** `parse()` is cached on author text (≤4096
  entries); a large file-loaded script is one entry.
- **Approval previews** truncate each top-level param's JSON to 200 chars
  (`execution/gate_prompt.py`): a long `env:` map is cut where a long resolved command was cut
  before. Unchanged here; worth an issue if an approver hits it.
- **Follow-ups to file at the merge seam (not built):** carry resolved params on the failure
  record and retire the shell node's `command`/`env` failure outputs (with #698);
  `gate.masked_preview` duplicates `redact_sensitive`; `redact_sensitive` masks an empty
  secret-named value — an empty `API_TOKEN` behind a 401 is indistinguishable from a set one (R,
  agent-ux W4; the shared function is #715's, not this task's); http `headers`/`params` are string
  maps with the same JSON-parse hazard `env:` had (Task 120's predicate should cover them); the
  batch results' `command` key is now a constant repeated per item; a bare `${x}` outside a Python
  string is a generic "Python syntax error" from the markdown parser — an `inputs:` hint there
  would help (R, impact S3).
- **For the task-review (inheritors):** Task 120 *replaces* `binds_as_text`/`parses_leaves` with
  its declared-type rule (not "inherits"); Task 182: shellcheck's SC2153 did-you-mean works with
  UPPER_SNAKE names given a preamble assigning the bound names (executed by the architecture-fit
  lens); Task 181: `body_references` is the detector its safety-net warning reuses.

---

## 11. Proposed `context/CONTEXT.md` changes (the main orchestrator writes them)

- **Template** — amend: "a string in a Step's params containing `${…}` expressions, resolved
  against the shared store at runtime and checked against declared output structure at validation —
  one parse serves both surfaces. A Code body is never a Template. _Avoid_: placeholder,
  interpolation, substitution."
- **Code body** — new: "the program text of a shell step's `command` or a code step's `code`:
  plain sh / plain Python, never a Template — a `${…}` in it belongs to that language. Values
  reach it only through a Binding. _Avoid_: script, snippet, inline code, template body."
- **Binding** — new: "a named value pflow hands to a Code body as a variable of its language: an
  `env:` entry on a shell step (an environment variable, always text), an `inputs:` entry on a
  code step (a Python variable, typed). The entry's value is a Template; the body reads the name.
  _Avoid_: injection, interpolation, variable (unqualified — a Reference is not one)."
- **Issue** — append: "A Code body has no Issues."
- Ambiguity entry — **Binding vs Reference**: "both connect a step to data. A Reference names
  data in the shared store inside a Template (`${fetch.stdout}`); a Binding gives that data a
  name inside a Code body (`"$BODY"`). A shell step that uses an upstream value has both: the
  Reference in `env:`, the Binding in the command."
