# Template Validation Package

`validate_workflow_templates` checks templates before execution. Its production
caller is `core/workflow/validator.py::WorkflowValidator`; compilation imports
`extract_node_outputs` but does not run these passes.

## Find the check

| Symptom or change | Owner |
|---|---|
| Malformed template, unused input, loop condition | `validator.py` |
| Missing node output/path, diagnostic field suggestions | `path_validation.py` |
| Parameter type, shell JSON coercion, code-input annotation | `type_validation.py` |
| `${item.field}` against inferred item structure | `batch_item_validation.py` |
| Type compatibility/inference | `type_checker.py` |
| Nesting-aware path split or safe diagnostic display | `utils.py::split_template_path`, `sanitize_for_display` |
| Output metadata or child workflow output discovery | `validator.py::extract_node_outputs`, `_resolve_child_workflow_outputs` |
| Paths shown by node-output formatters | `utils.py::flatten_output_structure` |

Malformed syntax returns early before semantic template checks. Unknown node
types are deliberately skipped by `_register_node_outputs_from_registry`:
the outer workflow validator owns their diagnostic. Raising here replaces a
useful unknown-type error with a validator exception.

## Keep extraction purposes separate

- `_extract_all_templates` counts non-literal references, including coalesce
  operands, for unused-input detection.
- `_field_checkable_templates` excludes multi-operand `??` chains: missing fields
  are legitimate fallthrough at runtime. `core/workflow/data_flow.py` still checks
  their roots. A bare `${node.field}` remains fully field-checked for typos.
- `_extract_cache_templates_for_unused_check` joins only unused-input accounting.
  Cache-var resolution belongs to `core/workflow/data_flow.py::_validate_cache_block`; feeding
  those vars to path validation produces two diagnostics for one mistake.
- Literal operands are not references. `_LITERAL_PATTERN` and
  `TemplateResolver.is_literal_operand` must stay aligned with runtime JSON
  parsing and coalesce splitting; otherwise validation can accept a value that
  runtime leaves unresolved.

## Output metadata and limits

`extract_node_outputs` builds the metadata consumed by the passes and compiler.
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

## Regex, path, and type boundaries

Three patterns have different jobs; do not unify them just because they all find
`${...}` syntax:

| Pattern | Owner/purpose | Important distinction |
|---|---|---|
| `_PERMISSIVE_PATTERN` | `validator.py`, validation discovery | Sees nested bracket templates; no dollar-escape lookbehind |
| `TEMPLATE_PATTERN` | `TemplateResolver`, runtime resolution | Strict operand grammar and dollar-escape guard |
| `TEMPLATE_EXTRACT_PATTERN` | `TemplateResolver`, diagnostic/data-flow discovery | Broad extraction; downstream checks decide validity |

Path checks use the permissive field-checkable set. Type/shell passes use
`TemplateResolver.extract_variables`: for nested bracket templates they see the
inner variable, not the complete outer reference. This is a type-checking
limitation, not evidence that the outer value is safe. Use `split_template_path`,
never `str.split('.')`, which splits dots inside nested expressions.

Shell validation rejects dict/list interpolation in `command` unless the
quoted-template opt-in (`'${var}'`) is present. This is JSON-coercion/type-check
behavior, not a general shell-injection safety guarantee.

`type_checker.is_type_compatible` permits string → dict/list because runtime can
parse JSON containers, but not string → primitive numeric/bool conversion.
Source unions require every member to fit; target unions accept any matching
member. Parameterized collections compare outer types only; element types are
not checked.
