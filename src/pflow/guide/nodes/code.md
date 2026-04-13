# Code Node

**Use for**: Data transformation — filter, reshape, merge, compute, string parsing.

**Not for extraction** — templates handle path traversal (`${node.result.data.field}`). Use code only when you need to compute or reshape.

- Receives native objects from upstream nodes (no serialization needed)
- Supports multiple inputs from different nodes
- Type-annotated Python code for clarity and validation

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
- Upstream JSON is auto-parsed before your code runs — if source is JSON, declare `dict`/`list` not `str`
- Use `object` as type when you don't know the type (skips validation)
- Single output via `result` variable — use dict for structured output
- Downstream access: `${node.result}` or `${node.result.field}` for dict results

