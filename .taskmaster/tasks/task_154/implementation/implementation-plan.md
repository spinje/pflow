# Plan — Type Vocabulary Coherence Refactor

> **For the implementing agent:** this plan is self-contained. Read top to bottom. Every line number, file path, exact string, and decision is provided. You should not need to re-research anything. If you find a genuine discrepancy between this plan and the code, STOP and ask — don't guess.

## TL;DR

**Create**: `src/pflow/core/types.py` (new `TypeSpec` class), `tests/test_core/test_types.py`.

**Edit (code)**: `src/pflow/core/ir_schema.py` (shrink enum, new input-side suggestion routing), `src/pflow/core/exceptions.py` (extend `SchemaValidationError` with structured context fields), `src/pflow/nodes/python/python_code.py` (inject `Any` into exec namespace, reject lowercase `any` with `NonRetriableError`, fix NameError suggestion), `src/pflow/core/param_coercion.py` (add `any` dispatch), `src/pflow/core/markdown_parser.py` (line 147 hint).

**Edit (tests)**: 3 test-fixture files (Python-alias `str`/`int` → canonical), plus removal of 6 now-dead alias tests and addition of ~40 new tests across 4 files.

**Edit (docs)**: 10 files across `src/pflow/guide/`, `src/pflow/mcp_server/resources/instructions/`, `docs/`, `architecture/`.

**Do NOT edit**: `TYPE_COMPATIBILITY_MATRIX`, `_TYPE_ALIASES` dict, registry `Interface:` docstrings, scratchpad probes, runtime template validation hardcoded lists, MCP JSON→Python mapping.

**Atomic**: one PR. Breaking changes on Python aliases and `object` ship together.

---

## 1. Context

### The problem

pflow today has a subtly incoherent type vocabulary across two authoring surfaces:

- **Surface 1 (S1)** — `## Inputs` / `## Outputs` blocks in `.pflow.md` files use a `type:` field.
- **Surface 2 (S2)** — Python code-block annotations (`x: str`, `result: int = ...`).

Three concrete bugs follow from the incoherence (see `scratchpads/type-vocabulary-incoherence/bug-report.md` for full probes):

1. **Dual vocabulary at S1.** The IR schema silently accepts both JSON Schema names (`string`, `number`, `boolean`, `array`, `object`) and Python aliases (`str`, `int`, `integer`, `float`, `bool`, `dict`, `list`). Only the JSON Schema names are documented. This is a 12-name enum doing the work of 6 concepts.
2. **`type: object` is a hidden wildcard.** Probe E confirmed that `type: object` silently accepts strings, lists, ints, dicts — not just dict-shaped values. A type label that looks restrictive but behaves permissively is worse than no label.
3. **`any` is rejected at S1 but `Any` works at S2 only with import ceremony.** The natural wildcard name is illegal at the declaration layer; the Python wildcard requires `from typing import Any` or produces a misleading error (`Add 'Any' to the inputs dict: {"Any": ...}`).

### The intended outcome

- **One S1 vocabulary** — JSON Schema names only, 7 values: `string | number | integer | boolean | array | object | any`.
- **S2 unchanged** — Python annotations, with one addition: `Any` auto-injected into the code exec namespace.
- **Explicit bridge** documented between S1 and S2.
- **`object` means dict-only** (documented and enforced at the vocabulary level; strict runtime rejection of non-dict values is deferred to Task 120).
- **Hard errors on old spellings** with actionable fix suggestions — shipped in one atomic PR.

### Scope boundary (load-bearing)

This PR **does not** touch:

- **Node registry `Interface:` docstrings** — these use Python type names (`str`, `int`, `dict`) as documented Python annotations. They are conceptually closer to S2 than S1, and the convention is enforced only to be lowercase (`tests/test_registry/test_type_string_conventions.py`). This PR leaves them Python-named.
- **Lenient `coerce_workflow_input` behavior** — the function today returns original values on coercion failure rather than raising. This PR only adds an `"any"` passthrough entry. Tightening to strict rejection is Task 120's scope.
- **Complex / nested input schemas** (`properties:`, `required: [...]`) — separate follow-up task.
- **Union syntax at S1** (`string | null`, `int | float`) — deferred. `null` is dropped from the S1 vocabulary for now.

### Decisions previously made (confirmed by polls)

| # | Decision | Source |
|---|---|---|
| 1 | Separate vocabularies: S1 = JSON Schema, S2 = Python | Design discussion + 2 independent reviewers + poll P3 |
| 2 | `any` at S1, `Any` at S2 — semantic match, not character-for-character | Poll P1 unanimous (3/3) |
| 3 | `x: Any` (capitalized) works via namespace injection. Lowercase `x: any` in code blocks is a hard error | Poll P1 unanimous |
| 4 | Also accept `x: typing.Any` (dotted form) | Poll P1 agent 2 |
| 5 | Ship `object` fix + Python alias removal atomically in one PR | Poll P3 unanimous (3/3) |
| 6 | Hard errors with fix suggestions, no deprecation warnings | Poll P3 unanimous |
| 7 | Error for `type: str` must say exactly `"use 'string'"`; for wildcard `dict`, must name `any` as the migration path | Poll P3 explicit ask |
| 8 | `required:` + `default:` stay as separate explicit fields; `default:` present implies optional | Design discussion |
| 9 | Parameterized generics (`dict[str, int]`) rejected at S1 parse time. S2 Python code keeps today's outer-type-only validation | Design discussion |
| 10 | `null` dropped from S1 vocabulary until union syntax lands | Design discussion |
| 11 | No migration helper; manual sed for migrations | Design discussion (O4) |
| 12 | Lenient coercion stays — Task 120 will tighten | Design discussion (O3) |

---

## 2. Target vocabulary

### S1 — `## Inputs` / `## Outputs` `type:` field

Exactly 7 legal values:

```
string | number | integer | boolean | array | object | any
```

**Semantics:**

| S1 type | Accepts |
|---|---|
| `string` | Python `str` |
| `integer` | Python `int` (not `float`) |
| `number` | Python `int` or `float` |
| `boolean` | Python `bool` |
| `array` | Python `list` |
| `object` | Python `dict` only (NOT wildcard) |
| `any` | Any value — the explicit wildcard |

**Rejected (old accepted values):** `str`, `int`, `float`, `bool`, `dict`, `list`. Each produces a hard error naming the canonical replacement.

**Rejected (other):** `null` (deferred), parameterized generics (`list[str]`, `dict[str, int]`, etc.), uppercase variants (`String`, `Int`).

### S2 — Python code-block annotations

Unchanged. Valid Python types. Plus:

- `Any` is auto-injected into the code exec namespace. `from typing import Any` is unnecessary but still works.
- `typing.Any` also works (injected `typing` module continues to exist).
- Lowercase `any` in code blocks is a hard error with a fix suggestion.
- Parameterized generics (e.g., `list[dict]`) continue to work — outer type is enforced, generic params are documentation.

### The S1 ↔ S2 bridge (must be documented in one place)

| S1 (`## Inputs` `type:`) | Python annotation | Notes |
|---|---|---|
| `string` | `str` | |
| `integer` | `int` | Rejects `float` |
| `number` | `int \| float` or `float` | `float` accepts `int` per Python convention |
| `boolean` | `bool` | |
| `array` | `list` | |
| `object` | `dict` | dict only, NOT wildcard |
| `any` | `Any` | auto-injected, no import needed |

Copy-paste-equivalent in meaning; spelling differs because each surface uses its native dialect.

---

## 3. Internal type model — `TypeSpec`

### Location

New file: `src/pflow/core/types.py`

### Motivation

Today the 7 (or 12) strings flow through ~10 fragmented consumer sites, each with its own `if s == "str" or s == "string"` branching. One canonical class will consolidate these, making future changes (e.g., Task 120 strict coercion, union syntax) single-site edits.

### Public API

```python
# src/pflow/core/types.py
from __future__ import annotations
from typing import Any, ClassVar, Final
from dataclasses import dataclass


# Canonical S1 vocabulary
CANONICAL_TYPES: Final[tuple[str, ...]] = (
    "string", "number", "integer", "boolean", "array", "object", "any",
)

# Python aliases that are NO LONGER legal at S1 — map to their canonical replacement
# for producing "use X instead" error messages.
PYTHON_ALIASES_AT_S1: Final[dict[str, str]] = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "dict": "object",  # special: also mention `any` for wildcard intent
    "list": "array",
}


@dataclass(frozen=True)
class TypeSpec:
    """Canonical representation of a pflow S1 type.

    Construct via `TypeSpec.parse(s)`. Exposes a small interface that every
    consumer should use instead of comparing strings.
    """

    name: str  # one of CANONICAL_TYPES

    def __post_init__(self) -> None:
        if self.name not in CANONICAL_TYPES:
            raise ValueError(f"TypeSpec.name must be in {CANONICAL_TYPES}, got {self.name!r}")

    # -- construction --

    @classmethod
    def parse(cls, raw: str) -> "TypeSpec":
        """Parse an S1 type string into a TypeSpec.

        Raises ValueError with a specific, actionable message for:
        - Python aliases (`str`, `int`, `dict`, ...) — "use '{canonical}'"
        - Parameterized generics (`list[str]`, `dict[str, int]`) — "parameterized generics not supported"
        - Unknown types — "did you mean '{closest}'?" using suggestion_utils.find_similar_items
        - Empty / non-string input — "type must be a non-empty string"
        """
        ...

    # -- semantics --

    def accepts(self, value: Any) -> bool:
        """Whether a Python value satisfies this type.

        object → dict only; array → list only; any → True.
        integer → int and NOT bool (matches JSON Schema convention); number → int OR float.
        """
        ...

    def is_wildcard(self) -> bool:
        """True for TypeSpec('any'), False for everything else."""
        ...

    def python_type(self) -> type | tuple[type, ...] | None:
        """Return the Python type(s) this maps to for isinstance-style checks.

        Returns None for `any` (no check).
        Returns a tuple for `number` (int, float).
        Excludes bool from integer (despite Python's `bool issubclass int`).
        """
        ...

    def to_json_schema(self) -> dict[str, str]:
        """Produce a minimal JSON Schema dict: {'type': name} except `any` which returns {}."""
        ...

    def __str__(self) -> str:
        return self.name
```

