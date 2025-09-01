# Critical User Decisions for Task 22: Named Workflow Execution

## 1. CLI Interface Pattern - Decision Importance (4/5)

How should users invoke saved workflows by name?

### Context:

Currently, pflow has partial support for named workflows through implicit detection:
- `pflow my-workflow param=value` works if "my-workflow" exists
- Single words like `pflow analyze` are NOT detected as workflow names (go to planner)
- The heuristics are conservative to avoid false positives

### Options:

- [x] **Option A: Enhanced Implicit Detection (Keep Current Pattern)**
  ```bash
  pflow fix-issue issue=1234        # Named workflow
  pflow "fix issue 1234"            # Natural language
  ```
  - ✅ Maintains backwards compatibility
  - ✅ Simpler, more "magical" UX
  - ✅ Aligns with CLI-first philosophy
  - ❌ Ambiguous for single-word workflows
  - ❌ Requires careful heuristics tuning

- [ ] **Option B: Explicit `run` Command**
  ```bash
  pflow run fix-issue issue=1234    # Named workflow (explicit)
  pflow "fix issue 1234"            # Natural language
  ```
  - ✅ Clear, unambiguous intent
  - ✅ Industry standard (npm run, make, etc.)
  - ✅ Easier to add subcommands (run --list, run --help)
  - ❌ More verbose
  - ❌ Breaking change

- [ ] **Option C: Hybrid Approach**
  ```bash
  pflow run fix-issue issue=1234    # Explicit (always works)
  pflow fix-issue issue=1234        # Implicit (enhanced heuristics)
  ```
  - ✅ Best of both worlds
  - ✅ Gradual migration path
  - ❌ Two ways to do the same thing
  - ❌ More complex documentation

**Recommendation**: Option A - The implicit detection is already working and aligns with pflow's philosophy of minimal, intuitive CLI interaction. We should enhance the heuristics and add better error messages rather than introducing new commands.

---

## 2. Parameter Syntax - Decision Importance (3/5)

How should users pass parameters to named workflows?

### Context:

Currently uses positional `key=value` syntax. Need to decide if we should support additional formats for better usability and type handling.

### Options:

- [x] **Option A: Enhanced key=value (Current Pattern)**
  ```bash
  pflow fix-issue issue=1234 verbose=true items='["a","b"]'
  ```
  - ✅ Already implemented and working
  - ✅ Simple and consistent
  - ✅ Supports JSON for complex types
  - ❌ No GNU-style options (--param)
  - ❌ Everything looks like strings initially

- [ ] **Option B: GNU-style Options**
  ```bash
  pflow fix-issue --issue=1234 --verbose --items='["a","b"]'
  ```
  - ✅ Industry standard
  - ✅ Better boolean flag support
  - ❌ Conflicts with pflow's own options
  - ❌ Major change to existing pattern

- [ ] **Option C: Mixed Approach**
  ```bash
  pflow fix-issue issue=1234 --verbose --no-cache
  ```
  - ✅ Natural for different param types
  - ❌ Confusing which syntax to use when
  - ❌ Complex parsing logic

**Recommendation**: Option A - Keep the current key=value pattern but add intelligent type conversion based on workflow input declarations. This maintains consistency and simplicity.

---

## 3. Discovery Commands - Decision Importance (2/5)

What commands should we provide for workflow discovery and help?

### Context:

Users need ways to discover available workflows and understand their parameters. Currently no discovery mechanism exists.

### Options:

- [x] **Option A: Dedicated Commands**
  ```bash
  pflow list                    # List all workflows
  pflow describe fix-issue      # Show workflow details
  ```
  - ✅ Clear, dedicated purpose
  - ✅ Easy to implement
  - ✅ Follows Unix philosophy
  - ❌ More commands to remember

- [ ] **Option B: Subcommand under `workflow`**
  ```bash
  pflow workflow list
  pflow workflow describe fix-issue
  pflow workflow delete fix-issue
  ```
  - ✅ Groups related commands
  - ✅ Room for expansion
  - ❌ More verbose
  - ❌ Inconsistent with current pattern

- [ ] **Option C: Help Flag Pattern**
  ```bash
  pflow --list
  pflow fix-issue --help
  ```
  - ✅ Familiar pattern
  - ❌ Conflicts with pflow's own help
  - ❌ Less discoverable

**Recommendation**: Option A - Simple, dedicated commands are most intuitive and align with pflow's design philosophy.

---

## 4. Implementation Priority - Decision Importance (5/5)

What should we implement first to deliver maximum value?

### Context:

The investigation revealed that basic named workflow execution already works, but lacks input validation, defaults, and discovery. We need to prioritize enhancements.

### Options:

- [x] **Option A: Core Validation First**
  Phase 1: Input validation + defaults (immediate safety/correctness)
  Phase 2: Discovery commands (improved UX)
  Phase 3: Advanced types (nice-to-have)
  - ✅ Delivers immediate value (safety)
  - ✅ Builds on Task 21's work
  - ✅ Minimal code changes
  - ❌ Discovery comes later

- [ ] **Option B: Discovery First**
  Phase 1: List/describe commands
  Phase 2: Input validation
  Phase 3: Advanced features
  - ✅ Better initial UX
  - ❌ Workflows remain unsafe without validation
  - ❌ Doesn't leverage Task 21 immediately

- [ ] **Option C: Complete Feature**
  Implement everything at once
  - ✅ Full feature in one go
  - ❌ Larger change, more risk
  - ❌ Delayed delivery

**Recommendation**: Option A - Start with core validation to ensure workflows execute safely with proper parameter handling. This provides immediate value while being a focused, low-risk change.

---

## Summary of Recommendations

1. **Keep implicit detection** - Enhance existing pattern rather than adding new commands
2. **Keep key=value syntax** - Add type conversion but maintain current pattern
3. **Add simple commands** - `pflow list` and `pflow describe` for discovery
4. **Implement validation first** - Connect Task 21's input declarations to execution

This approach maintains pflow's minimalist philosophy while adding essential safety and usability features.