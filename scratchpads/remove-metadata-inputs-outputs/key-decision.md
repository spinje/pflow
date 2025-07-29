# Key Decision: Complete Removal vs Optional Fields

## The Choice

Should we:
1. **Completely remove** inputs/outputs from metadata (recommended)
2. Make them **optional** and auto-generate from IR

## Analysis

### Option 1: Complete Removal (Recommended) ✅

**Pros:**
- Clean architecture - IR is the single source of truth
- No duplication or sync issues
- Forces proper IR declarations
- Simpler codebase
- Aligns with "IR = Contract" principle

**Cons:**
- Breaking change (but no users yet!)
- Slightly more complex display logic

**Implementation:**
- Remove fields from validation
- Extract from IR for display
- Update all fixtures/examples

### Option 2: Optional with Auto-generation

**Pros:**
- Gradual migration path
- Could support both formats

**Cons:**
- Maintains confusion about source of truth
- More complex logic
- Technical debt remains
- Sync issues still possible

## Recommendation: Complete Removal

Since we have **no users** and are building an MVP:

1. **Make the breaking change now** - This is the perfect time
2. **Establish clean patterns** - Start with the right architecture
3. **Avoid technical debt** - Don't carry forward bad decisions
4. **Simplify the system** - One source of truth is clearer

The context_builder can easily extract what it needs from the IR, and display even richer information (types, descriptions, defaults) than the simple string arrays provided.

## Impact on Task 17 (Planner)

The planner will benefit from this change:
- Can access detailed type information
- Can see descriptions for better parameter mapping
- Can validate workflow composition at planning time
- No confusion about which fields to use

## Decision

**Proceed with complete removal** as outlined in the migration plan.