### Implementation notes

1. **`accepts()` for `integer`**: return `isinstance(value, int) and not isinstance(value, bool)` — Python's `bool` is a subclass of `int`, but JSON Schema treats them as distinct. This matches the convention users expect from "integer."
2. **`accepts()` for `number`**: accept both `int` and `float`, exclude `bool`.
3. **`accepts()` for `object`**: `isinstance(value, dict)`. Deliberately stricter than today's lenient passthrough — but this method is only used by future callers (Task 120). Current lenient `coerce_workflow_input` is unaffected.
4. **`parse()` error detail** — `TypeSpec.parse` raises a typed subclass `TypeVocabularyError(ValueError)` carrying structured fields (see §3.5 below). The message strings are the prose suggestion; the structured fields feed `Diagnostic.context` for JSON/agent consumption:
   - **`raw in PYTHON_ALIASES_AT_S1`**: message `f"Use '{canonical}' instead of '{raw}'"`. For `raw == "dict"` specifically, populate `suggestions_list` with TWO pasteable options (not a single prose string): `["Use 'object' if the value is a dict: - type: object", "Use 'any' if the value can be any type: - type: any"]`. For other aliases, `suggestions_list` has one entry.
   - **`"[" in raw`** (parameterized generic): outer-name mapping rule is load-bearing:
     - If the base name (before `[`) is in `PYTHON_ALIASES_AT_S1`, suggest its canonical replacement (`list[str]` → `"Use 'array'"`, `dict[str, int]` → `"Use 'object'"`).
     - Else if the base name is in `CANONICAL_TYPES`, suggest the base itself (`array[string]` → `"Use 'array'"`).
     - Else: `"Use the base type"`.
     - Full message template: `f"Parameterized generics not supported in `## Inputs` / `## Outputs`. Got: {raw!r}. {recommendation}."`
   - **`raw == "null"`**: **Lead with the fix, not the deferred feature.** Message: `"Use 'any' if the value may be None — it accepts null alongside other values. (Nullable-only types require union syntax, which pflow does not yet support.)"`
   - **Unknown type**: use `find_similar_items(raw, CANONICAL_TYPES, method="fuzzy", cutoff=0.6)`. **Cutoff is 0.6, NOT 0.4** — at a 7-item universe, 0.4 produces false positives (e.g., `pool` ≈ `bool`). 0.6 still catches single-char typos (`strin`→`string` ≈ 0.93). If a match: `similar_names=[closest]`, message `f"Unknown type '{raw}'. Did you mean '{closest}'? Valid types: {', '.join(CANONICAL_TYPES)}"`. Else: `similar_names=[]`, message `f"Unknown type '{raw}'. Valid types: {', '.join(CANONICAL_TYPES)}"`.
   - **Whitespace**: strip leading/trailing silently (common copy-paste artifact). `"  object  "` → `TypeSpec("object")`. Reject INTERNAL whitespace: `"str ing"` raises "Whitespace not allowed inside type names."
   - **Non-string / empty**: explicit `isinstance(raw, str)` check. `parse(None)`, `parse(5)`, `parse("")` raise `"Type must be a non-empty string"`. Do NOT rely on type annotations alone — Python won't enforce at runtime.
5. **Immutability**: `@dataclass(frozen=True)` so `TypeSpec` instances are hashable and can be cached or used as dict keys.

### 3.5 `TypeVocabularyError` — structured error class

Define inside `src/pflow/core/types.py`:

```python
from dataclasses import dataclass, field


@dataclass
class TypeVocabularyError(ValueError):
    """Raised by `TypeSpec.parse` for invalid S1 type strings.

    Carries both prose (for `__str__`) and structured fields (for Diagnostic.context).
    Consumers in `ir_schema._suggest_for_invalid_type` read the structured fields and
    thread them through `SchemaValidationError.__init__` kwargs so they surface in
    `Diagnostic.context`.
    """

    message: str
    offending: str               # the raw input that failed to parse
    similar_names: list[str] = field(default_factory=list)   # fuzzy matches (≤1 for type vocab)
    available_fields: list[str] = field(default_factory=lambda: list(CANONICAL_TYPES))
    available_fields_label: str = "types"
    suggestions_list: list[str] = field(default_factory=list)  # 1-2 pasteable options

    def __str__(self) -> str:
        return self.message
```

**Critical**: the `dict → object/any` case populates `suggestions_list` with TWO entries; the renderer's numbered-list path (`diagnostic_render.py:105-111`) emits them as:

```
To fix this:
  1. Use 'object' if the value is a dict: - type: object
  2. Use 'any' if the value can be any type: - type: any
```

All other cases have one entry in `suggestions_list`.

### Where TypeSpec is used in this PR

- `src/pflow/core/ir_schema.py` — replaces the enum check + `_get_output_suggestion` case 3. Called from `_get_suggestion` (new input-side branch) to extract structured error data and thread it into `SchemaValidationError`.
- `src/pflow/core/exceptions.py` — `SchemaValidationError` gets three new keyword args (see §4.x below) to carry the structured context.
- `tests/test_core/test_types.py` — comprehensive unit tests (see §6).

### Where TypeSpec is NOT used in this PR (deferred)

- `src/pflow/core/param_coercion.py` — **not migrated in this PR.** The `_TYPE_ALIASES` + `_COERCION_DISPATCH` continue to handle runtime coercion. We only add an `"any"` passthrough dispatch entry (see §4.4).
- `src/pflow/runtime/template_validation/type_checker.py` — **not migrated.** The `TYPE_COMPATIBILITY_MATRIX` continues to handle BOTH vocabularies (because the registry Interface side stays Python-named). Future consolidation is a separate refactor.
- `src/pflow/nodes/python/python_code.py` — `_TYPE_MAP` is S2 (Python-named), not affected.

This keeps the PR scope focused on S1. `TypeSpec` is introduced now so Task 120 and future union-type work have a single canonical model to grow from.

---

## 4. Per-file changes

### 4.1 `src/pflow/core/types.py` — NEW FILE

Create the file with the `TypeSpec` class as specified in §3 plus `TypeVocabularyError` per §3.5. This is the single new module this PR adds.

**Imports required:** `from pflow.core.suggestion_utils import find_similar_items` (already-existing utility at `src/pflow/core/suggestion_utils.py:14-74`). Must tolerate circular-import risk — if needed, do the import locally inside `parse()`.

**Public exports:** `TypeSpec`, `TypeVocabularyError`, `CANONICAL_TYPES`, `PYTHON_ALIASES_AT_S1`.

### 4.2 `src/pflow/core/ir_schema.py` — primary enforcement edits

#### 4.2.1 Shrink the `inputs.*.type` enum

**Current** (lines 233-252):

```python
"type": {
    "type": "string",
    "enum": [
        # JSON Schema canonical types
        "string",
        "number",
        "boolean",
        "object",
        "array",
        # Python type aliases
        "str",
        "int",
        "integer",
        "float",
        "bool",
        "dict",
        "list",
    ],
    "description": "Data type hint (accepts JSON Schema or Python type names)",
},
```

**Replace with:**

```python
"type": {
    "type": "string",
    "enum": list(CANONICAL_TYPES),  # imported from pflow.core.types
    "description": "Data type: one of string, number, integer, boolean, array, object, any",
},
```

Add `from pflow.core.types import CANONICAL_TYPES` at the top of the file (near existing imports around line 10-15).

#### 4.2.2 Shrink the `outputs.*.type` enum

**Current** (lines 271-289): identical enum to inputs. Apply the same replacement at lines 271-289.

#### 4.2.3 Rewrite `_get_output_suggestion` case 3

**Current** (lines 402-404):

```python
# Case 3: Invalid type enum value
if error.validator == "enum" and "type" in path_str:
    valid_types = "string, number, boolean, object, array (or Python aliases: str, int, float, bool, dict, list)"
    return f"Type must be one of: {valid_types}"
```

**Replace with:**

```python
# Case 3: Invalid type enum value
if error.validator == "enum" and "type" in path_str:
    return _suggest_for_invalid_type(error.instance)
```

And add a new helper function immediately above `_get_output_suggestion`:

```python
def _suggest_for_invalid_type(offending: Any) -> tuple[str, dict[str, Any]]:
    """Produce an actionable suggestion + structured context for an invalid `type:` enum value.

    Returns (suggestion_text, structured_context_kwargs) tuple. The structured kwargs
    feed `SchemaValidationError`'s new context parameters so `Diagnostic.context`
    carries `similar_names`, `available_fields`, `available_fields_label`, and any
    multi-suggestion list — matching the producers-are-self-describing principle
    documented in `src/pflow/core/CLAUDE.md`.

    Handles three cases:
      1. Python alias (str/int/float/bool/dict/list) → "use '{canonical}' instead of '{alias}'"
         For `dict`, returns TWO suggestions (use 'object' for dict-shaped; use 'any' for wildcard).
      2. Parameterized generic (`list[str]`, `dict[str,int]`, etc.) → maps outer name to canonical
         replacement per §3 note 4.b (`list` → `array`, `dict` → `object`).
      3. Other unknown value → "did you mean '{closest}'?" via fuzzy match (cutoff=0.6).
    """
    from pflow.core.types import TypeSpec, TypeVocabularyError, CANONICAL_TYPES

    # Non-string offending values (unusual — the schema requires a string, but be defensive)
    if not isinstance(offending, str):
        text = f"Type must be one of: {', '.join(CANONICAL_TYPES)}"
        return text, {"available_fields": list(CANONICAL_TYPES), "available_fields_label": "types"}

    try:
        TypeSpec.parse(offending)
    except TypeVocabularyError as exc:
        ctx: dict[str, Any] = {
            "available_fields": exc.available_fields,
            "available_fields_label": exc.available_fields_label,
        }
        if exc.similar_names:
            ctx["similar_names"] = exc.similar_names
        if exc.suggestions_list:
            ctx["suggestions_list"] = exc.suggestions_list
        return str(exc), ctx

    # Should not reach here if jsonschema flagged this as an enum error.
    return (
        f"Type must be one of: {', '.join(CANONICAL_TYPES)}",
        {"available_fields": list(CANONICAL_TYPES), "available_fields_label": "types"},
    )
```

