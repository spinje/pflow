# Task 22: Revised Implementation Plan

## Summary of Findings

After thorough testing and investigation:
1. **Basic named workflow execution DOES work** for kebab-case names
2. **Major gaps**: No input validation, no .json extension support, poor single-word detection
3. **Shell pipe bug exists** (will fix separately if we encounter it)

## Implementation Priorities

### 🎯 Phase 1: Core Safety & Usability (Must Have)

#### 1.1 Support .json Extension & File Paths
**Why**: Users naturally type `pflow my-workflow.json` or `pflow ./workflow.json`

**Implementation**:
- Create `resolve_workflow()` function that tries:
  1. Exact name in saved workflows
  2. Name without .json in saved workflows
  3. Local file path resolution
- Update `is_likely_workflow_name()` to detect .json and paths
- Modify `_try_direct_workflow_execution()` to use resolution

**Files to modify**:
- `src/pflow/cli/main.py` - Add resolution logic

#### 1.2 Connect Input Validation
**Why**: Currently no validation against declared inputs (Task 21's work unused)

**Implementation**:
- Import `prepare_inputs()` from `workflow_validator.py`
- Call it before execution with workflow's declared inputs
- Apply default values for optional inputs
- Convert types based on declarations

**Files to modify**:
- `src/pflow/cli/main.py` - Add validation in `_try_direct_workflow_execution()`

#### 1.3 Better Error Messages
**Why**: Current errors are generic and unhelpful

**Implementation**:
- When workflow not found: List available workflows
- When inputs invalid: Show required/optional inputs with descriptions
- When type mismatch: Show expected vs provided type

### 📊 Phase 2: Discovery Commands (Should Have)

#### 2.1 List Command
```bash
pflow list
```
Shows all saved workflows with descriptions

**Implementation**:
- Add new Click command in main.py
- Use WorkflowManager.list_all()
- Format output nicely

#### 2.2 Describe Command
```bash
pflow describe my-workflow
```
Shows workflow's inputs, outputs, and description

**Implementation**:
- Add new Click command
- Load workflow metadata
- Display inputs/outputs with types and descriptions

### 🔧 Phase 3: Enhanced Features (Nice to Have)

#### 3.1 Type Conversion
- Parse numbers, booleans, JSON from CLI strings
- Based on input type declarations

#### 3.2 Improved Single-Word Detection
- Make heuristics less conservative
- Allow common single-word workflow names

## Implementation Order

1. **Start with .json extension support** - Biggest usability win
2. **Add input validation** - Critical for safety
3. **Implement list/describe** - Helps users discover features
4. **Enhanced error messages** - Throughout all changes

## Code Structure Plan

### New Functions in `main.py`:

```python
def resolve_workflow(name: str) -> tuple[Optional[dict], str]:
    """Resolve workflow from name, name.json, or file path."""

def validate_and_prepare_inputs(
    workflow_ir: dict,
    raw_params: dict[str, str]
) -> dict[str, Any]:
    """Validate params against inputs and apply defaults."""

@main.command()
def list():
    """List all saved workflows."""

@main.command()
def describe(name: str):
    """Describe a workflow's interface."""
```

### Modified Functions:

```python
def is_likely_workflow_name(first_arg: str) -> bool:
    # Add: .json detection, path detection

def _try_direct_workflow_execution(...):
    # Add: resolution, validation, better errors
```

## Testing Strategy

### Unit Tests:
- Test `resolve_workflow()` with various inputs
- Test validation with missing/invalid inputs
- Test type conversion

### Integration Tests:
- Save workflow → Run with .json → Verify
- Run with invalid inputs → Check error message
- Test list/describe commands

### E2E Tests:
- Full workflow: Create → Save → List → Describe → Execute
- Test with various parameter types
- Test file vs saved workflow execution

## Success Criteria

After implementation:
1. ✅ `pflow my-workflow.json` works for saved workflows
2. ✅ `pflow ./workflow.json` works for local files
3. ✅ Parameters are validated against declared inputs
4. ✅ Default values are applied
5. ✅ Users can discover workflows with `pflow list`
6. ✅ Users can see interface with `pflow describe`
7. ✅ Clear error messages guide users

## What We're NOT Doing (Yet)

1. ❌ Fixing shell pipe bug (separate task)
2. ❌ Adding `pflow run` command (keep implicit for now)
3. ❌ Complex type inference (keep simple string → type)
4. ❌ Workflow aliases or shortcuts
5. ❌ Tab completion

## Next Steps

1. Get user approval on this plan
2. Implement Phase 1 (Core Safety & Usability)
3. Test thoroughly
4. Add Phase 2 (Discovery) if time permits
5. Document the feature