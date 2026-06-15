# Code Node

**Use for**: Data transformation — filter, reshape, merge, compute, string parsing.

**Not for extraction** — templates handle path traversal (`${node.result.data.field}`). Use code only when you need to compute or reshape.

- Receives native objects from upstream nodes (no serialization needed)
- Supports multiple inputs from different nodes
- Type-annotated Python code for clarity and validation
- **Caching**: code nodes don't cache by default — safe inside iteration loops where they read state mutated between runs. Add `cache: true` only for a pure, expensive transform fully determined by its declared inputs.

### Node Creation Patterns

```markdown
### filter-and-reshape

Filter active items and reshape for downstream processing.
Templates go in `inputs`, Python code in the code block.
All inputs and result MUST have type annotations.

- type: code
- inputs:
    items: ${fetch-with-auth.response.data.items}

```python code
items: list

result: list = [
    {'id': i['id'], 'name': i['name'], 'value': i['metrics']['value']}
    for i in items
    if i['status'] == 'active'
]
```

### merge-data

Merge and summarize data from two sources.
Downstream nodes access fields: `${merge-data.result.summary}`, `${merge-data.result.count}`.

- type: code
- inputs:
    api_data: ${fetch-with-auth.response.data.items}
    db_records: ${query-db.result}

```python code
api_data: list
db_records: list

merged = api_data + db_records
result: dict = {
    'items': merged,
    'count': len(merged),
    'summary': f'{len(api_data)} from API, {len(db_records)} from DB'
}
```
```

### Code Node Rules

**Code node rules:**
- Templates go in `- inputs:` param, NEVER in the `python code` block (code is literal Python, not a template)
- All inputs and `result` MUST have type annotations: `data: list`, `result: dict = ...`
- Bare vs valued annotations: a top-level **bare** `name: type` (no value) is read as an input declaration and needs a matching `inputs:` entry. An annotated assignment `name: type = value` is a local — so type your intermediates freely (`total: int = sum(...)`). `result`/`next` are the declared output/routing.
- Upstream JSON is auto-parsed before your code runs — if source is JSON, declare `dict`/`list` not `str`
- Use `Any` as the type when you don't want type validation (see syntax table below — auto-injected, no import needed)
- Single output via `result` variable — use dict for structured output
- Downstream access: `${node.result}` or `${node.result.field}` for dict results

## Validate-Time Type Checking

Three code-node input errors are caught at validate time (`pflow
--validate-only`) instead of runtime:

1. **Input bound, annotation missing** — `inputs: {x: ${ref}}` with no `x:
   <type>` in code. The suggestion uses the upstream's declared type when
   known (`Add an annotation (in params.code): x: str  (inferred from ...)`).
2. **Bare annotation declared, no input bound** — a top-level `name: type` with
   no value and no matching `inputs:` entry. (An annotated assignment `name: type
   = value` is a local and is never flagged — issue #331.) The fix depends on
   whether the name is also bound in the body:
   - **bound elsewhere** (a later `helper = ...` or `def helper(): ...`) → the
     bare annotation is redundant, so removing it is safe. Offers both, local
     first: `Remove the annotation 'helper: Any' — 'helper' is assigned in the
     code, so it's a local variable` *or* `add 'helper' to the inputs dict` (if
     it was meant as an input). To keep a type on a local, use the value form
     (`helper: Any = ...`).
   - **read but not bound** (`y: list` + `len(y)`) → removing would leave
     `y` unbound, so the only fix is `Add 'y' to the inputs dict` (or `Rename
     the annotation to 'items'` for a fuzzy-matched typo).
   - **neither read nor bound** → dead annotation: `Remove the annotation
     'y: list' — it is never read in the code`.
3. **Type mismatch** — `x: dict` bound to `${upstream.result}` that declares
   `list`:

    ```text
    Input 'x' expects dict but receives list from ${upstream.result}.

    To fix this:
      1. Change the type annotation (in params.code): x: list
      2. Or change ${upstream.result} to return dict
      3. Or accept any type (in params.code): x: Any
    ```

Suggestions include locality hints (`in params.code` vs `in params.inputs`) so
agents know which section to edit. Upstream type is read from the registry
interface for standard nodes and from the code-block `result:` annotation for
upstream code nodes (including batch code nodes — enrichment flows through
`results[0].result` access paths). Use `Any` when you want to accept any
upstream type deliberately.

### Type annotation syntax

Type annotations in code blocks are Python. pflow follows modern Python style (PEP 585 + PEP 604):

| For... | Write | Example |
|---|---|---|
| Any type (wildcard) | `Any` | `x: Any` |
| Built-in scalars | `str`, `int`, `float`, `bool`, `bytes` | `x: str` |
| List | `list[T]` | `x: list[str]` |
| Dict | `dict[K, V]` | `x: dict[str, int]` |
| Tuple | `tuple[T, ...]` | `x: tuple[int, str]` |
| Set | `set[T]` | `x: set[str]` |
| Union | `A \| B` (pipe syntax) | `x: int \| str` |
| Optional | `Optional[T]` or `T \| None` | `x: str \| None` |

**Auto-injected** (no import needed): `Any`, `Optional`, and the `typing` module.

**Requires** `from typing import X` at the top of your code block: `Literal`, `TypeVar`, `Callable`, `Final`, `ClassVar`, `Iterable`, `Iterator`, `Sequence`, `Mapping`.

**Not allowed**: `List[T]`, `Dict[K, V]`, `Union[A, B]`, and other uppercase typing-module generics — use the modern lowercase / pipe forms above. pflow's NameError suggestions point at the canonical replacement.

Only the outer type is enforced at prep time (e.g. `list[dict]` checks `isinstance(x, list)` but not element types).