#### 4.2.4 Route input-side enum errors to the suggestion helper

**Current** (lines 420-424 in `_get_suggestion`):

```python
# OUTPUT-SPECIFIC ERROR HANDLING
if "outputs" in path_str:
    return _get_output_suggestion(error, path_str)
```

**Problem:** the input side never reaches `_get_output_suggestion`, so `type: str` in `## Inputs` today returns an empty suggestion. After the enum shrink, this gap becomes user-visible (the "use 'string'" message would never fire for inputs).

**Fix — the routing change has to thread structured context, not just a string**. `_get_suggestion` today returns a single string. After the refactor, the type-vocab branch returns TWO values (the prose suggestion + the structured-context kwargs). Change `_get_suggestion`'s return type to `tuple[str, dict[str, Any]]` and update the call in `validate_ir` to pass both. OR — simpler if the diff is large — have `_get_suggestion` set a module-level `_last_suggestion_context` variable that `validate_ir` reads. Prefer the tuple approach if it's clean.

```python
def _get_suggestion(error: JsonSchemaValidationError) -> tuple[str, dict[str, Any]]:
    """Return (suggestion_string, structured_context_kwargs)."""
    path_str = str(error.absolute_path)

    # TYPE-VOCAB ERROR HANDLING (applies to both inputs and outputs)
    if error.validator == "enum" and "type" in path_str:
        return _suggest_for_invalid_type(error.instance)

    # OUTPUT-SPECIFIC ERROR HANDLING (kept for additionalProperties / type-shape cases)
    if "outputs" in path_str:
        return _get_output_suggestion(error, path_str), {}

    # ...existing branches... wrap each existing return into (msg, {})
```

Then in `validate_ir` at line 515-517:

```python
suggestion, ctx_kwargs = _get_suggestion(error)
raise SchemaValidationError(
    message=error.message,
    path=path,
    suggestion=suggestion,
    **ctx_kwargs,  # NEW — passes similar_names/available_fields/etc.
)
```

This ensures `type: str` in either `## Inputs` or `## Outputs` produces the `"Use 'string' instead of 'str'"` suggestion AND populates `Diagnostic.context` with structured data for JSON consumers.

#### 4.2.5 `SchemaValidationError` — extend with structured context kwargs

**Rationale**: The existing three-string signature (`message`, `path`, `suggestion`) flattens all error signal into prose. Per `src/pflow/core/CLAUDE.md` ("Producers are self-describing") and `src/pflow/runtime/template_validation/CLAUDE.md` ("Every producer builds a `Diagnostic` directly at the call site and populates `context['path']`, `available_fields`, `similar_names`, and `suggestions`"), validators MUST populate structured context keys. The unified renderer (`src/pflow/core/diagnostic_render.py`) consumes `context["similar_names"]` (→ "Did you mean" block), `context["available_fields"]` + `context["available_fields_label"]` (→ "Available types (showing N of M)" block), and `suggestions_list` via the numbered-list path at lines 105-111.

**Edit** `src/pflow/core/exceptions.py` lines 147-183:

```python
class SchemaValidationError(PflowError):
    """Validation error for IR schema with helpful messages and field paths.

    Attributes:
        message: The validation error message
        path: Dotted path to the invalid field (e.g., "nodes[0].type")
        suggestion: Optional suggestion for fixing the error (single-line prose fallback)
        similar_names: Optional fuzzy-match suggestions (renders as "Did you mean")
        available_fields: Optional full list of valid alternatives (renders as "Available X")
        available_fields_label: Optional noun for the alternatives block ("types", "nodes", etc.)
        suggestions_list: Optional multi-suggestion list (renders as numbered list)
    """

    def __init__(
        self,
        message: str,
        path: str = "",
        suggestion: str = "",
        *,
        similar_names: list[str] | None = None,
        available_fields: list[str] | None = None,
        available_fields_label: str | None = None,
        suggestions_list: list[str] | None = None,
    ):
        self.message = message
        self.path = path
        self.suggestion = suggestion
        self.similar_names = similar_names or []
        self.available_fields = available_fields or []
        self.available_fields_label = available_fields_label
        self.suggestions_list = suggestions_list or []

        full_message = "Validation error"
        if path:
            full_message += f" at {path}"
        full_message += f": {message}"
        if suggestion:
            full_message += f"\n{suggestion}"

        super().__init__(full_message)

    def to_diagnostics(self) -> list[Diagnostic]:
        ctx: dict[str, Any] = {"category": "validation"}
        if self.path:
            ctx["path"] = self.path
        if self.similar_names:
            ctx["similar_names"] = self.similar_names
        if self.available_fields:
            ctx["available_fields"] = self.available_fields
        if self.available_fields_label:
            ctx["available_fields_label"] = self.available_fields_label

        # Multi-suggestion list overrides single suggestion string — renderer emits
        # numbered list at diagnostic_render.py:105-111 when suggestions has >1 item.
        if self.suggestions_list:
            suggestions = self.suggestions_list
        elif self.suggestion:
            suggestions = [self.suggestion]
        else:
            suggestions = None

        return [
            Diagnostic(
                severity=Severity.ERROR,
                message=self.message,
                title="Validation Error",
                suggestions=suggestions,
                source="validation",
                context=ctx,
            )
        ]
```

**Backward compat**: all new kwargs are keyword-only with `None` defaults. Existing call sites that use only `(message, path, suggestion)` continue to work unchanged.

### 4.3 `src/pflow/nodes/python/python_code.py` — `Any` auto-injection + error message fix

#### 4.3.1 Inject `Any` into the exec namespace

**Current** (lines 321-325 inside `PythonCodeNode.exec()`):

```python
namespace: dict[str, Any] = {"__builtins__": __builtins__}
namespace["typing"] = _typing_module
namespace["Optional"] = _typing_module.Optional
namespace.update(inputs)
```

**Replace** (insert one line after the `Optional` injection):

```python
namespace: dict[str, Any] = {"__builtins__": __builtins__}
namespace["typing"] = _typing_module
namespace["Optional"] = _typing_module.Optional
namespace["Any"] = _typing_module.Any  # auto-injected so `x: Any` works without import
namespace.update(inputs)
```

One line addition. Mirrors the existing `Optional` precedent.

#### 4.3.2 Reject lowercase `any` in code annotations with a specific message

Add a new helper near `_get_outer_type` (after line 144):

```python
def _check_annotation_vocabulary(annotations: dict[str, str]) -> None:
    """Reject code-block annotations that use lowercase `any` or known-bad forms.

    Fires at prep time to produce a focused, actionable error instead of letting
    Python's exec() raise `TypeError: isinstance() arg 2 must be a type` at runtime
    or a confusing NameError.

    Raises NonRetriableError (not vanilla ValueError) so the engine treats this
    as a deterministic validation rejection rather than a retriable exec-time failure.
    See `src/pflow/nodes/CLAUDE.md` "Use NonRetriableError for validation errors".

    KNOWN LIMITATION: only the outer name after stripping one level of Optional[] is
    checked. Lowercase `any` nested inside a generic (e.g., `list[any]`) is not
    detected here — it will error at exec time via Python's normal NameError path.
    Accepted trade-off: detecting generic params requires recursive parsing and
    the exec-time error is still reached.
    """
    from pflow.nodes.file.exceptions import NonRetriableError  # local import to avoid cycles

    for var_name, annotation in annotations.items():
        # Strip optional wrapper and generic params — we want the base name
        inner = _get_inner_optional_type(annotation) or annotation
        base = inner.split("[")[0].strip()

        if base == "any":
            raise NonRetriableError(
                f"Invalid type annotation for '{var_name}': 'any' (lowercase).\n\n"
                f"Use 'Any' (capitalized) in Python code blocks. "
                f"pflow auto-injects `typing.Any` — no import needed.\n"
                f"  {var_name}: Any\n\n"
                f"Note: lowercase 'any' is the legal spelling in `## Inputs` / `## Outputs` "
                f"sections (e.g., `- type: any`), but Python annotations must use 'Any' (capitalized)."
            )
```

Call this from `PythonCodeNode.prep()` immediately after the existing `_check_input_annotation_syntax` call (current line 274):

```python
self._check_input_annotation_syntax(inputs, annotations)
_check_annotation_vocabulary(annotations)  # NEW — rejects lowercase 'any'
```

#### 4.3.3 Fix the misleading NameError suggestion

**Current** (lines 620-631 in `_format_exec_error`):

```python
if isinstance(exc, NameError):
    var_name = getattr(exc, "name", str(exc))
    msg = f"Undefined variable '{var_name}'"
    if location:
        msg += f"\n{location}"
    msg += (
        f"\n\nSuggestions:\n"
        f'  - Add \'{var_name}\' to the inputs dict: "inputs": {{"{var_name}": ...}}\n'
        f"  - Or define '{var_name}' in the code before use\n"
        f"  - Check for typos in variable names"
    )
    return msg
