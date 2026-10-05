# Template Validation Package

`validate_workflow_templates` checks templates before execution. Its production
caller is `core/workflow/validator.py::WorkflowValidator`; compilation does not
run these passes.

## Find the check

| Symptom or change | Owner |
|---|---|
| Malformed template (the one Issue pass), unused input, loop condition | `validator.py` |
| Which references a pass checks, and how (the operand classifier) | `operands.py` |
| Where templates live in the IR (params, `batch.items`, loop, carry, outputs, cache) | `core/workflow/template_surfaces.py` |
| Missing node output/path, diagnostic field suggestions | `path_validation.py` |
| Parameter type, shell JSON coercion, code-input annotation | `type_validation.py` |
| `${item.field}` against inferred item structure | `batch_item_validation.py` |
| Type inference (compatibility: `core/templates.py::is_type_compatible`) | `type_checker.py` |
| Index into declared structure, dotted display, safe display | `utils.py::descend_index`, `dotted_parts`, `sanitize_for_display` |
| Output metadata or child workflow output discovery | `validator.py::extract_node_outputs`, `_resolve_child_workflow_outputs` |
| Paths shown by node-output formatters | `utils.py::flatten_output_structure` |

Malformed syntax returns early before semantic template checks. Unknown node
types are deliberately skipped by `_register_node_outputs_from_registry`:
the outer workflow validator owns their diagnostic. Raising here replaces a
useful unknown-type error with a validator exception.

## One enumeration, one Issue pass, one classifier

- Every template check walks `iter_template_surfaces`; a new template-bearing
  location is added there, never as another walk.
- `_validate_malformed_templates` is the ONE Issue pass: an Issue (an unescaped
  `${` that opens no Expression) is an ERROR on every surface, cache prose
  included. Any future tolerance (which Issues are errors on which surface) is
  decided there only; `parse()` has no mode.
- `operands.iter_template_operands` yields every Reference in params,
  `batch.items` and loop fields, a dynamic index's inner refs included, tagged
  `FIELD_CHECK` or `ROOT_ONLY`. Pass 5 and Pass 8 field-check `FIELD_CHECK`
  only (a `??` operand may miss its field at runtime and fall through); Pass 8 also
  filters by node id, since batch nodes may share an alias. `ROOT_ONLY` roots
  are checked by `core/workflow/data_flow.py`, over the same surfaces.
- Output sources: `operands.iter_output_source_operands` parses each as the
  runtime resolves it (`output_resolver.normalize_output_source` — a bare `n.x`
  is `${n.x}`). Their roots are `WorkflowValidator._validate_output_sources`'s;
  Pass 5 field-checks their `FIELD_CHECK` node-output paths only (a whole-node
  `n` source is legal), and all of them count toward unused inputs.
- A carry value's own reference and cache vars have their own passes (one
  diagnostic per mistake); cache vars also join unused-input accounting
  (`_extract_cache_templates_for_unused_check`). A carry may only reference the loop
  node itself, but its dynamic-index sources (`${s.lst[${i}]}`) are ordinary reads:
  `iter_template_operands` and data_flow check them (`Reference.index_sources`).
  Feeding cache vars to path validation produces two diagnostics for one mistake.
- Literal operands are not references. `TemplateResolver.is_literal_operand`
  is a coarse first-character check for already-parsed operands, not a
  literal validator.

Type, shell, and code-annotation passes (6, 7, 9) read params independently
through `TemplateResolver.extract_variables`; they do not consume the operand
iterator. When adding a template-bearing location, inspect those passes too.

## Output metadata and limits

`extract_node_outputs` builds the metadata consumed by the passes.
Read it for the shape rather than introducing a second metadata recipe.
`is_batch_output` controls batch path behavior; `is_batch_item` and
`is_inputs_context` record provenance, not pass-selection logic.

Batch `results` contains successes only. In continue mode, path validation blocks
positional indexing into it because positions no longer identify original items.
Child workflow outputs are resolved separately at validation time.

User parameters allow deep access without validating their runtime structure;
known node output structures receive traversal checks. Do not turn this into a
promise that all runtime paths have been validated.

## Diagnostic producers

Construct `Diagnostic` at detection sites, retaining the structured path,
suggestions, and available fields. Rendering belongs to `core/diagnostic_render.py`.

| Context key | Purpose |
|---|---|
| `category` | Validation/template-error title selection |
| `path` | Authoring location, e.g. `nodes[id=X].params.field` |
| `node_type` | Node type context |
| `similar_names` | Suggested matches; producer limits to five |
| `available_fields`, `available_fields_total` | Available values and full count |
| `available_fields_label` | Explicit noun such as outputs/inputs; omission becomes generic “fields” |
| `template` | Reference carried to structured consumers |

Do not populate keys that trigger another subsystem's blocks: compiler `phase`,
runtime `exception_type`, HTTP `raw_response`, MCP `mcp_error`, parser `line`, or
shell `shell_command`/`shell_stdout`/`shell_stderr`. The shell block checks key
presence: even `shell_command=None` triggers it.

Ordinary WARNING/INFO output is compact, but context is **not universally ignored**.
`_format_warning_or_info_diagnostic` renders template-error warnings with
`unresolved_references` structurally and cache warnings from selected context.
Check that dispatch before relying on a context field to appear in text; do not
flatten rich template diagnostics into canned message/suggestion strings.

## Views over one parse, paths, and type boundaries

`core/templates.py::parse()` is the one tokenizer; every check here is a view
over it. Root, forward-reference and unused-input accounting read the dependency
view; type passes read the value view (`core/CLAUDE.md` → **Template language**).

Paths are walked as `parse_path` segments, never `str.split('.')` (dots inside
a dynamic index are not separators). An index — `[N]` or `[${…}]` — descends
by `utils.descend_index` in both Pass 5 and `infer_template_type`: batch
`items` or a list field's `structure` is the element; `any` indexes to an
unknown element; a string indexes only as a JSON array at runtime (WARNING).

Shell validation rejects dict/list interpolation in `command` unless the
quoted-template opt-in (`'${var}'`) is present. This is JSON-coercion/type-check
behavior, not a general shell-injection safety guarantee.

Type compatibility is `core/templates.is_type_compatible` (template flow, not a
literal-value check): string → dict/list is allowed because runtime parses JSON
containers, string → numeric/bool is not; a source union needs every member to
fit, a target union any. Parameterized collections compare outer types only.
