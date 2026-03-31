# Task 142: Explore Function-Based Code Node Syntax

## Description

Explore replacing the current two-zone code node syntax (YAML inputs + Python code block) with a function-based syntax that eliminates the separate inputs block entirely.

## Status
not started

## Priority
low

## Type
exploratory

## Problem

The current code node has two syntax zones that look similar but mean different things:

**YAML inputs** (data binding):
```yaml
- inputs:
    text: ${fetch-data.stdout}
```

**Python code block** (type declarations + logic):
```python
text: str
result: str = text.upper()
```

This causes confusion (issue #148): users naturally write `text: str = ${fetch-data.stdout}` in YAML inputs, mirroring the code block syntax. YAML silently treats this as the string value `"str = <resolved>"`, corrupting data with no error.

A bug fix (#148) now catches this specific mistake. But the root cause is the two-zone design itself.

## Key Insight

The current code block is **not runnable Python in isolation**. It's syntactically valid Python (passes `ast.parse()`), but:
- `text: str` is an annotation with no value — `NameError` if run directly
- Variables only get values because the code node injects them into the `exec()` namespace
- The "pure Python" property buys AST parsing for annotation extraction — nothing else

Since the code isn't standalone anyway, the argument against changing the syntax is weak.

## Potential Direction: Function Syntax

A function-based code block would be genuinely standalone and testable:

```python
def transform(text: str, count: int) -> str:
    return text.upper()[:count]
```

- The function signature declares inputs AND types in one place
- No separate inputs block needed — template bindings come from parameter names
- Return type replaces `result: <type> = ...`
- The function is genuine, runnable, testable Python
- IDE support (autocomplete, type checking) works naturally

### Template Binding

The engine would bind template values to function parameters by name. Two approaches to explore:

**Approach A — Implicit binding (convention over configuration):**
Parameters auto-bind to `${node-name.field}` based on the execution graph. Only need explicit inputs for non-obvious bindings.

**Approach B — Explicit binding via YAML (like today, but inputs are just parameter values):**
```yaml
- inputs:
    text: ${fetch-data.stdout}
    count: 10
```
The inputs block maps to function parameters. Type confusion impossible because the function signature is the only place types appear.

## Open Questions

1. **Backwards compatibility**: How to migrate existing code nodes? Deprecation period? Can both syntaxes coexist?
2. **Multi-statement logic**: Functions handle this naturally (multiple lines in function body). Is there any loss compared to the current flat exec() approach?
3. **Dynamic routing**: Current `next: str = "target"` pattern — how does this map to a function return? Maybe `return ("target", result)` or a routing decorator?
4. **Multiple return values**: Current pattern only has `result`. Functions could return dicts naturally. Impact on downstream template resolution?
5. **Side effects**: Current code can `print()` and it's captured. Functions could too, but is this the right pattern?
6. **`exec()` vs function call**: Current impl uses `exec()`. A function-based approach could use `exec()` to define the function, then call it. Or parse the function with AST and call directly.

## What This Task Is NOT

- Not a commitment to implement this change
- Not a design spec — the questions above are genuinely open
- Not blocking any other work (#148 bug fix handles the immediate problem)

## Dependencies

- Issue #148 (bug fix) — done, provides the immediate safety net
- Task 104 (original code node implementation) — context on design decisions

## Next Steps

1. Prototype the function syntax in a scratchpad
2. Test with realistic workflows to see if the ergonomics work
3. Identify migration path from current syntax
4. Decide whether this is worth the breaking change