```

**Replace with** (adds a branch for known typing names, keeps existing behavior for everything else):

```python
if isinstance(exc, NameError):
    var_name = getattr(exc, "name", str(exc))
    msg = f"Undefined variable '{var_name}'"
    if location:
        msg += f"\n{location}"

    # Known typing names that pflow doesn't auto-inject
    _TYPING_NAMES = {
        "Union", "List", "Dict", "Tuple", "Set", "Callable",
        "Literal", "TypeVar", "Iterable", "Iterator", "Sequence",
        "Mapping", "Type", "Final", "ClassVar",
    }
    if var_name in _TYPING_NAMES:
        msg += (
            f"\n\nSuggestions:\n"
            f"  - '{var_name}' is from the typing module. Two options:\n"
            f"      1. Import it: from typing import {var_name}\n"
            f"      2. Use modern syntax (Python 3.10+): `int | None` instead of `Optional[int]`,\n"
            f"         `int | str` instead of `Union[int, str]`.\n"
            f"  - pflow auto-injects 'Any' and 'Optional' — other typing names require explicit import."
        )
    else:
        msg += (
            f"\n\nSuggestions:\n"
            f'  - Add \'{var_name}\' to the inputs dict: "inputs": {{"{var_name}": ...}}\n'
            f"  - Or define '{var_name}' in the code before use\n"
            f"  - Check for typos in variable names"
        )
    return msg
```

Note: post-refactor `Any` is injected, so a `NameError` for `"Any"` won't fire at runtime. The branch is defensive for `Union`/`List`/`Dict`/etc., which pflow does NOT inject (user must import those explicitly). This keeps the PR's new-injection story minimal (`Any` only) while improving the error message for the analogous cases.

#### 4.3.4 Minor: error-message suggestion text in `_check_input_types`

**Current** (lines 593-598):

```python
raise TypeError(
    f"Input '{var_name}' expects {type_str} but received {actual}\n\n"
    f"Suggestions:\n"
    f"  - Change the type annotation to: {var_name}: {actual}\n"
    f"  - Or convert the input value to {type_str}"
)
```

**Add a third suggestion line — INPUT error only** (inputs often arrive with upstream-shape surprises; `Any` is a legitimate escape):

```python
raise TypeError(
    f"Input '{var_name}' expects {type_str} but received {actual}\n\n"
    f"Suggestions:\n"
    f"  - Change the type annotation to: {var_name}: {actual}\n"
    f"  - Or convert the input value to {type_str}\n"
    f"  - Or use `Any` to accept any type: {var_name}: Any"
)
```

**Do NOT add the third line to the result-type mismatch error at lines 408-414.** A `result:` annotation is the author's own intent statement; suggesting `Any` there tells them to defeat their own contract rather than fix the actual mismatch. Keep the result-mismatch error with its original two suggestions.

### 4.4 `src/pflow/core/param_coercion.py` — add `any` passthrough

**Current** (lines 226-233):

```python
_COERCION_DISPATCH = {
    "string": _coerce_to_string,
    "integer": _coerce_to_integer,
    "number": _coerce_to_number,
    "boolean": _coerce_to_boolean,
    "object": _coerce_to_object,
    "array": _coerce_to_array,
}
```

**Add** one entry. **CRITICAL: signature must match the other coercers.** Every other `_coerce_to_*` takes `(value, log_context)` and the dispatcher at line 293 calls `coercer(value, log_context)`. A `(value,)` single-arg signature will raise `TypeError: takes 1 positional argument but 2 were given` on the first `type: any` invocation.

```python
def _coerce_to_any(value: Any, log_context: dict[str, Any]) -> Any:
    """Passthrough coercion for `type: any` — accepts any value unchanged.

    Signature mirrors the other _coerce_to_* functions; log_context is unused
    because `any` is a pure passthrough, but the parameter is REQUIRED by the
    dispatcher's calling convention (param_coercion.py:293).
    """
    return value


_COERCION_DISPATCH = {
    "string": _coerce_to_string,
    "integer": _coerce_to_integer,
    "number": _coerce_to_number,
    "boolean": _coerce_to_boolean,
    "object": _coerce_to_object,
    "array": _coerce_to_array,
    "any": _coerce_to_any,
}
```

Do **NOT** touch `_TYPE_ALIASES` (lines 15-22). **Rationale (corrected from prior draft)**: `_normalize_type()` has exactly one caller today (`coerce_workflow_input` at `param_coercion.py:287`), and post-refactor the IR schema rejects Python aliases so the alias path is mostly unreachable via that call. **Keep it as defense-in-depth** for IR paths that bypass schema validation (programmatically-constructed IR dicts in tests, cached IRs, future MCP entry points that skip the validator). Removing `_TYPE_ALIASES` + `_normalize_type` is a legitimate follow-up cleanup but out of scope here — the goal of THIS PR is breaking vocabulary changes, not dead-code removal. Flag as `# Note: kept for non-S1 entry points; see plan §4.4.` with a short comment in the code.

### 4.5 `src/pflow/runtime/template_validation/type_checker.py` — no changes

Leave `TYPE_COMPATIBILITY_MATRIX` (lines 37-65) as-is. It still has entries under BOTH Python and JSON Schema names, which is correct because:

- S1 (canonical) values flow in from IR `inputs`/`outputs`
- Registry Interface metadata flows in with Python-named types

Both must match compatibly. A future refactor can consolidate when the registry Interface vocabulary is unified, but that's out of scope.

### 4.6 `src/pflow/runtime/template_validation/path_validation.py` — no changes

The hardcoded type-list lines (185, 289-290, 304-340, 326, 334) continue to work because they already handle both vocabularies. Leave as-is.

### 4.7 `src/pflow/runtime/template_validation/type_validation.py` — no changes

`_SHELL_SAFE_TYPES`, `SHELL_BLOCKED_TYPES`, and the scattered type-string checks (lines 31, 126, 157, 162, 219, 231, 233, 274-293) continue to work for the same reason. Leave as-is.

### 4.8 `src/pflow/runtime/engine/template_resolution.py` — no changes

`build_type_cache` and `validate_resolved_type` (lines 29-145) continue to work. Leave as-is.

### 4.9 `src/pflow/mcp/discovery.py` — no changes

`_json_type_to_python` at lines 325-354 stays. Registry continues to use Python names.

### 4.10 `src/pflow/cli/param_parsing.py` — no changes

`infer_type` at lines 9-46 is orthogonal (it infers Python values from CLI strings, not type strings).

### 4.11 `src/pflow/core/markdown_parser.py` — error-hint update (REQUIRED)

**Line 147** — `_SECTION_SYNTAX_HINTS`:

```python
"    - type: str\n"
```

**Change to:**

```python
"    - type: string\n"
```

**This is NOT optional.** `tests/test_core/test_markdown_parser.py:2355` asserts on the hint text (`assert "- type: str" in err.suggestion` today). §5.3 updates that assertion to expect the new hint string. If §4.11 is skipped but §5.3 is applied, the test breaks. Ordering coupling: do §4.11 BEFORE §5.3 test-fixture updates, OR make them atomic.

**Also**: audit other user-facing strings in `markdown_parser.py` for Python-alias leakage. Run:

```bash
grep -nE "type: (str|int|float|bool|dict|list)\b" src/pflow/core/markdown_parser.py
```

Every hit outside of the `_SECTION_SYNTAX_HINTS` block at line 147 is a separate error/hint surface that needs the same canonical-name treatment. Fix each.

---

## 5. Example workflow migrations

Research (Searcher 4) confirmed:

- **All production `.pflow.md` files under `examples/`** already use canonical JSON Schema names at S1. **Zero mechanical migration needed.**
- **The scratchpad probes** at `scratchpads/type-vocabulary-incoherence/repro-files/` deliberately use Python aliases and `object`-as-wildcard. **Do not migrate — they're reference fixtures for the bug being fixed.**
- **One ambiguous file:** `examples/output_validation_demo.pflow.md:43` declares `dynamic_result: type: object` with no `source:` — unclear if it's wildcard or dict. **See migration action below.**

### 5.1 Ambiguous file — `examples/output_validation_demo.pflow.md`

**Action**: change `examples/output_validation_demo.pflow.md:43` from `- type: object` to `- type: any`.

**Rationale**: the output is named `dynamic_result` and has no `source:` declaration. The word "dynamic" in the name + the absence of a concrete source implies the shape is unknown or varies. `any` communicates this intent correctly under the new vocabulary. The runtime behavior is unchanged (output resolver never tries to resolve a `source:`-less declaration).

This is a cosmetic choice — the prior draft's "pick one of three options" instruction was removed to avoid implementer ambiguity.

### 5.2 Scratchpad repro files — do not modify

Files in `scratchpads/type-vocabulary-incoherence/repro-files/` stay as-is. They'll become negative/positive test fixtures after the refactor:

- `A3-input-type-any.pflow.md` (currently rejected) will START PASSING after the refactor. This is deliberate — it's the positive test case.
- `A1-input-type-dict.pflow.md`, `A2-input-type-str.pflow.md` will START FAILING with the new "use 'object'"/"use 'string'" errors. This is the intended behavior.
- `E-object-wildcard.pflow.md` continues to parse with `type: object`, but will behave as "dict-only" semantically (the strict runtime enforcement is Task 120, so today it still accepts non-dict values leniently). The file documents the semantic shift.

### 5.3 Test inline workflow strings — migration inventory

Research surfaced Python-alias usage in 4 test files' inline `.pflow.md` strings (not `.pflow.md` files on disk):

