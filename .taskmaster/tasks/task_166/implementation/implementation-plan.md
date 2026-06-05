# Task 166 — Declarative Stateful Loop Primitive (`carry:` + `until:`)

> Implementation plan for an isolated AI agent. Self-contained: read this top-to-bottom, then
> execute phase by phase. Every load-bearing fact below was verified against current source and/or
> run-proven by a spike. File:line anchors are starting points — re-confirm, they may drift.
>
> **Hardened by a 4-agent plan review (plan / validation-consistency / feature-interactions /
> silent-failures) + 4 source verifications.** The review caught one critical bug (the carry hook
> was in dead code) and several gaps; all are folded in below. Sections marked **[review-fix]** were
> corrected from the first draft — do not revert them.

## Context

`pflow`'s `loop:` modifier today is a do-while over a node's own typed output (`while:` +
`max_iterations`), with **no first-class way to carry state across iterations**. To accumulate
state (a shrinking contender list, a running best, a draft+feedback), authors hand-assemble a
backward-edge worker/checker and thread the accumulator across *sibling* nodes — verbose,
error-prone, hard to read. Two specific failure modes motivated this task:

1. **Invisible output→input coupling** silently feeds stale state (loop runs wrong or to `max`).
2. A single polarity-ambiguous `while:` causes a silent *"poll until done → runs once and exits"*
   bug that type-checks, runs, and looks plausible — no static check can catch it.

**This task** extends the existing `loop:` modifier (it stays a modifier, symmetric with `batch:`)
with three things:
- **`carry:`** — an explicit map `{ body_input: ${loop-node-id.output} }` declaring which body
  output feeds which body input next iteration. Mirrors `inputs:` shape so the direction is
  unambiguous and un-reversible.
- **`inputs:` as the round-1 seed** — `carry:` overrides the carried keys from round 2 on. No
  separate `seed:` field.
- **`while:` + `until:`** — two mutually-exclusive, exactly-one-required polarity keywords.
  `while: X` continues while X truthy; `until: X` continues while X falsy.

**Intended outcome:** the tournament / evaluator-optimizer / validate-fix / poll patterns become
expressible in ONE loop node — no sibling counter, no backward edge — and a fresh AI agent authors
a correct loop on the first try.

### Why this is a thin surface, not a loop engine (run-proven)

The loop self-reference substrate already works at runtime — **proven by spike on current `main`**,
not just code-read:
- `shared[node_id]` persists across iterations; template context is `dict(shared)` with **no
  self-exclusion**, so a loop node's own prior output is readable as `${node-id.field}` during the
  next iteration's input resolution.
- A code-node loop whose `inputs:` reference its OWN prior output (`${tick.result.acc ?? 0}`)
  accumulated `1→2→3→4` and stopped on the **condition** (not the cap) — self-reference threads.
- A `type: workflow` loop carrying the child's output back into the child's input
  (`${count.n_plus ?? 0}`) accumulated `1→2→3`, condition stop — sub-workflow carry threads.
- Coalesce accepts a **reference** fallback (`${self.x ?? some_input}`), not only literals.

So **manual carry already works today** via `${self.field ?? seed}`. `carry:` is a *safe, explicit,
statically-checked declarative surface* over this proven mechanism — NOT new state plumbing.

(Spike fixtures live in `scratchpads/task-166-loop-carry/` — keep as **regression** fixtures: they
use the manual `${self.field ?? seed}` pattern, so they prove the substrate stays intact, NOT the
new `carry:` surface. See Phase 5.)

## Decisions already made (do not re-litigate)

