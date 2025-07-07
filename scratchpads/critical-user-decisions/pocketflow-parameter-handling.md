# Critical Decision: PocketFlow Parameter Handling Issue

## Decision Title - Decision Importance (4/5)

The PocketFlow framework has a parameter overwriting issue that prevents pflow from using node parameters as intended. This needs to be resolved for the workflow execution to work correctly.

## Context

The other AI agent discovered that PocketFlow's `Flow._orch()` method overwrites node parameters with flow parameters, causing nodes to lose their configured values. This happens because:

1. pflow sets parameters on nodes during compilation (e.g., `{"file_path": "input.txt"}`)
2. When `Flow.run()` executes, it calls `_orch()` which overwrites these parameters with the Flow's empty parameters
3. Nodes fail with "Missing required 'file_path'" errors

## Technical Analysis

### PocketFlow's Design Intent
- Parameters are designed for BatchFlow use cases where parent flows pass different parameters to child flows/nodes
- The documentation states: "Only set the uppermost Flow params because others will be overwritten by the parent Flow"
- This is intentional behavior for batch processing scenarios

### pflow's Use Case
- pflow uses parameters as static configuration values set during workflow compilation
- This is different from PocketFlow's batch-oriented parameter design
- All pflow nodes implement a fallback pattern: check shared store first, then params

## Options

### Option A: Use PreservingFlow Wrapper (Current Implementation)
- **Description**: Create a custom Flow subclass that doesn't overwrite node parameters
- **Pros**:
  - Minimal change - only affects flow creation
  - Maintains clean separation between PocketFlow and pflow
  - Already implemented and working
  - Clear intent with descriptive class name
- **Cons**:
  - Adds a wrapper layer
  - Diverges from standard PocketFlow usage
  - May need maintenance if PocketFlow changes

### Option B: Store All Configuration in Shared Store
- **Description**: Don't use parameters at all; put everything in the shared store
- **Pros**:
  - Aligns with PocketFlow's design philosophy
  - No need for wrapper classes
  - Shared store is the primary communication mechanism
- **Cons**:
  - Requires refactoring all nodes and compiler
  - Mixes configuration with runtime data
  - Shared store becomes cluttered with static config
  - Less clear separation of concerns

### Option C: Modify PocketFlow Directly
- **Description**: Change PocketFlow's `_orch()` to preserve node parameters
- **Pros**:
  - Fixes the root cause
  - No wrapper needed
- **Cons**:
  - Violates separation of concerns (PocketFlow is external framework)
  - Would break PocketFlow's batch functionality
  - Makes pflow dependent on modified PocketFlow version

### Option D: Use Flow Parameters Instead
- **Description**: Set parameters on the Flow object, not individual nodes
- **Pros**:
  - Works with current PocketFlow design
  - No modifications needed
- **Cons**:
  - All nodes would share the same parameters
  - Can't have node-specific configuration
  - Doesn't match pflow's workflow model

**Recommendation**: Option A (PreservingFlow Wrapper) - This is the most pragmatic solution that:
1. Solves the immediate problem
2. Maintains clean architecture boundaries
3. Is already implemented and tested
4. Has minimal impact on the rest of the codebase
5. Can be easily modified or removed if PocketFlow's behavior changes

The wrapper approach is a common pattern when integrating with external frameworks that don't exactly match your use case. It's explicit about its purpose and isolated to one file.

## Decision Needed

Should we proceed with the PreservingFlow wrapper approach, or would you prefer to explore one of the alternative solutions?

- [x] **Option A: Keep the PreservingFlow wrapper** (Recommended)
- [ ] **Option B: Refactor to use shared store for all configuration**
- [ ] **Option C: Modify PocketFlow directly**
- [ ] **Option D: Use Flow-level parameters**
