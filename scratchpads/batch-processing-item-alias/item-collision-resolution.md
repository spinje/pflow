# Item Alias Collision Resolution Analysis

## Question
If `shared["item"]` already exists before batch execution, what should BatchNodeWrapper do?

## Findings

### Existing Patterns for Temporary State Modification

#### 1. TemplateAwareNodeWrapper Pattern (lines 859-871 in node_wrapper.py)

**Usage**: Temporarily modifies `inner_node.params` during template resolution

**Pattern**:
```python
# Save original state
original_params = self.inner_node.params

# Modify temporarily
merged_params = {**self.static_params, **resolved_params}
self.inner_node.params = merged_params

try:
    # Execute with modified state
    result = self.inner_node._run(shared)
    return result
finally:
    # Restore original state (defensive programming)
    self.inner_node.params = original_params
```

**Key characteristics**:
- Uses try/finally for guaranteed restoration
- Saves complete original state
- Comment notes: "defensive programming in case the node is reused"
- Does NOT delete, always restores to original value

#### 2. PocketFlow BatchNode (pocketflow/__init__.py:78-80)

**Current implementation**:
```python
class BatchNode(Node):
    def _exec(self, items):
        return [super(BatchNode, self)._exec(i) for i in (items or [])]
```

**Observation**:
- Does NOT modify shared store at all
- Each item is passed to exec() directly as parameter
- No "item" alias concept exists in base PocketFlow

#### 3. No Existing Shared Store Backup/Restore Pattern

**Search results**: No existing pattern for temporary shared store modification in the codebase

**Implication**: We're establishing a new pattern for pflow

## Risk Analysis for Key Collision

### Collision Probability: LOW but SIGNIFICANT when it occurs

**Why LOW**:
- Users would need to manually create `shared["item"]` before batch node
- Not a common pattern in typical workflows
- Most data flows through namespaced keys like `${node-id.output}`

**Why SIGNIFICANT when it occurs**:
- Data corruption: User's original `shared["item"]` value would be lost
- Silent failure: User won't know their data was overwritten
- Debug difficulty: Hard to trace why original data disappeared
- Workflow breakage: Downstream nodes expecting original `shared["item"]` would fail

### Specific Risk Scenarios

1. **User workflow with pre-existing "item" key**:
   ```json
   {
     "nodes": [
       {
         "id": "setup",
         "type": "llm",
         "params": {},
         "outputs": {"item": "user-data"}  // Sets shared["item"]
       },
       {
         "id": "batch",
         "type": "batch",
         "params": {
           "items": "${setup.items}",
           "item_alias": "item"  // COLLISION!
         }
       },
       {
         "id": "use-original",
         "params": {
           "data": "${setup.item}"  // Expects original, gets batch item!
         }
       }
     ]
   }
   ```

2. **Nested workflows**:
   - Parent workflow sets `shared["item"]`
   - Child workflow has batch node with `item_alias: "item"`
   - Parent's data silently corrupted

## Recommendations

### Option A: Save and Restore Original Value (RECOMMENDED)

**Pattern**: Follow TemplateAwareNodeWrapper's defensive approach

**Implementation**:
```python
def _run(self, shared):
    # Check for collision and save original
    had_original = self.item_alias in shared
    original_value = shared.get(self.item_alias) if had_original else None

    try:
        # Process batch with temporary alias
        for item in items:
            shared[self.item_alias] = item
            result = self.inner_node._run(shared)
            results.append(result)

        return results
    finally:
        # Restore original state
        if had_original:
            shared[self.item_alias] = original_value
        else:
            shared.pop(self.item_alias, None)
```

**Pros**:
- ✅ Zero data loss - original value preserved
- ✅ Follows established pflow pattern (TemplateAwareNodeWrapper)
- ✅ Defensive programming - safe for node reuse
- ✅ Predictable behavior - workflow state unchanged after batch
- ✅ Works correctly with nested workflows
- ✅ No silent failures - user data always safe

**Cons**:
- Minimal extra complexity (2 variables: `had_original`, `original_value`)

### Option B: Delete After (NOT RECOMMENDED)

**Implementation**:
```python
def _run(self, shared):
    try:
        for item in items:
            shared[self.item_alias] = item
            result = self.inner_node._run(shared)
            results.append(result)
        return results
    finally:
        shared.pop(self.item_alias, None)
```

**Pros**:
- Slightly simpler code

**Cons**:
- ❌ Data loss - original value destroyed
- ❌ Silent failure - user won't know data was lost
- ❌ Breaking change - shared store state differs before/after
- ❌ Nested workflow issues - parent's data corrupted
- ❌ Violates principle of least surprise

### Option C: Raise Error on Collision (DEFENSIVE ALTERNATIVE)

**Implementation**:
```python
def _run(self, shared):
    # Fail fast on collision
    if self.item_alias in shared:
        raise ValueError(
            f"Batch node collision: '{self.item_alias}' already exists in shared store.\n"
            f"Current value: {shared[self.item_alias]}\n"
            f"Choose a different item_alias to avoid collision."
        )

    # Normal batch processing...
```

**Pros**:
- ✅ Explicit failure - no silent data corruption
- ✅ Forces user to fix collision
- ✅ Clear error message guides resolution

**Cons**:
- ❌ Breaks workflows that might work fine with save/restore
- ❌ Less forgiving than Option A
- ❌ Requires user intervention

## Concrete Implementation Recommendation

**Use Option A: Save and Restore**

**Rationale**:
1. **Consistency**: Matches TemplateAwareNodeWrapper's proven pattern
2. **Safety**: Zero data loss, no silent failures
3. **Compatibility**: Works with nested workflows and edge cases
4. **Predictability**: Shared store state unchanged after batch execution
5. **Defensive**: Safe for node reuse scenarios

**Code Pattern**:
```python
def _run(self, shared: dict[str, Any]) -> Any:
    """Execute batch processing with item alias."""

    # Save original state (if collision exists)
    had_original = self.item_alias in shared
    original_value = shared.get(self.item_alias) if had_original else None

    if had_original:
        logger.debug(
            f"Batch node '{self.node_id}': '{self.item_alias}' already exists in shared store, "
            "will restore after batch execution",
            extra={"node_id": self.node_id, "alias": self.item_alias}
        )

    try:
        # Get items to process
        items = self._get_batch_items(shared)

        # Process each item
        results = []
        for item in items:
            shared[self.item_alias] = item
            result = self.inner_node._run(shared)
            results.append(result)

        return results
    finally:
        # Restore original state (defensive programming)
        if had_original:
            shared[self.item_alias] = original_value
        else:
            shared.pop(self.item_alias, None)
```

## Alternative Consideration: Validation Warning

**Enhancement**: Add validation warning (not error) when collision detected

```python
# In template_validator.py or batch-specific validation
if item_alias in declared_outputs:
    warnings.append(
        f"Batch node '{node_id}' uses item_alias '{item_alias}' which matches "
        f"an existing output. This may cause confusion. Consider renaming the alias."
    )
```

**Benefit**: Alerts users to potential confusion without breaking workflows

## Summary

**Decision**: Implement Option A (Save and Restore)

**Justification**:
- Follows existing pflow pattern (TemplateAwareNodeWrapper)
- Zero data loss
- Predictable behavior
- Safe for all scenarios (nested workflows, node reuse)
- Minimal complexity cost

**Implementation Location**: `BatchNodeWrapper._run()` method

**Testing Requirements**:
- Test with pre-existing `shared["item"]`
- Test with nested workflows
- Test that original value is correctly restored
- Test that non-existent keys are properly deleted after batch