| File | Occurrences | Action |
|---|---|---|
| `tests/test_core/test_markdown_parser.py` lines 460, 468, 2168, 2245, 2275, 2282, 2336, 2355 | `- type: str` in inline markdown | UPDATE to `- type: string` |
| `tests/test_runtime/test_compile_once_regression.py` lines 275, 506, 509 | `- type: str` | UPDATE to `- type: string` |
| `tests/test_integration/test_branch_convergence.py` lines 204, 308 | `- type: int` | UPDATE to `- type: integer` |

**Special case**: `test_markdown_parser.py:2355` currently asserts `assert "- type: str" in err.suggestion`. The suggestion text changes under the refactor — update this assertion accordingly (likely asserting the new canonical message).

These are mechanical `sed`-scale edits. The test behavior (parsing / validation) stays the same; only the fixture type names change.

---

## 6. Tests

### 6.1 New test file — `tests/test_core/test_types.py`

Create this file. Must cover:

**`TestTypeSpecParse`:**
- `test_parse_legal_types` — all 7 canonical types parse and round-trip
- `test_parse_rejects_python_aliases_str` — `TypeSpec.parse("str")` raises, message contains `"Use 'string' instead of 'str'"` (exact substring match)
- Same for `int` → `integer`, `float` → `number`, `bool` → `boolean`, `list` → `array`
- `test_parse_rejects_dict_with_wildcard_hint` — `TypeSpec.parse("dict")` raises, message contains `"Use 'object' instead of 'dict'"` AND `"use 'any'"` (both assertions)
- `test_parse_rejects_parameterized_generics` — `TypeSpec.parse("list[str]")`, `TypeSpec.parse("dict[str, int]")` both raise with `"Parameterized generics not supported"`
- `test_parse_rejects_null` — raises with `"Union types"` hint mentioning `any`
- `test_parse_rejects_unknown_with_fuzzy_suggestion` — `TypeSpec.parse("strin")` raises, message contains `"Did you mean 'string'"`
- `test_parse_rejects_unknown_no_fuzzy_match` — `TypeSpec.parse("zzz")` raises with `"Valid types: ..."` but no "Did you mean"
- `test_parse_rejects_uppercase` — `TypeSpec.parse("String")` raises
- `test_parse_strips_whitespace` — `TypeSpec.parse("  object  ")` succeeds OR raises (decide based on impl — recommend raises; whitespace is a typo signal)

**`TestTypeSpecAccepts`:**
- `test_string_accepts_str_only` — `accepts("x") is True`, `accepts(1) is False`, `accepts({}) is False`, `accepts(None) is False`
- `test_integer_accepts_int_rejects_bool` — `accepts(5) is True`, `accepts(5.5) is False`, `accepts(True) is False`
- `test_number_accepts_int_and_float_rejects_bool` — `accepts(5) is True`, `accepts(5.5) is True`, `accepts(True) is False`
- `test_boolean_accepts_bool_only` — `accepts(True) is True`, `accepts(1) is False`
- `test_object_accepts_dict_only` — `accepts({}) is True`, `accepts([]) is False`, `accepts("x") is False`, `accepts(1) is False`
- `test_array_accepts_list_only` — symmetric
- `test_any_accepts_everything` — dict, list, str, int, bool, float, None all True

**`TestTypeSpecIsWildcard`:**
- `test_any_is_wildcard` — `TypeSpec("any").is_wildcard() is True`
- `test_others_are_not_wildcard` — all 6 others False

**`TestTypeSpecPythonType`:**
- `test_python_type_mapping` — returns `str/int/float/bool/list/dict`. For `any` returns `None`. For `number` returns `(int, float)`. Integer returns `int` (not a tuple).

**`TestTypeSpecToJsonSchema`:**
- `test_simple_types` — `TypeSpec("string").to_json_schema() == {"type": "string"}`
- `test_any_returns_empty_dict` — `TypeSpec("any").to_json_schema() == {}` (matches JSON Schema convention for "any value")

**`TestTypeSpecRoundtrip`:**
- `test_str_roundtrip` — `str(TypeSpec.parse(t)) == t` for all canonical types
- `test_equality_and_hash` — `TypeSpec.parse("object") == TypeSpec.parse("object")`, usable as dict key

**`TestTypeVocabularyError`** — NEW test class for the structured error type:
- `test_structured_fields_on_alias_error` — `TypeSpec.parse("str")` raises `TypeVocabularyError`; asserts `.offending == "str"`, `.available_fields == list(CANONICAL_TYPES)`, `.available_fields_label == "types"`, `.suggestions_list == ["Use 'string' instead of 'str'"]` (exact)
- `test_structured_fields_on_dict_alias_includes_two_suggestions` — `TypeSpec.parse("dict")` raises with `.suggestions_list` exactly equal to:
  ```python
  ["Use 'object' if the value is a dict: - type: object",
   "Use 'any' if the value can be any type: - type: any"]
  ```
- `test_structured_fields_on_fuzzy_match` — `TypeSpec.parse("strin")` raises with `.similar_names == ["string"]`
- `test_structured_fields_on_unknown` — `TypeSpec.parse("foobar")` raises with `.similar_names == []` (no fuzzy match at cutoff=0.6)
- `test_case_sensitive_use_capital_U` — alias-error message contains literal `"Use '"` (capital U) — regression guard for the case-preservation contract from poll P3

**Deferred (do not add in this PR):** union parsing, union acceptance.

### 6.2 `tests/test_core/test_ir_schema.py` changes

**UPDATE** existing tests:

- `TestInputTypeAliases.test_json_schema_types_accepted` (lines 372-380) — SPLIT. Keep the canonical-accepted assertion, extend to include `integer` and `any` as accepted. Add a corresponding `outputs` test.
- `TestInputTypeAliases.test_python_type_aliases_accepted` (lines 382-390) — REMOVE. Replace with tests below.
- `TestInputTypeAliases.test_invalid_type_rejected` (lines 392-401) — UPDATE. Assert the error suggestion contains the new 7-name list (not the old 12).

**ADD** new tests in `TestInputTypeAliases` (or a new `TestInputTypeVocabulary` class):

- `test_str_alias_rejected_with_fix_suggestion` — IR with `type: str` fails `validate_ir`; `SchemaValidationError.suggestion` contains exact `"Use 'string' instead of 'str'"` (case-sensitive assertion)
- Same for `int`, `float`, `bool`, `list`
- `test_dict_alias_rejected_with_wildcard_hint` — `type: dict` raises `SchemaValidationError`; assert `.suggestions_list == [<exact two-entry list>]` (not just substring search) — verify both pasteable options
- `test_any_now_accepted` — IR with `type: any` validates successfully (positive test for the new vocabulary)
- `test_integer_now_accepted_and_bridges_to_int` — IR with `type: integer` validates; and a workflow that passes `type: integer` input to a code node annotated `x: int` runs successfully. This closes the `integer` canonical-name coverage gap.
- `test_null_still_rejected` — IR with `type: null` fails; assert message contains `"Use 'any'"` FIRST (lead with the fix, not the deferred feature)
- `test_parameterized_generic_rejected_list` — IR with `type: list[str]` fails; message contains exact `"Use 'array'"` (not `"Use 'list'"` or `"Use 'the base type'"`)
- `test_parameterized_generic_rejected_dict` — IR with `type: dict[str, int]` fails; message contains exact `"Use 'object'"`
- `test_unknown_type_fuzzy_suggestion` — IR with `type: strin` fails; `.similar_names == ["string"]` via structured field (not just substring)
- `test_unknown_type_no_false_positive_fuzzy` — IR with `type: pool` fails; `.similar_names == []` (0.6 cutoff prevents bool match)
- `test_outputs_apply_same_rules` — all of the above mirrored for `outputs.*.type`
- `test_json_output_contains_structured_context` — run `validate_ir` on `type: str`, call `.to_diagnostics()[0].to_dict()`, assert `context["similar_names"]` / `context["available_fields"] == list(CANONICAL_TYPES)` / `context["available_fields_label"] == "types"` are all populated (verifies the diagnostic pipeline carries structured data, not just prose)

### 6.3 `tests/test_core/test_param_coercion.py` changes

**REMOVE** tests that enshrine the old alias acceptance:
- `test_type_alias_str_works` (line 204)
- `test_type_alias_int_works` (line 242)
- `test_type_alias_float_works` (line 267)
- `test_type_alias_bool_works` (line 301)
- `test_type_alias_dict_works` (line 344)
- `test_type_alias_list_works` (line 382)

**ADD** new tests in a new `TestAnyTypeCoercion` class:
- `test_any_accepts_str_unchanged` — `coerce_workflow_input("hello", "any") == "hello"`
- `test_any_accepts_int_unchanged`
- `test_any_accepts_float_unchanged`
- `test_any_accepts_bool_unchanged`
- `test_any_accepts_dict_unchanged`
- `test_any_accepts_list_unchanged`
- `test_any_accepts_none_unchanged`
- `test_any_accepts_nested_complex` — dict-of-lists-of-dicts passes through unchanged

**KEEP** all other tests (dispatch behavior for canonical types is unchanged).

**NOTE on `coerce_param_for_node`:** The 4 `TestDictToStringCoercion.test_*_when_type_is_str` tests (lines 16-49) and `TestPassthroughBehavior.test_*_when_type_is_str` (lines 91-132) and `TestNonSerializableHandling.*` (lines 138-159) use the string `"str"` — but this function operates at the **node-execution boundary**, not S1. Registry Interface docstrings still use Python names, so `coerce_param_for_node` continues to accept `"str"`. **KEEP these tests unchanged.**

