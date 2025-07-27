# Task 19: Node IR Implementation - Fix Template Validation with Proper Metadata

## The Problem You're Solving

The template validator is failing valid workflows because it uses hardcoded heuristics to guess which variables come from the shared store. When a node writes `$api_config` (not in the magic list of "common" outputs), validation fails even though the workflow would run perfectly. This is frustrating users and blocking adoption.

## Your Mission

Transform pflow's metadata system by moving interface parsing from runtime to scan-time, creating a proper "Node IR" (Intermediate Representation) that stores fully parsed node metadata in the registry. This eliminates flawed heuristics and enables accurate validation by checking template variables against what nodes ACTUALLY write.

## Required Reading (IN THIS ORDER)

### 1. FIRST: Understand the Epistemic Approach
**File**: `.taskmaster/workflow/epistemic-manifesto.md`

**Purpose**: Core principles for deep understanding and robust development. This document establishes:
- Your role as a reasoning system, not just an instruction follower
- The importance of questioning assumptions and validating truth
- How to handle ambiguity and uncertainty
- Why elegance must be earned through robustness

**Why read first**: This mindset is critical for implementing a foundational system change correctly. You'll need to question existing patterns, validate assumptions, and ensure the solution survives scrutiny.

### 2. SECOND: Read the Critical Context
**File**: `.taskmaster/tasks/task_19/node-ir-implementation-critical-context.md`

**Purpose**: Hard-earned implementation wisdom from Task 18 (template system). This document contains:
- Specific bugs you WILL hit and their solutions
- File locations and line numbers that matter
- Performance measurements from real testing
- The circular import trap and how to avoid it
- Why certain patterns exist and must be preserved

**Why read first**: This will save you hours of debugging by learning from actual implementation experience.

### 3. THIRD: Read the Comprehensive Implementation Guide
**File**: `.taskmaster/tasks/task_19/node-ir-comprehensive-implementation-guide.md`

**Purpose**: Complete architectural design and implementation plan. This document contains:
- Detailed problem analysis with examples
- Step-by-step implementation for each component
- Code examples with critical annotations
- The full path validation approach
- Testing strategies

**Why read third**: This gives you the complete picture of WHAT to build and HOW to build it.

### 4. FOURTH: Read the Formal Specification
**File**: `.taskmaster/tasks/task_19/18_spec.md`

**Purpose**: Exact requirements, test criteria, and acceptance conditions. This document contains:
- Precise inputs/outputs for each component
- All 17 rules that must be followed
- Complete test criteria (24 items)
- Performance requirements
- Error handling specifications

**Why read fourth**: This ensures you meet all formal requirements after understanding the context and design.

## Key Outcomes You Must Achieve

### 1. Scanner Enhancement
- Parse Interface docstrings during scanning (not runtime)
- Store complete metadata including nested structures
- Use dependency injection for MetadataExtractor
- Fail fast with actionable errors (file:line references)

### 2. Validator Transformation
- Replace ALL heuristic code with registry lookups
- Validate complete paths (e.g., `$api_config.endpoint.url`)
- Handle both simple and rich output formats
- Check actual node outputs, not magic lists

### 3. Context Builder Simplification
- Remove ~100 lines of dynamic import code
- Use pre-parsed interface data directly
- Preserve EXACT output format (planner depends on it)
- Return zero skipped nodes

### 4. System Properties
- Registry grows from ~50KB to ~500KB-1MB
- Scan time increases but runtime decreases
- All errors include actionable fix instructions
- No behavior changes to nodes or workflows

## Critical Warnings from Experience

### 1. The Circular Import Trap
Scanner is imported by registry at module level. If you import MetadataExtractor at module level in scanner, you get circular imports. Use the dependency injection pattern shown in the guide.

### 2. The Output Format Duality
MetadataExtractor returns EITHER:
- Simple format: `["output1", "output2"]`
- Rich format: `[{"key": "output1", "type": "str"}]`

You MUST handle both or validation will crash at runtime.

### 3. The Registry Performance Hit
The registry loads on EVERY pflow command (even `pflow --version`). Your larger registry adds ~50ms to every command. This is acceptable but be aware.

### 4. The Format Preservation Requirement
The context builder output format must be EXACTLY preserved. The planner will break if even one field changes. Test this carefully.