| Decision | Choice | Rationale |
|---|---|---|
| Node shape | **Modifier** on a node (not `type: loop`) | Symmetric with `batch:`; loop is engine behavior |
| Coupling | **Explicit `carry:` map**, statically checked | Implicit coupling is the #1 reliability risk |
| Seed | **`inputs:` is the round-1 value**; no `seed:` field | Collapses a field; carry declares which keys are carried |
| Polarity | **`while:` + `until:`**, exactly one required | Kills the silent "runs once and exits" bug |
| Output refs | **`${loop-node-id.field}`** (no `${body}`/`${acc}`) | Zero new reserved word; reuses verified substrate |
| **Body-type scope** | **ALL node types**, uniformly | carry overrides `inputs:` keys; resolution is type-agnostic (verified) |
| **Runtime mechanism** | **Explicit override** (round-N>1 swaps carried key's input template), NOT desugar-to-coalesce | Round N>1 ALWAYS uses the carry ref → absent/typo'd carried output is loud, not a silent re-seed |
| `max_iterations` | optional | Visit guard (default 100, `MAX_NODE_VISITS`) backstops |
| **Carry + permissive mode** `[review-fix]` | **Carry refs resolve STRICTLY regardless of `template_resolution_mode`** — an unresolved carried key RAISES even in permissive workflows | Carry is structural plumbing; silently passing the literal `"${...}"` string defeats the task's #1 anti-goal. Permissive mode otherwise leaves it as a DEGRADED warning (verified) |
| **`until` + absent source** `[review-fix]` | **Continue (re-run), bounded by `max_iterations`** — absent is treated as a falsy *value*, so `until` keeps looping until the field appears truthy | Stop-on-absent would re-introduce the silent "runs once and exits" bug for a body that omits the field while not-yet-done. Failure on a typo is then loud + bounded (spins to cap). `while` behavior is unchanged |

### Validation rulings (decided)

- **Carry values MUST self-reference the loop node** (`${this-loop-node.field}`) — carrying from
  another node is meaningless; reject it.
- **Every carry key MUST have a seed in `inputs:`** — explicit round-1 value required.
- **Typo-check precision is type-dependent (acceptable, mirrors existing `while:` behavior):**
  for `workflow` bodies the carry input/output check is *precise* (declared `## Inputs`/`## Outputs`);
  for `code`/`llm` bodies the body output is loosely-typed (`result`/`response`) so nested-field
  checks are best-effort.

### Uniform-body caveat to document (not a code blocker)

`carry:` overrides keys in the node's `inputs:` map. The resolved value reaches the body through
that body type's existing sink:
- **code/python** body: consumed as `params["inputs"]` (locals). ✅ direct
- **workflow** body: mapped to the child's declared inputs. ✅ direct
- **llm/shell** body: the node does NOT read `inputs` at exec time — it reads the resolved
  `prompt`/`command`. A carried key is only effective if the prompt/command text references it
  (`${key}`). Carry into `inputs:` alone is inert for these types. → **Document this**, AND emit a
  validation WARNING when a carried key is never referenced in the prompt/command `[review-fix —
  promoted to required]` (a carried-but-unreferenced key is silent staleness in disguise). See Phase 4b.

## Target syntax (converged)

**Tournament (carries a shrinking contender list):**
```markdown
### run-rounds
- type: workflow
- workflow: ./judge-round.pflow.md     # input: contenders ; outputs: survivors, more
- inputs:
    contenders: ${initial_lineup}      # round-1 seed (carry overrides round 2+)
- loop:
    carry:
      contenders: ${run-rounds.survivors}   # next round: input `contenders` <- this node's `survivors`
    while: ${run-rounds.more}                # continue while body's `more` is truthy
    max_iterations: 100
```

**Poll (no carried state):**
```markdown
### wait
- type: workflow
- workflow: ./check-status.pflow.md
- inputs:
    job_id: ${job_id}                  # constant every round
- loop:
    until: ${wait.pending}             # stop when body's `pending` is truthy
    max_iterations: 60
```

## Architecture — three mechanisms

All anchors verified against current source on `feat/declarative-stateful-loop`.

1. **Carry-override (runtime):** on iteration > 1, swap each carried input key's template to its
   carry ref before resolution (at the top of `_execute_node`, so hash+resolution+execution agree).
   Round 1 uses the `inputs:` seed. A strict guard makes an unresolved carried key raise in any mode.
2. **`until` polarity (runtime):** reuse the `while` evaluation path, restructured so absent/unresolved
   becomes a falsy *value* and polarity applies uniformly — `while`+absent→stop (unchanged),
   `until`+absent→continue. Malformed template + string value → hard stop/raise for both.
3. **Validation (two parity layers + a shared polarity helper):** `carry`/`until`/exactly-one-of
   rules added to BOTH the compiler run-path AND the `data_flow.py` save/`--validate-only` path
   (exactly-one-of via one shared pure function), plus the typed-bool + carry-typo checks in
   `template_validation/validator.py`.

> ⚠️ **PARITY (load-bearing):** `compiler.py::_build_loop_config` (run path) and
> `core/workflow/data_flow.py` (save/`--validate-only` path — *never compiles*) are two
> independent loop validators. Documented lesson in `core/workflow/CLAUDE.md` ("Data flow
> validation parity"). **Every new loop rule must be added to BOTH** or a workflow passes
> `pflow validate` and fails at runtime (or vice-versa). The compiler does shape/exactly-one-of;
> `data_flow.py` mirrors shape/exactly-one-of/self-ref/seed; `validator.py` does the
> type/typo checks (it alone has `node_outputs`).

---

## Phase 0 — Substrate spike ✅ DONE

Run-proven on current `main`. Fixtures in `scratchpads/task-166-loop-carry/`:
`spike-self-reference.pflow.md` (inline code carry), `spike-subworkflow-carry.pflow.md` +
`child-inc.pflow.md` (workflow carry), `spike-coalesce-refseed.pflow.md` (ref seed). Move these into
the test suite as **regression** fixtures (they prove the substrate is untouched — they use the
manual `??` pattern, NOT the new `carry:` keyword; see Phase 5).

## Phase 1 — Schema / types / compiler (run-path shape)

**`src/pflow/runtime/engine/types.py`** (`LoopConfig`, ~38–51) — add new fields **at the END**
`[review-fix]` so `while_template` + `max_iterations` stay positional-compatible with existing
construction sites:
```python
@dataclass
class LoopConfig:
    while_template: Optional[str] = None      # was: required str — now optional (until is the alt)
    max_iterations: Optional[int] = None
    max_iterations_template: Optional[str] = None
    until_template: Optional[str] = None      # NEW — mutually exclusive with while_template
    carry: dict[str, str] = field(default_factory=dict)   # NEW — {body_input_key: "${loop-node.field}"}
```
*(import `field` from dataclasses.)* **Audit ALL `LoopConfig(` sites** `[review-fix]`: production
`compiler.py:~424` (1 site); tests `test_loop_compiler.py:~26,~80` (full-equality — pass once
expected objects also default the new fields), `test_loop_control.py:~68,72,76,80,85,91`
(positional first-arg — safe with end-append), `test_only_snapshot.py:~671` (kwargs — safe).

**`src/pflow/core/ir_schema.py`** (`LOOP_CONFIG_SCHEMA`, ~146–177):
- Add `"until"`: same shape as `while` (`{"type":"string","pattern": r"^\$\{.+\}$"}`).
- Add `"carry"`: `{"type":"object","additionalProperties":{"type":"string","pattern": r"^\$\{.+\}$"}}`.
- Drop `"while"` from `required` → `required: []` (exactly-one enforced in code for a rich error).
- Keep `additionalProperties: False` (it's the only thing catching a `whlie:` typo).

**`src/pflow/runtime/compilation/compiler.py`** (`_build_loop_config`, ~372–428):
- Read `until = loop_data.get("until")` alongside `while`.
- **Exactly-one-of enforcement** (match the batch/loop idiom at ~388): raise
  `CompilationError(msg, phase="loop_config", node_id=node_id, node_type=node_type, suggestion=...)`
  when both `while` and `until` are set, and when neither is set. (Replaces the current
  "missing while" raise.)
- Read `carry = loop_data.get("carry") or {}` (validate it's a dict; non-dict → `CompilationError`).
- Construct `LoopConfig(while_template=while or None, until_template=until or None, carry=carry, ...)`.
- The compiler does NOT do typo/seed/self-ref checks (those need `node_outputs` → validator layer).

**`src/pflow/core/markdown_parser.py`** — NO CHANGE. `[review-fix]` Both authoring forms land the
whole `loop:` block as an opaque dict on `node["loop"]`: the inline `- loop:` bullet via
`_parse_yaml_items` → hoist at `~1600–1602`; the fenced ```` ```loop ```` block via
`_route_code_blocks` at `~1187–1190`. Neither reads sub-keys, so `carry:`/`until:` arrive
automatically — the compiler/schema/validators interpret them.

## Phase 2 — Engine carry-override (runtime) `[review-fix — hook relocated]`

> ⚠️ **The first draft put this hook in `_execute_single_node` — that is DEAD CODE for loop nodes.**
> `_execute_single_node` is *only* the batch per-item callback (sole caller `execute_batch`,
> engine.py:~830), and batch+loop are mutually exclusive, so a loop node NEVER reaches it. A
> non-batch loop node resolves templates inside `_execute_node` → `plan_node()`. Verified: every
> loop re-execution (walk re-entry via `_run_node_with_child_only`→`_execute_node:~358`, AND `--only`
> via `_run_only_snapshot:~536`) funnels through **`_execute_node` (engine.py:~746)** — the single
> chokepoint.

**New helper in `src/pflow/runtime/engine/loop_control.py`** (loop-cohesion home; operates on
`TemplateConfig` from `engine/types.py`):
```python
def apply_carry_overrides(tc: TemplateConfig, carry: dict[str, str]) -> TemplateConfig:
    """Round N>1 of a carried loop: override carried input keys with their carry refs.
    Returns a FRESH TemplateConfig — NEVER mutates the originals. The compiled
    template_config and its inner inputs dict are the SAME objects every iteration
    (verified); in-place mutation would leak across iterations and corrupt
    CompiledWorkflow reuse. `inputs` is stored all-or-nothing in template_params OR
    static_params; merge both, route the whole map through template_params (carry refs
    are templates), and strip inputs from static_params so resolved inputs win the
    `merged_params = {**static, **resolved}` merge."""
    from dataclasses import replace
    current_inputs = {
        **tc.static_params.get("inputs", {}),
        **tc.template_params.get("inputs", {}),
    }
    effective_inputs = {**current_inputs, **carry}   # carry refs override carried keys
    return replace(
        tc,
        template_params={**tc.template_params, "inputs": effective_inputs},
        static_params={k: v for k, v in tc.static_params.items() if k != "inputs"},
    )
```

**Hook: rebind `config` at the TOP of `_execute_node`** (engine.py:~746), BEFORE any `config` use
(esp. before `plan_node(node, config, shared)` at ~773 — which reads `config.template_config` for
BOTH the config-hash AND `resolve_templates`, keeping hash/resolution/execution consistent):
```python
def _execute_node(self, node, config, shared):
    # Task 166: on loop re-entry (iteration > 1) swap carried inputs into an EFFECTIVE
    # config before plan_node, so resolution + config_hash + execution all observe the
    # override. Built fresh from the pristine config each pass (workflow.node_configs is
    # untouched → no accumulation across iterations).
    if (config.loop_config is not None and config.loop_config.carry
            and shared.get("__iteration__", 1) > 1):
        config = dataclasses.replace(
            config, template_config=apply_carry_overrides(config.template_config, config.loop_config.carry))
    ...  # rest unchanged — every downstream `config.*` (~30 sites) now sees the effective copy
```
- `NodeConfig` and `TemplateConfig` are plain (non-frozen) dataclasses → `dataclasses.replace` works.
  Rebinding the local `config` once is **complete**: all ~30 downstream `config.*` reads (hash
  compare, cache write, trace, batch branch) see the effective copy. `_loop_should_reenter` /
  `resolve_loop_cap` read the ORIGINAL `workflow.node_configs[node_id]` (while/max_iterations must
  never be carried) — no bleed, correct.
- `shared["__iteration__"]` is set by `loop_runtime_scope` (~468) wrapping this call; 1-based.
  Round 1 / `--only` → `__iteration__ == 1` → no override → seed.
- Uniform across body types: carry overrides `inputs:`; the resolved value reaches code (locals),
  workflow (child inputs), llm/shell (prompt/command `${key}` interpolation) via each type's
  existing sink. No per-type branching.

**Strict carry-resolution guard `[review-fix — DECISION: strict on carry always]`.** After
`plan_node` returns (in `_execute_node`, on a carry iteration only), assert every carried key in the
resolved `inputs` actually resolved — independent of `template_resolution_mode`. In *permissive*
mode `resolve_templates` does NOT raise on an absent ref; it leaves the literal `"${loop-node.field}"`
string and records a DEGRADED warning (verified). Carry is a structural contract, so:
```python
# carry iteration only, after resolved_params is available
resolved_inputs = plan.resolved_params.get("inputs", {})
for key in config.loop_config.carry:
    val = resolved_inputs.get(key)
    if contains_unresolved_template(val, ...):     # reuse template_resolution.contains_unresolved_template
        raise <PflowError subclass>(  # e.g. a LoopCarryError in core/exceptions.py
            f"Loop '{config.node_id}': carried input '{key}' did not resolve "
            f"({val!r}). The body did not produce the carried output this iteration.")
```
This makes an absent/typo'd carried output LOUD in every mode — the guarantee the whole "explicit
override" mechanism exists to provide.

## Phase 3 — `until` polarity inversion (runtime) `[review-fix — absent→continue]`

**`src/pflow/runtime/engine/loop_control.py`** (`evaluate_loop_condition`, ~63–102): **restructure**
so absent/unresolved becomes a falsy *value* and polarity applies uniformly. This is the corrected
design (DECISION: `until` + absent → continue, bounded by cap). Behavior-preserving for `while`.
```python
def evaluate_loop_condition(condition_template, shared, node_id, *, until=False) -> bool:
    context = dict(shared)
    var = extract_simple_template_var(condition_template)
    if var is None:
        return False  # MALFORMED template (not a single ${...}) → hard STOP for BOTH polarities
                      # (validator rejects this shape; this is a bypassed-IR backstop)
    if is_coalesce_expression(var):
        value, status = resolve_coalesce(var, context)
        if status != "resolved":
            value = None          # unresolved coalesce → treat as falsy VALUE (was: return False)
    elif not variable_exists(var, context):
        value = None              # absent reference → treat as falsy VALUE (was: return False)
    else:
        value = resolve_value(var, context)
    if isinstance(value, str):
        raise LoopConditionError(...)   # string foot-gun → raise for BOTH polarities (unchanged)
    truthy = bool(value)                # None → False
    return (not truthy) if until else truthy
```
Why this is correct and safe:
- `while` unchanged: absent → `value=None` → `bool(None)=False` → `return False` (stop). Identical
  to today for all three former-guard cases.
- `until` correct: absent → `value=None` → `truthy=False` → `return not False = True` (continue,
  to cap). A poll whose body omits the field while not-yet-done keeps looping instead of exiting
  once. A typo spins to the cap (loud, bounded) — never silent-runs-once.
- Malformed template (`var is None`) → hard STOP for both (backstop; validator already rejects it).
- String value → `LoopConditionError` for both (the `"false"`-is-truthy foot-gun applies to `until`).

**`src/pflow/runtime/engine/engine.py`** (`_loop_should_reenter`, the `while_template` read at ~605):
```python
if loop_config.until_template is not None:
    should_continue = evaluate_loop_condition(loop_config.until_template, shared, node_id, until=True)
else:
    should_continue = evaluate_loop_condition(loop_config.while_template, shared, node_id)
```
Keep `_mark_loop_stopped(shared, node_id, "condition")` for both polarities (stop *reason* is still
"condition"). **Defensive guard `[review-fix]`:** if BOTH `until_template` and `while_template` are
None (can't happen post-validation, but a probe/programmatic IR could bypass `_build_loop_config`),
raise `LoopConditionError` rather than calling `evaluate_loop_condition(None, ...)`.

## Phase 4 — Validation (the bulk; two parity layers)

**Shared exactly-one-of helper `[review-fix — S1]`.** To avoid hand-maintaining the polarity rule in
two places (the plan's own "load-bearing parity" risk), extract ONE pure function — e.g.
`check_loop_polarity(loop_data) -> Optional[str]` returning an error message (or `None`) for
both-set / neither-set — in a module both layers import (alongside the loop helpers). The compiler
wraps its result in `CompilationError`; `data_flow.py` wraps it in a `Diagnostic`. This mirrors the
codebase's existing shared-`validate_data_flow` pattern. **Ordering:** the polarity check must run
BEFORE the per-field condition walks (4a/4b) so a both-set workflow doesn't also emit confusing
per-field diagnostics.

### 4a. `src/pflow/core/workflow/data_flow.py` (pure-IR shape — save/`--validate-only` path)

In **`_validate_loop_node_combos`** (~545–590; gated by `isinstance(loop_data, dict)` at ~586) add,
each emitting a `Diagnostic` via a new `_make_loop_*` builder matching the existing idiom
(`severity=Severity.ERROR, source="validator", title="Validation Error", node_id=node_id,
message=f"...", suggestions=[...], context={"category":"validation","path":f"nodes[id={node_id}].loop"}`;
NO catalog `id`):
- **Exactly-one-of while/until** — both-set or neither-set → error. (Parity twin of the compiler check.)
- **Carry value self-reference** — for each `carry` value, parse the `${root.field}` root; if
  `root != node_id` → error (`carry` must reference the loop node's own output). Pure string parse,
  no `node_outputs` needed. *(The generic forward-ref check does NOT enforce this — it only rejects
  forward refs, so an upstream other-node ref would otherwise pass.)*
- **Carry key has a seed** — each `carry` key must appear in `node["params"]["inputs"]` → else error
  (a carried input needs a round-1 value). *(`inputs:` lands in `params["inputs"]` — verified.)*

In **`_validate_node_params`** (the loop-source threading block, ~794–825): add a parallel
`loop_block.get("until")` walk through `_check_param_value("loop.until", ...)` (mirror the `while`
walk at ~796–810) so a forward-ref `until: ${downstream.x}` is caught. **Guard with
`isinstance(until, str)` `[review-fix]`** exactly like the `while` walk — a mis-authored non-string
`until` (e.g. YAML bool) must not reach `_check_param_value`. *(Do NOT thread `carry` here — its
self-ref + typo are handled by 4a above and 4b below.)*

### 4b. `src/pflow/runtime/template_validation/validator.py` (type/typo — has `node_outputs`)

- **`until` typed-bool gate (raw-string rejection):** in `_validate_loop_conditions` (~207–221) the
  single read site is `loop_config.get("while")` at ~215. Iterate over BOTH `while` and `until`
  (each present string → `_loop_condition_diagnostic`). **Parameterize the field name into BOTH the
  `path` AND the message TEXT `[review-fix]`** of the three `_make_loop_*` builders — the message
  hard-codes `` `loop: while:` `` at ~273/293/313, not just the `path` at ~282/302/324. Otherwise an
  `until` error reads "while:" while pointing at `.loop.until` — a confusing inconsistency in the
  very feature meant to kill polarity confusion. `until` thus inherits operator-rejection +
  single-ref-shape + raw-string rejection for free. (`has_loop` early-exit at ~124 already covers
  `until` — it checks `node.get("loop")`, not subfields.)
- **NEW carry-typo check** — add `_validate_loop_carry_refs(workflow_ir, node_outputs)`, called
  alongside `_validate_loop_conditions` (Pass 10 wiring ~169), **gated to run AFTER the 4a self-ref
  check `[review-fix]`** (so a bare-aliased carry like `${survivors}` — missing the node prefix —
  fails the self-ref check, not a misleading "unknown output"). For each loop node with `carry`, for
  each carry value: extract the var via `TemplateResolver.extract_simple_template_var`; take the
  **root output segment** (e.g. `${run-rounds.result.acc}` → root output `result`); check membership
  using the **namespaced `f"{node_id}.{root}"` key ONLY `[review-fix]`** — NOT the bare alias key
  (`_register_workflow_node_outputs` registers both `node_outputs["run-rounds.survivors"]` AND bare
  `node_outputs["survivors"]`; the bare alias would mask a missing-prefix mistake). If the loop node
  has **precisely-registered outputs** (static `type: workflow` declared `## Outputs`, or a `code`
  body's `result` — node has `f"{node_id}.*"` keys not flagged `is_workflow_dynamic`) and
  `f"{node_id}.{root}"` ∉ `node_outputs` → emit a carry-unknown-output `Diagnostic`. **Skip
  (best-effort) when body outputs are dynamic/loose** (templated `workflow:` → `is_workflow_dynamic`;
  llm/shell registry outputs). Precise for tournament/workflow + code; zero false-positives elsewhere.
- **NEW llm/shell carried-key-unreferenced WARNING `[review-fix — W1/W2 feature-interactions]`** — for
  a loop body that is `llm`/`shell` (carry into `inputs:` is inert unless the prompt/command text
  references `${key}`): if a carried key never appears in the node's resolved `prompt`/`system`/
  `command` template text, emit a `Severity.WARNING` (not error — there are indirect-reference edges).
  A carried-but-unreferenced key is silent staleness in disguise — exactly what the task kills. This
  is the validate-time backstop for the body types where the carry-typo check is best-effort; the
  runtime strict-carry guard (Phase 2) is the other half.
- **No change to `_register_loop_node_outputs`** (~737–769): carry values reference body outputs
  already registered by `_register_workflow_node_outputs` (workflow) / code-`result` enrichment.

### Validation matrix (check → home → why)

| Check | Layer(s) | Precision |
|---|---|---|
| Exactly-one-of `while`/`until` | compiler + data_flow | always |
| `until` is single typed-bool ref (no operators / not string) | validator.py (reuse `_loop_condition_diagnostic`) | per body type (same as `while`) |
| `until` not a forward ref to another node | data_flow `_validate_node_params` | always |
| Carry value self-references the loop node | data_flow `_validate_loop_node_combos` | always (pure IR) |
| Carry key has a round-1 seed in `inputs:` | data_flow `_validate_loop_node_combos` | always (pure IR) |
| Carry value references a real body output (typo) | validator.py (NEW `_validate_loop_carry_refs`) | precise: workflow(static)+code; best-effort: llm/shell/dynamic |
| Carry key is a real body input | **NONE NEEDED** | subsumed by "carry key ∈ `inputs:`" + existing undeclared-input validation (Task 153 / code annotations) |
| llm/shell carried key referenced in prompt/command | validator.py (NEW, WARNING) | best-effort string check; backstopped by Phase-2 strict-carry guard |

**Parity & ordering notes `[review-fix]` (state these so a reader doesn't over-trust a layer):**
- The 4a **seed check is presence-only** — it confirms `carry key ∈ params.inputs`, NOT that the
  seed resolves; seed *resolution* is covered by the existing `_validate_node_params` input walk.
- **`carry` non-dict** is caught on the validate path by the schema (`carry: {type: object}`) and on
  the run path by `_build_loop_config`'s explicit dict guard — two mechanisms, same rule; keep both.
- **Schema short-circuit:** `additionalProperties: False` is a step-1 schema error, so a `whlie:`
  typo pre-empts the (step-4) exactly-one-of check. Both-set and neither-set pass the schema (both
  are valid properties / no required key), so they reach the exactly-one-of check — confirmed
  reachable.

## Phase 5 — Tests `[review-fix — spikes are REGRESSION-only; content-asserting integration is non-negotiable]`

> The Phase-0 spikes use the MANUAL `${self.field ?? seed}` + `while:` pattern — they prove the
> substrate is untouched (**regression**), they exercise ZERO of the new `carry:`/`until:` surface.
> Do NOT treat them as carry coverage; the new feature needs the new fixtures below.

**Unit**
- `tests/test_core/…ir_schema`: schema accepts `carry`/`until`; rejects unknown loop keys; rejects
  non-dict `carry`.
- `tests/test_runtime/test_loop_compiler.py`: `_build_loop_config` parses carry/until; both-set →
  `CompilationError`; neither-set → `CompilationError`. Confirm the full-equality `LoopConfig(...)`
  fixtures (~:26, ~:80) still pass (new fields default symmetrically).
- `tests/test_runtime/test_loop_control.py` — the restructured `evaluate_loop_condition`:
  `until=True` + resolved-truthy → STOP (`False`); `until=True` + resolved-**falsy** → CONTINUE
  (`True`); `until=True` + **absent** source → CONTINUE (`True`) `[review-fix]`; malformed template
  (`var is None`) → STOP for both; string value → `LoopConditionError` for both. Pin `while`
  unchanged: absent → STOP. NEW: `apply_carry_overrides` returns a fresh object (assert the ORIGINAL
  `template_config` and its inner `inputs` dict are unmutated — identity check), overrides carried
  keys, preserves a constant (non-carried) input **with its value AND type** — cover BOTH a
  templated-seed loop and an all-static-inputs-with-carry loop (the static→template move).
- Other `LoopConfig(` sites (`test_only_snapshot.py:671`, etc.): confirm still construct.

**Integration (run real workflows)**
- **Tournament — CONTENT-ASSERTING, non-negotiable `[review-fix]`:** a `judge-round` child
  (`contenders → survivors, more`) looped with `carry` + `while`. Assert the **carried value's
  CONTENT changes across rounds** (round-2 `contenders` == round-1 `survivors`), not merely the
  iteration count — this is the ONLY test that catches the C1-class "hook never fires, seed re-used"
  failure. End state: one winner, no sibling counter.
- Poll: `until` only, no carry — runs to condition.
- Validate-fix: carry a draft+feedback pair.
- **Constant-vs-carried fixture** (spec's explicit verification): one *carried* + one *constant*
  input; assert round N>1 carried reflects prior output AND the constant is unchanged every round.
- **No-carry loop guard `[review-fix]`:** a `while:`-only loop with constant inputs (no `carry:`) —
  assert its `inputs` are NOT rewritten on iteration 2 (guards the 3-conjunct override gate).
- **Carry × on-error `[review-fix]`:** a carry loop whose body routes to `on-error` on iteration 2 —
  assert the handler behaves sanely (the failed iteration's carried output is in `__failures__`, so
  a handler templating the loop node's output sees absent, not stale carried state).
- **Strict carry under permissive mode `[review-fix — DECISION]`:** a workflow with
  `template_resolution_mode: permissive` and an absent/typo'd carried output → must RAISE (loud), not
  pass the literal `"${...}"` string.

**Validation (assert exact diagnostics, both `pflow validate` and run paths)**
- Typo'd carry output on a workflow body → carry-unknown-output error.
- Carry key without a seed → carry-seed error.
- Carry value referencing another node (and bare-aliased `${field}`) → carry-self-ref error.
- `while` + `until` both / neither → polarity error (single diagnostic, not cascaded).
- `until` referencing a string output → string-type diagnostic with `until` in the MESSAGE + path.
- llm/shell carried key never referenced in prompt/command → WARNING.

**Regression**
- The Phase-0 spikes still pass unchanged (substrate untouched).
- Existing `loop:` examples (`examples/agent-orchestration/...`) still validate + run unchanged.
- Nested `loop: + storage_mode: shared` inside a sub-workflow body still rejected at validate time
  (verified: recursive validation catches it — guards the parent `__iteration__` the carry gate reads).

## Phase 6 — Docs + `pflow guide`

- `pflow guide` loop section: add `carry:` / `until:` / seed semantics + a tournament snippet (this
  is what the acceptance-gate agents read).
- `docs/` loop page + a runnable `examples/` tournament workflow.
- Document the **llm/shell caveat**: a carried key is only effective if referenced in the
  prompt/command text (carry into `inputs:` alone is inert for those sinks).
- `[review-fix]` Note the **`until` + absent semantics** (one sentence): an absent `until:` source
  keeps looping (to the cap), so `until` never silently exits after one pass.
- `[review-fix]` Note the **`--only` caveat**: `--only <loop-node>` runs exactly one iteration with
  round-1 seed inputs — carried state never advances, so it can't reproduce a mid-loop iteration.

## Phase 7 — Acceptance gate (the REAL definition of done)

Hand fresh general-purpose agents (no pflow context, only the new guide text) the three cases
(tournament / poll / validate-fix); measure first-try authoring correctness + recurring mistakes.
If agents trip, adjust **syntax/guide**, not tests. Only here, if it surfaces, revisit the micro
choices (`${node-id}` vs `${body}`, etc.).

---

## Edge cases (decided / verified)

- **`until` + absent source** `[review-fix]` → CONTINUE to cap (not stop). See Phase 3.
- **Carry + permissive mode** `[review-fix]` → strict carry guard raises regardless of mode. See Phase 2.
- **`--only <loop-node>`** → one iteration, `__iteration__ == 1` → no carry. Correct (and can't
  reproduce a mid-loop iteration — guide note).
- **`--dry-run`** → planner walks the body once at iteration 1 (verified: reads only
  `loop_config is not None` + `resolve_loop_cap`, never `while`/`until`/`carry`). New fields do NOT
  break it; the carry-override is **engine-only — do NOT wire `apply_carry_overrides` into `plan.py`**
  `[review-fix]` (planning a carry ref against an absent prior output would emit a spurious plan-time
  template error). Carry plans the round-1 seed shape (fidelity limit, not a crash).
- **Memo cache** → `__loop_active__ > 0` suppresses memo *reads* during the loop (verified); the
  carry override changes the config-hash/cache-key anyway (override is before `plan_node`). Never stale.
- **Constant inputs** under carry → unmodified each round; scalar constants are coercion-no-ops on
  both the static and template path (verified), so the static→template move is value/type-safe.
- **Nested loop + `storage_mode: shared`** `[verified clean]` → caught at validate time by recursive
  sub-workflow validation; `mapped` (default) child storage keeps inner `__iteration__` in a separate
  dict. No clobber path carry introduces.
- **Both `while` and `until` None at runtime** → can't happen post-validation; the engine `else`
  branch raises `LoopConditionError` defensively `[review-fix]` (probe/programmatic IR can bypass
  `_build_loop_config`).
- **Nested loops** → the carry gate reads the PARENT frame's `__iteration__`; a `mapped` child
  sub-workflow's own inner-loop `__iteration__` lives in a separate dict (verified) — no collision.

## Files touched (summary)

| File | Change |
|---|---|
| `runtime/engine/types.py` | `LoopConfig` += `until_template`, `carry` (appended, defaulted) |
| `core/ir_schema.py` | `LOOP_CONFIG_SCHEMA` += `until`, `carry`; relax `required` |
| `runtime/compilation/compiler.py` | `_build_loop_config`: parse carry/until; call shared `check_loop_polarity` → `CompilationError`; non-dict-carry guard |
| `core/workflow/` (shared loop util) | NEW pure `check_loop_polarity(loop_data)` imported by compiler + data_flow |
| `runtime/engine/loop_control.py` | `apply_carry_overrides` (new); restructured `evaluate_loop_condition(..., until=)` |
| `runtime/engine/engine.py` | carry-override hook **at top of `_execute_node`** (rebind `config` via `dataclasses.replace`); strict carry-resolution guard after `plan_node`; `until` + defensive branch in `_loop_should_reenter` |
| `core/exceptions.py` | (maybe) a `LoopCarryError` for the strict-carry guard |
| `core/workflow/data_flow.py` | `_validate_loop_node_combos` += polarity (shared helper) / carry self-ref / carry seed; `_validate_node_params` += guarded `until` walk; new `_make_loop_*` builders |
| `runtime/template_validation/validator.py` | `_validate_loop_conditions` iterates while+until (param field in path AND message); new `_validate_loop_carry_refs` (namespaced-only, after self-ref); new llm/shell unreferenced-carry WARNING |
| `tests/...` | unit + integration (content-asserting tournament, no-carry guard, carry×on-error, permissive-strict) + validation + regression |
| `pflow guide` text + `docs/` + `examples/` | carry/until/seed + tournament example + until-absent + `--only` notes |

## Verification (end-to-end)

```bash
# 1. Regression: existing loop examples still work
uv run pflow examples/agent-orchestration/parallel-planner-review/orchestrate.pflow.md --validate-only

# 2. The three spikes (Phase 0 fixtures) still pass after changes
uv run pflow scratchpads/task-166-loop-carry/spike-self-reference.pflow.md       # 4 iters, acc=4, condition stop
uv run pflow scratchpads/task-166-loop-carry/spike-subworkflow-carry.pflow.md    # 3 iters, n_plus=3, condition stop

# 3. New carry/until syntax (author a tournament fixture) runs + validates
uv run pflow <tournament>.pflow.md --validate-only && uv run pflow <tournament>.pflow.md

# 4. Negative cases surface the right diagnostics
uv run pflow <typo-carry>.pflow.md --validate-only     # carry-unknown-output error
uv run pflow <both-while-until>.pflow.md --validate-only  # polarity error

# 5. Full suite + quality gates
make test && make check
```

**Acceptance gate (Phase 7):** fresh-agent first-try authoring of tournament/poll/validate-fix from
the guide text — the metric the whole design optimized for.

## Out of scope / non-goals

- Issue #471 (retry/backoff, "recovered-cleanly" status) — independent, keep out.
- Inline-body special-casing — there is none; carry is uniform on `inputs:` (a doc caveat for
  llm/shell prompt sinks, not code).
- A new `${body}`/`${acc}` reserved word, a `seed:` field, a `type: loop` node — all rejected.
- Trace per-iteration carried-state field (nice for the future flow view / Task 155) — not required.