For `TestNoCoercionWhenTypeMatches.test_dict_unchanged_when_type_is_dict` (line 55) and `test_list_unchanged_when_type_is_list` (line 71): these also exercise `coerce_param_for_node`. KEEP unchanged — same rationale.

### 6.4 `tests/test_nodes/test_python/test_python_code.py` changes

**KEEP** all 73 existing tests. The Python-annotation surface is unchanged.

**One possible UPDATE:** `test_unknown_type_annotation_skips_check` (lines 231-245) uses `data: object` precisely because `object` is not in `_TYPE_MAP`. Post-refactor, `object` is still not in `_TYPE_MAP` (which is S2/Python-side). Test behavior unchanged — **KEEP**.

**ADD** new test class `TestAnyAutoInjection`:

- `test_any_without_import_works` — code block `x: Any\nresult: int = len(x)` (with `x="hello"` input) runs successfully without `from typing import Any`
- `test_any_in_result_annotation_works` — `result: Any = {"nested": [1, 2, 3]}` post-check accepts the dict
- `test_typing_Any_dotted_form_works` — `x: typing.Any\nresult: int = 1` succeeds (typing module is already injected)
- `test_any_accepts_all_input_types` — annotation `x: Any` accepts dict, list, str, int, bool, None as input values without raising
- `test_any_union_none_works` — `x: Any | None\nresult: int = 1` runs (tests that `Any | None` in an annotation is parseable)
- `test_explicit_typing_import_still_works` — code that DOES `from typing import Any` continues to work (no double-definition error)
- `test_lowercase_any_rejected` — code block `x: any\nresult: int = 1` raises at prep time; error message contains `"Use 'Any'"` and mentions `## Inputs`
- `test_lowercase_any_in_result_rejected` — `result: any = 1` raises similarly

**ADD** one test to `TestSafetyAndErrors` — regression guard for the `_format_exec_error` fix:

- `test_nameerror_for_typing_symbol_suggests_import` — code `x: Union[int, str]\nresult: int = x` (without `from typing import Union`) raises; error message contains `"from typing import Union"` (not `"Add 'Union' to the inputs dict"`)

### 6.5 `tests/test_registry/test_type_string_conventions.py` — no changes

This file (lines 47-109) enforces the lowercase convention on registry metadata. Registry stays Python-named in this PR. No changes.

### 6.6 `tests/test_runtime/test_template_validation/*` — minimal changes

The compatibility matrix (`test_type_checker.py`, 22 tests) and integration tests (`test_types.py`, 37 tests) continue to use the Python-named fixtures because the **registry** side is still Python-named. **KEEP all tests unchanged** except any that specifically exercise IR `inputs`/`outputs` `type:` values with Python aliases (which would fail schema validation post-refactor). Research found none in these files.

### 6.7 `tests/test_mcp/test_mcp_discovery_critical.py` — no changes

`_json_type_to_python` still maps JSON Schema to Python for the registry. **KEEP.**

### 6.8 Integration test updates

Per §5.3:
- `tests/test_core/test_markdown_parser.py` — 8 fixture updates
- `tests/test_runtime/test_compile_once_regression.py` — 3 fixture updates
- `tests/test_integration/test_branch_convergence.py` — 2 fixture updates

---

## 7. Documentation updates

All doc edits use the new canonical vocabulary. File by file:

### 7.1 `src/pflow/guide/core.md` — CRITICAL

**Line 300** — replace:
```
**Input fields**: `type` (string|number|boolean|array|object), `required` (true|false), `default` (only when required: false), `stdin` (true|false — only one input can have this), description as prose.
```
with:
```
**Input fields**: `type` (string|number|integer|boolean|array|object|any), `required` (true|false), `default` (only when required: false), `stdin` (true|false — only one input can have this), description as prose.
```

**Lines 614-665** ("Parameter Types - Complete Guide" section) — rewrite to include `integer` and `any`; clarify `object` is dict-only, `any` is the explicit wildcard. See plan §2 bridge table for the shape; write one entity per type as in the current format.

**New section** (insert near line 614, before the per-type details): add the S1↔S2 bridge table as documented in §2 above. Header: `### Type Vocabulary — Two Surfaces`.

### 7.2 `src/pflow/guide/nodes/code.md` — CRITICAL

**Lines 59-66** — the rule `"Use `object` as type when you don't know the type (skips validation)"` is WRONG post-refactor. Replace with:
```
- Use `Any` as the type when you don't want type validation (`Any` is auto-injected — no `from typing import Any` needed)
```

### 7.3 `src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md` — CRITICAL

**Line 1006** — same fix as `guide/core.md:300` above (these strings are mirrored across MCP instructions).

**Line 1262+** — extend the "Parameter Types - Complete Guide" section mirroring the updated `guide/core.md`.

### 7.4 `src/pflow/mcp_server/resources/instructions/mcp-sandbox-agent-instructions.md` — CRITICAL

**Line 988** — same fix as above.

### 7.5 `docs/reference/nodes/code.mdx` — CRITICAL

**Lines 41-43** — update the `<Tip>` to recommend `Any` (auto-injected) instead of `object`.

**Lines 45-60** — "Supported types" accordion: replace the `object` row with `Any` row noting auto-injection.

**After line 142** — add a new "Bridge to workflow inputs" section with the S1↔S2 bridge table from §2.

### 7.6 `docs/reference/nodes/claude-code.mdx` — NO CHANGE

Uses Python names (`str/int/bool/list/dict`) in the Claude Code `output_schema` — this is a separate schema surface that uses Python names as a prompt convention (the strings are embedded into LLM prompts via `_build_schema_prompt`). Out of scope.

### 7.7 `docs/changelog.mdx` — ADD NEW ENTRY

Add at the top:

```mdx
<Update label="<MONTH> 2026" description="v0.12.0" tags={["Breaking changes", "Improvements"]}>
  ## Type vocabulary coherence

  The `## Inputs` and `## Outputs` `type:` field now accepts exactly 7 values:
  `string`, `number`, `integer`, `boolean`, `array`, `object`, `any`.

  **Breaking changes:**
  - Python type aliases (`str`, `int`, `float`, `bool`, `dict`, `list`) removed from workflow input/output declarations. Each produces a hard error suggesting the canonical replacement.
  - `object` now documented as dict-only (no longer a hidden wildcard). Use `any` for wildcard.
  - Parameterized generics (`list[str]`, `dict[str, int]`) rejected at parse time.
  - Saved workflows in `~/.pflow/workflows/` containing Python aliases will fail validation on next load or re-save — migrate by editing the saved `.pflow.md` file to use canonical names.

  **New:**
  - `any` explicit wildcard type.
  - `Any` auto-injected into code node exec namespace — no `from typing import Any` needed.
  - Bridge table documenting `## Inputs` ↔ Python annotation mapping in the guide.
</Update>
```

### 7.8 `architecture/reference/ir-schema.md` — UPDATE (EXTENSIVE)

Plan's prior draft listed only lines 83, 322-340, 588-597. Actual scope is larger — **~20 Python-alias S1 examples at lines 63, 68, 98, 103, 135, 140, 148, 153, 228, 235, 241, 275, 281, 287, 293, 331, 332, 335, 354, 355, 358, 359**. Plus 83, 322-340, 588-597 from the prior list. Update every `"type": "str"` / `"type": "int"` / `"type": "dict"` / `"type": "list"` / `"type": "float"` / `"type": "bool"` example that appears under workflow IR `inputs.*.type` or `outputs.*.type` context.

Also add a note distinguishing workflow IR `inputs`/`outputs` (canonical 7 names) from node metadata Interface docstrings (Python names).

**Required audit**: run `grep -nE '"type":\s*"(str|int|float|bool|dict|list)"' architecture/reference/ir-schema.md` and fix every hit where the context is workflow IR (not registry Interface metadata).

### 7.9 `architecture/reference/enhanced-interface-format.md` — UPDATE

**Lines 31-39** — add a cross-reference clarifying: "These type names describe node `Interface:` docstrings and are Python-named. Workflow `## Inputs` / `## Outputs` use a separate canonical vocabulary — see [type vocabulary](../..)."

### 7.10 `architecture/reference/template-variables.md` — UPDATE (was OPTIONAL, now REQUIRED)

**Lines 511-512, 678-683, 986-988** contain `inputs` block examples using Python aliases. These shape agent mental models of the IR format. Update each hit to canonical vocabulary.

**Lines 604-620** (`TYPE_COMPATIBILITY_MATRIX` docs) — add a note explaining the matrix bridges two vocabularies (S1 canonical for workflow inputs; Python for registry Interface metadata).

### 7.11 MCP agent instructions — additional mandatory line edits

Beyond the lines §7.3/§7.4 already list, **two more lines explicitly teach the REMOVED `object == wildcard` behavior**:

- `src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md:836` — `"Use \`object\` as type when you don't know the type (skips validation)"`. **Change to**: `"Use \`Any\` as the type when you don't want type validation — auto-injected into Python code blocks, no import needed."`
- `src/pflow/mcp_server/resources/instructions/mcp-sandbox-agent-instructions.md:822` — same line, same fix.

**Required audit**: run `grep -nE 'object.*wildcard|object.*skip.*validation' src/pflow/mcp_server/resources/instructions/*.md` — every hit must be rewritten.

### 7.12 `docs/CLAUDE.md` — UPDATE

The voice-style guidance section uses as an exemplar sentence: `"Use \`object\` when you don't know the type — it skips validation entirely"`. Post-refactor this advice is wrong. Replace with an exemplar that teaches `Any` in code blocks and `any` in `## Inputs`.

### 7.13 Docs — full sweep

After the targeted edits above, run a final audit across the entire `docs/` and `src/pflow/guide/` and `architecture/` trees:

```bash
grep -rnE "type: (str|int|float|bool|dict|list)\b" \
    docs/ src/pflow/guide/ src/pflow/mcp_server/resources/instructions/ architecture/
grep -rnE '(object.*wildcard|object.*skips? validation|type: null)' \
    docs/ src/pflow/guide/ src/pflow/mcp_server/resources/instructions/ architecture/
```

Every hit in workflow-IR-context examples must be updated. Hits in Claude Code `output_schema` / LLM `output_schema` context are out of scope (§7.6) — verify each hit's context before editing.

---

## 8. Implementation order

The implementer should follow this order to keep each step testable:

1. **Create `src/pflow/core/types.py`** with `TypeSpec` + `TypeVocabularyError`.
2. **Write `tests/test_core/test_types.py`** — make it pass.
3. **Update `src/pflow/core/exceptions.py`** — extend `SchemaValidationError.__init__` with the four new keyword args + update `to_diagnostics()` to populate structured context.
4. **Update `src/pflow/core/ir_schema.py`** — enum shrink + `_suggest_for_invalid_type` (returns tuple) + `_get_suggestion` routing fix + `validate_ir` threading of structured kwargs.
5. **Add/update tests in `tests/test_core/test_ir_schema.py`** — make them pass (including the JSON-output structured-context test).
6. **Update `src/pflow/nodes/python/python_code.py`** — `Any` injection + `_check_annotation_vocabulary` with `NonRetriableError` + NameError-branch fix with expanded `_TYPING_NAMES` + input-only third-line `Any` suggestion.
7. **Add/update tests in `tests/test_nodes/test_python/test_python_code.py`** — make them pass.
8. **Update `src/pflow/core/param_coercion.py`** — add `any` dispatch entry with correct `(value, log_context)` signature + add the code comment citing this plan §4.4.
9. **Add tests in `tests/test_core/test_param_coercion.py`**; remove the 6 alias tests; add one test pinning `_normalize_type` behavior so it isn't accidentally removed in a future cleanup.
10. **Update `src/pflow/core/markdown_parser.py:147`** + audit other hints — REQUIRED step (was optional).
11. **Fix test fixtures** per §5.3 (3 test files).
12. **Migrate AMBIGUOUS example** per §5.1 (1 file).
13. **Run full test suite** — `make test`. Expect all to pass.
14. **Run type checker** — `make check`.
15. **Doc updates** per §7 (including the doc files that were missing from the prior draft: `architecture/reference/template-variables.md`, `docs/CLAUDE.md`, MCP instruction lines 836/822).
16. **Final doc sweep grep** per §7.13 — catch stragglers.
17. **Manual verification** per §10 below.
18. **Bug-report post-fix appendix** — update `scratchpads/type-vocabulary-incoherence/bug-report.md` per §10.2.

---

## 9. Critical files to modify (summary)

**Code:**
- `src/pflow/core/types.py` — NEW FILE (`TypeSpec` + `TypeVocabularyError`)
- `src/pflow/core/ir_schema.py` — enum + suggestion logic + `_get_suggestion` returns tuple
- `src/pflow/core/exceptions.py` — `SchemaValidationError` new kwargs + `to_diagnostics` context population
- `src/pflow/nodes/python/python_code.py` — Any injection + lowercase-any rejection with `NonRetriableError` + NameError fix + expanded `_TYPING_NAMES`
- `src/pflow/core/param_coercion.py` — add `any` dispatch with correct `(value, log_context)` signature
- `src/pflow/core/markdown_parser.py` — line 147 (required, not optional) + audit grep for other Python-alias hints

**Tests:**
- `tests/test_core/test_types.py` — NEW FILE
- `tests/test_core/test_ir_schema.py` — update + add
- `tests/test_nodes/test_python/test_python_code.py` — add `TestAnyAutoInjection`
- `tests/test_core/test_param_coercion.py` — remove 6 alias tests, add `TestAnyTypeCoercion`
- `tests/test_core/test_markdown_parser.py` — fixture `str` → `string` (8 locations)
- `tests/test_runtime/test_compile_once_regression.py` — fixture `str` → `string` (3 locations)
- `tests/test_integration/test_branch_convergence.py` — fixture `int` → `integer` (2 locations)

**Examples:**
- `examples/output_validation_demo.pflow.md` — line 43: classify and migrate the ambiguous `dynamic_result`

**Docs:**
- `src/pflow/guide/core.md` — vocabulary + bridge table
- `src/pflow/guide/nodes/code.md` — `object` → `Any` recommendation
- `src/pflow/mcp_server/resources/instructions/mcp-agent-instructions.md` — lines 836, 1006, 1262+
- `src/pflow/mcp_server/resources/instructions/mcp-sandbox-agent-instructions.md` — lines 822, 988, 1244+
- `docs/reference/nodes/code.mdx` — Tip + Supported types + new Bridge section
- `docs/changelog.mdx` — new entry (includes saved-workflow migration note)
- `docs/CLAUDE.md` — voice-style exemplar sentence no longer teaches `object == wildcard`
- `architecture/reference/ir-schema.md` — ~20 example updates across lines 63-359 plus 588-597
- `architecture/reference/enhanced-interface-format.md` — cross-reference note distinguishing S1 / S2 / S3 (registry)
- `architecture/reference/template-variables.md` — lines 511-512, 678-683, 986-988 (was OPTIONAL, now REQUIRED)
- Final full-tree grep sweep per §7.13

**NOT changed (explicit):**
- `src/pflow/runtime/template_validation/type_checker.py` (compatibility matrix — already includes both vocabularies, including `integer` row at line 56)
- `src/pflow/runtime/template_validation/path_validation.py` (hardcoded lists unchanged)
- `src/pflow/runtime/template_validation/type_validation.py` (shell safety lists unchanged)
- `src/pflow/runtime/engine/template_resolution.py` (runtime validator unchanged — Task 120 will tighten)
- `src/pflow/mcp/discovery.py` (registry conversion unchanged)
- `src/pflow/cli/param_parsing.py` (CLI inference unchanged)
- `src/pflow/nodes/claude/claude_code.py` (`output_schema` keeps Python names — intentional third dialect, see §11.8)
- `src/pflow/nodes/llm/llm.py` (`output_schema` passes through as opaque dict — JSON Schema native)
- `tests/test_registry/test_type_string_conventions.py` (registry vocabulary unchanged)
- `scratchpads/type-vocabulary-incoherence/repro-files/*` (bug reproducers preserved; `bug-report.md` gets a post-fix appendix per §10.2)

---

## 10. Verification

### 10.1 Automated gates

1. `make test` — full test suite passes.
2. `make check` — type checker and linter pass.
3. Specifically confirm these tests pass:
   - `tests/test_core/test_types.py` — all new `TypeSpec` tests
   - `tests/test_core/test_ir_schema.py::TestInputTypeVocabulary` — new vocabulary rejection tests
   - `tests/test_nodes/test_python/test_python_code.py::TestAnyAutoInjection` — new `Any` injection tests

### 10.2 Probe-based manual verification

From `scratchpads/type-vocabulary-incoherence/repro-files/`, run each probe and confirm the expected post-refactor behavior:

```bash
cd scratchpads/type-vocabulary-incoherence/repro-files/

# Should now SUCCEED (was failing before):
uv run pflow ./A3-input-type-any.pflow.md x=hello --validate-only

# Should now FAIL with "Use 'object' instead of 'dict'" AND numbered list containing 'any':
uv run pflow ./A1-input-type-dict.pflow.md x='{"a":1}' --validate-only

# Should now FAIL with "Use 'string' instead of 'str'":
uv run pflow ./A2-input-type-str.pflow.md x=hello --validate-only

# Should now SUCCEED without `from typing import Any` (B2 probe):
uv run pflow ./B2-annot-Any.pflow.md x='{"a":1}'

# Should still pass — lenient coercion unchanged (Task 120 will tighten):
uv run pflow ./E-object-wildcard.pflow.md x=hello
```

**Positive probe for `integer`** (add a new file under `/tmp/` for this test — not a repro file):

```bash
cat >/tmp/int-bridge.pflow.md <<'EOF'
# int-bridge
## Inputs
### count
Count.
- type: integer
- required: true
## Steps
### c
Count.
- type: code
- inputs:
    n: ${count}

```python code
n: int
result: int = n * 2
```
EOF
uv run pflow /tmp/int-bridge.pflow.md count=5
# Expected: exits 0, result=10. Tests the integer→int bridge through TYPE_COMPATIBILITY_MATRIX.
```

**Post-refactor bug-report update**: after verification passes, append a short "Post-fix behavior" section to `scratchpads/type-vocabulary-incoherence/bug-report.md` documenting the new expected outputs for each probe (so future readers see both the bug AND the fix captured in the same file).

### 10.3 Error-message wording spot-checks

Write these tiny probes and confirm the exact error substrings are present. **Use case-sensitive `grep` (no `-i` flag) to catch accidental case regressions in "Use" capitalization.**