## Critical Clarification: Breaking Changes

**Breaking Change - Fresh Start**: This is an MVP with no users. Simply update the scanner to generate the new format with interface data. Delete any existing registry and regenerate it. Do not add any backward compatibility code. The context builder can assume the interface field always exists.

**All Existing Functionality Must Remain**: While the registry format is changing, ALL existing system behavior must work exactly as before. All 610 tests must pass. You are changing HOW metadata is stored, not WHAT the system does.

**No Migration Needed**: Since there are no users, you don't need to handle old registry formats. Every component can assume the new `interface` field exists. If it doesn't exist, that's an error - fail fast with a clear message.

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_19/implementation/progress-log.md`

```markdown
# Task 19 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### 1. Start with understanding
Read the MetadataExtractor tests to see all format variations

### 2. Implement scanner changes
Add dependency injection and interface parsing

### 3. Update validator
Full path traversal replacing heuristics

### 4. Simplify context builder
Remove parsing, use stored data

### 5. Run full test suite
Ensure nothing breaks

### 6. Clean up
Remove all old heuristic code

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - [What I'm trying]
Attempting to [specific action]...

Result: [What happened]
- ✅ What worked: [Specific detail]
- ❌ What failed: [Specific detail]
- 💡 Insight: [What I learned]

Code that worked:
```python
# Actual code snippet
```
```

## Handle Discoveries and Deviations

**When you discover the plan needs adjustment:**

1. Document why the original plan didn't work
2. Capture what you learned
3. Update the plan with new approach
4. Continue with new understanding

Append deviation to progress log:
```markdown
## [Time] - DEVIATION FROM PLAN
- Original plan: [what was planned]
- Why it failed: [specific reason]
- New approach: [what you're trying instead]
- Lesson: [what this teaches us]
```

## Test Creation Guidelines

**Core Principle**: "Test what matters"

**Focus on quality over quantity**:
- Test public interfaces and critical paths
- Test edge cases where bugs typically hide
- Create integration tests when components interact
- Document only interesting test discoveries in your progress log

**What to test**:
- **Critical paths**: Business logic that must work correctly
- **Public APIs**: Functions/classes exposed to other modules
- **Error handling**: How code behaves with invalid input
- **Integration points**: Where components connect

**What NOT to test**:
- Simple getters/setters
- Configuration loading
- Framework code
- Internal helper functions (unless complex)

**Progress Log - Only document testing insights**:
```markdown
## 14:50 - Testing revealed edge case
While testing extract_metadata(), discovered that nodes with
circular imports crash the scanner. Added import guard pattern.
This affects how we handle all dynamic imports.
```

**Remember**: Quality tests that catch real bugs > many trivial tests

## What NOT to Do

- **DON'T** modify any node implementations
- **DON'T** change the workflow IR structure
- **DON'T** add ANY backward compatibility code - assume new format everywhere
- **DON'T** check if interface field exists - it MUST exist
- **DON'T** hide or skip errors - fail fast with clear messages
- **DON'T** optimize prematurely - get it working first
- **DON'T** break existing functionality - all 610 tests must pass
- **DON'T** cheat when tests fail - fix the root cause and make sure no functionality is lost or broken

## Definition of Success

You'll know you're done when:

1. ✅ The validator uses actual node outputs from registry (not heuristics)
2. ✅ Full path validation works (e.g., `$config.api.endpoint.url`)
3. ✅ All parsing happens at scan-time (none at runtime)
4. ✅ Context builder is ~100 lines simpler
5. ✅ All tests pass including new path validation tests
6. ✅ Error messages show file:line and how to fix
7. ✅ No heuristic code remains in the validator

## Remember

You're not adding new functionality - you're moving existing parsing from runtime to scan-time. The system behavior should be identical, just faster and more accurate. The template system (Task 18) works because it's transparent to nodes. Your Node IR must be equally transparent.

The design in the implementation guide is solid and battle-tested. Trust it. The details will try to kill you (especially the output format handling), but the architecture is right.

Following the epistemic manifesto: Question assumptions, validate against the code, and ensure your implementation survives scrutiny. When faced with ambiguity, surface it rather than guessing. This is a foundational change - robustness matters more than elegance.

Good luck! Think hard!You're fixing a fundamental flaw that will make pflow significantly more reliable.
