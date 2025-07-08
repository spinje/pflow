# Task 16: Planning Context Builder - Quick Reference

## Critical Integration Points

### Input (from Task 7)
```python
metadata = {
    'description': 'Get GitHub issue',
    'inputs': ['issue_number', 'repo'],
    'outputs': ['issue'],
    'params': ['token'],
    'actions': ['default', 'not_found']
}
```

### Output (for Task 17)
```markdown
**github-get-issue**: Get GitHub issue
- Reads: shared["issue_number"], shared["repo"]
- Writes: shared["issue"]
- Actions: default, not_found
```

## Key Implementation Decisions

### 1. Format: Markdown over JSON
- LLMs reason better with structured text
- More token-efficient
- Easier to read/debug

### 2. Focus: Interfaces over Parameters
- Emphasize inputs/outputs (data flow)
- De-emphasize params (configuration)
- This is what the planner needs most

### 3. Organization: Categories
```
File Operations
├── read-file
├── write-file
└── copy-file

GitHub Operations
├── github-get-issue
├── github-create-pr
└── github-list-prs
```

### 4. Key Naming Patterns
Emphasize these natural patterns:
- File ops: `file_path`, `content`, `encoding`
- GitHub ops: `repo`, `issue`, `pr`
- Git ops: `branch`, `message`, `commit_hash`
- LLM ops: `prompt`, `response`

## Implementation Checklist

- [ ] Create `src/pflow/planning/context_builder.py`
- [ ] Import from `Registry` to get metadata
- [ ] Handle missing/incomplete metadata gracefully
- [ ] Format nodes with consistent structure
- [ ] Organize by logical categories
- [ ] Keep context under 2000 tokens (base)
- [ ] Cache formatted context for performance
- [ ] Write tests with real registry data
- [ ] Test output with actual LLM

## Core Functions Needed

```python
class PlannerContextBuilder:
    def __init__(self, registry_metadata: Dict[str, Any])
    def build_context(self) -> str
    def _organize_by_category(self) -> Dict[str, Dict]
    def _format_node(self, name: str, metadata: Dict) -> str
    def _format_interface_keys(self, keys: List[str]) -> str
```

## Error Handling

Handle these cases:
1. Node with no metadata → Include with "(metadata missing)"
2. Empty inputs/outputs → Show as "none"
3. Missing description → Use node name
4. No actions → Default to ["default"]

## Testing Priority

1. **Format consistency** - All nodes follow same pattern
2. **Real registry data** - Works with actual Task 5 output
3. **LLM usability** - Context enables planning
4. **Token limits** - Stays under limits with full registry

## Performance Tips

1. Cache formatted context between calls
2. Pre-organize nodes by category on init
3. Use string joining, not concatenation
4. Consider lazy loading for large registries

## Common Mistakes to Avoid

❌ Including implementation details
❌ Over-formatting with complex structures
❌ Excluding nodes with incomplete metadata
❌ Making context too verbose
❌ Forgetting to escape special characters

✅ Keep it simple and consistent
✅ Focus on interfaces
✅ Include all nodes
✅ Test with real LLM
✅ Handle edge cases gracefully

## Quick Test

```python
# This should work after implementation
builder = PlannerContextBuilder.from_registry()
context = builder.build_context()

# Should see organized, formatted nodes
print(context)

# Should be under token limit
assert len(context.split()) < 2000  # rough estimate

# Should include key nodes
assert 'read-file' in context
assert 'shared["file_path"]' in context
```

---

Remember: This component is the bridge between metadata and AI reasoning. Keep it simple, clear, and focused on what the planner needs to make intelligent decisions.