```bash
# "Use 'string' instead of 'str'" — EXACT case
cat >/tmp/p1.pflow.md <<'EOF'
# p1
## Inputs
### x
Input.
- type: str
- required: true
## Steps
### e
Echo.
- type: shell
- cmd: echo
EOF
uv run pflow /tmp/p1.pflow.md --validate-only 2>&1 | grep "Use 'string'"

# "Use 'object' if the value is a dict" AND "Use 'any' if the value can be any type"
cat >/tmp/p2.pflow.md <<'EOF'
# p2
## Inputs
### x
Input.
- type: dict
- required: true
## Steps
### e
Echo.
- type: shell
- cmd: echo
EOF
uv run pflow /tmp/p2.pflow.md --validate-only 2>&1 | grep "Use 'object' if the value is a dict"
uv run pflow /tmp/p2.pflow.md --validate-only 2>&1 | grep "Use 'any' if the value can be any type"

# "Did you mean 'string'" (fuzzy match on 'strin')
cat >/tmp/p3.pflow.md <<'EOF'
# p3
## Inputs
### x
Input.
- type: strin
- required: true
## Steps
### e
Echo.
- type: shell
- cmd: echo
EOF
uv run pflow /tmp/p3.pflow.md --validate-only 2>&1 | grep "Did you mean 'string'"

# "Parameterized generics not supported" AND "Use 'array'" (canonical replacement, not 'list')
cat >/tmp/p4.pflow.md <<'EOF'
# p4
## Inputs
### x
Input.
- type: list[str]
- required: true
## Steps
### e
Echo.
- type: shell
- cmd: echo
EOF
uv run pflow /tmp/p4.pflow.md --validate-only 2>&1 | grep "Parameterized generics not supported"
uv run pflow /tmp/p4.pflow.md --validate-only 2>&1 | grep "Use 'array'"

# Outputs-side symmetry — same error pathway as inputs
cat >/tmp/p5.pflow.md <<'EOF'
# p5
## Inputs
### x
Input.
- type: string
- required: true
## Steps
### e
Echo.
- type: shell
- cmd: echo ${x}
## Outputs
### result
Result.
- type: str
- source: ${e.stdout}
EOF
uv run pflow /tmp/p5.pflow.md --validate-only 2>&1 | grep "Use 'string'"

# JSON output — structured context populated, not just prose
uv run pflow /tmp/p1.pflow.md --validate-only --output-format json 2>&1 | \
    python -c "import json,sys; d=json.loads(sys.stdin.read()); assert any('similar' in str(e).lower() or 'available_fields' in str(e).lower() for e in d.get('diagnostics', [])), 'structured context missing'"
```

All greps should return non-empty. If any are empty, the corresponding `_suggest_for_invalid_type` branch has wrong wording — fix it. The JSON check validates that `Diagnostic.context` carries structured fields (not just the prose suggestion).

### 10.4 `Any` injection in code blocks

```bash
cat >/tmp/any-code.pflow.md <<'EOF'
# any-code
## Inputs
### x
Input.
- type: any
- required: true
## Steps
### process
Process.
- type: code
- inputs:
    x: ${x}

```python code
x: Any
result: str = str(type(x).__name__)
```

## Outputs
### result
Result.
- source: ${process.result}
EOF
uv run pflow /tmp/any-code.pflow.md x='{"nested":[1,2,3]}'
# Expected: exits 0, output contains `dict`
```

### 10.5 Lowercase `any` in code block

```bash
cat >/tmp/lower-any.pflow.md <<'EOF'
# lower-any
## Inputs
### x
Input.
- type: any
- required: true
## Steps
### process
Process.
- type: code
- inputs:
    x: ${x}

```python code
x: any
result: str = "ok"
```

## Outputs
### result
Result.
- source: ${process.result}
EOF
uv run pflow /tmp/lower-any.pflow.md x=hello 2>&1 | grep -i "Use 'Any'"
# Expected: grep returns a line
```

### 10.6 Regression spot check — old behavior still working

```bash
# Existing canonical workflow should still run:
uv run pflow examples/test_llm_templates.pflow.md --validate-only
# Expected: exits 0, no errors.
# Note: this file uses `type: object` for its `llm_usage` output at line 58 —
# runtime value is an actual dict, so `object` is semantically correct; no migration needed.

# Probe that uses `type: object` with a dict (B1) should still succeed — lenient coercion untouched:
uv run pflow scratchpads/type-vocabulary-incoherence/repro-files/B1-annot-dict.pflow.md x='{"a":1}'
# Expected: exits 0.

# Claude Code output_schema examples — separate surface (Python names in LLM prompts, not IR).
# Plan §7.6 says NO CHANGE to claude-code.mdx because the output_schema vocabulary is intentionally
# a third dialect (Python names embedded into LLM prompts via _build_schema_prompt). Verify the
# example files parse and validate without schema errors:
uv run pflow examples/nodes/claude-code/claude-code-schema.pflow.md --validate-only
# Expected: exits 0. The `type: str`/`int`/`list` inside the fenced `yaml output_schema` block
# is a node param value (opaque dict), NOT a workflow-level ## Outputs `type:` declaration —
# the IR schema enum shrink does not affect it.
```

### 10.7 Documentation spot-check

- Run `uv run pflow guide core | grep -iE "any|integer"` — should show the new types listed.
- Run `uv run pflow guide code | grep -iE "Any|auto-inject"` — should mention auto-injection.

---

## 11. Known quirks and edge cases

1. **`additionalProperties: false` on input/output schema** means unknown fields (`- wildcard: true`) produce a different error than unknown type values. Existing suggestion logic for `additionalProperties` (`_get_output_suggestion` case 1, lines 356-388) is unrelated and unchanged.
2. **`_TYPE_ALIASES` in `param_coercion.py` stays as defense-in-depth** — kept for IR paths that bypass schema validation (programmatically-constructed IR dicts in tests, cached IRs, future MCP entry points). Post-refactor the alias path is mostly unreachable via normal S1 flow, but removing it is a separate cleanup.
3. **`coerce_param_for_node` accepts `"str"`** — this is the node-execution boundary where registry Interface (Python-named) meets actual values. Leave unchanged. Registry Interface vocabulary is **NOT** in scope for this PR.
4. **`test_type_string_conventions.test_type_convention_examples` (line 80-104)** lists Python names (`str`, `int`, `list[str]`, etc.) as valid registry types. **Don't change it** — it codifies the node Interface convention which stays Python-named.
5. **Parameterized generics in Python code blocks** continue to work as today (outer-type-only validation). The "rejected at parse time" rule applies ONLY to S1 IR schema parsing, not to Python AST parsing of code blocks.
6. **The `Any | None` annotation form** must still work in code blocks (it's valid Python 3.10+ syntax). The `_is_optional_type` / `_get_inner_optional_type` helpers handle this — no changes needed.
7. **`Optional[Any]`** also must still work. Same helpers handle it.
8. **Three type vocabularies coexist post-refactor** — this is intentional and documented:
   - **S1** (workflow IR `inputs`/`outputs`): canonical 7 names — `string | number | integer | boolean | array | object | any`
   - **S2** (Python code-block annotations): Python types, `Any` auto-injected
   - **S3** (node registry `Interface:` docstrings and Claude Code `output_schema`): Python names (`str`, `int`, `dict`, ...) — intentionally unchanged because S3 feeds LLM prompt construction (`_build_schema_prompt`) and registry metadata whose authors are Python library writers. The S1↔S2 bridge table is documented; the S3 vocabulary is a third dialect that's kept stable because it has different consumers.
9. **Lowercase `any` inside parameterized generics** (e.g., `list[any]`) is NOT caught by `_check_annotation_vocabulary` — the helper only inspects the outer name. It will surface as a `NameError` at exec time via the normal Python path. Accepted trade-off; documented in the helper's docstring.
10. **Saved workflows containing Python aliases** (at `~/.pflow/workflows/*/`) will fail validation on next load or `--force` re-save. Migration is manual: edit the saved `.pflow.md` to use canonical names. Changelog entry captures this.
11. **`TypeSpec.accepts()` uses strict JSON-Schema-style semantics** (e.g., `TypeSpec("integer").accepts(True) is False`, even though Python's `bool` is a subclass of `int`). This diverges from `python_code._TYPE_MAP`'s Python-permissive rules (`_TYPE_MAP["int"] == int` accepts `True`). No caller uses `accepts()` in this PR (it's for Task 120), but future callers should know the two semantics exist side by side. Document in `TypeSpec.accepts()`'s docstring.

---

## 12. Out of scope — things the implementer must NOT do

- Do NOT modify `TYPE_COMPATIBILITY_MATRIX` in `type_checker.py`.
- Do NOT modify `_TYPE_ALIASES` in `param_coercion.py`.
- Do NOT change `coerce_workflow_input` to raise on non-matching types (that's Task 120).
- Do NOT change registry Interface docstrings (stay Python-named).
- Do NOT remove `_TYPE_MAP` entries in `python_code.py`.
- Do NOT add complex/nested schema syntax (`properties:`, `required: [...]`) — separate task.
- Do NOT add union type syntax (`string | null`) — separate task.
- Do NOT migrate `scratchpads/type-vocabulary-incoherence/repro-files/*`.

---

## 13. Rationale notes for future readers

**Why separate S1 and S2 vocabularies?** S1 is an external contract; external consumers (CLI users, MCP clients, non-Python tooling) shouldn't need Python context. S2 must be Python because the runtime is Python. They serve different purposes, so they use different dialects. An explicit bridge keeps both surfaces clean.

**Why `object` → dict and `any` → wildcard instead of keeping `object` as wildcard?** A type label that looks restrictive but behaves permissively is worse than no label. Author predictability trumps implementation convenience.

**Why ship both `object` fix and alias removal in one PR?** Two breaks in one release = one migration. Spread across releases = a confused intermediate state. No external users means no backward-compat debt.

**Why hard errors not deprecation warnings?** Agents ignore warnings until they become errors. The confusing intermediate state ("works but will break") is a worse cost than the focused "here's the fix" error.

**Why `Any` auto-injected and lowercase `any` rejected?** Python code should BE Python. Each surface speaks its native dialect. But `from typing import Any` ceremony is pure tax; injecting `Any` (like `Optional` is already injected) removes the tax without leaking `typing` knowledge into workflow authoring.

**Why skip `null` for now?** Nullability is semantically distinct from absence — absence is `required: false` + no `default:`; nullability is a value-level concern. Handling null without union syntax collapses these. Add when union syntax lands.

---

_End of plan._
