# Task 19: Node IR Implementation - Fix Template Validation with Proper Metadata

## The Problem You're Solving

The template validator is failing valid workflows because it uses hardcoded heuristics to guess which variables come from the shared store. When a node writes `$api_config` (not in the magic list of "common" outputs), validation fails even though the workflow would run perfectly. This is frustrating users and blocking adoption.

## Your Mission

Transform pflow's metadata system by moving interface parsing from runtime to scan-time, creating a proper "Node IR" (Intermediate Representation) that stores fully parsed node metadata in the registry. This eliminates flawed heuristics and enables accurate validation by checking template variables against what nodes ACTUALLY write.

## Required Reading (IN THIS ORDER)

### 1. FIRST: Read the Critical Context
**File**: `.taskmaster/tasks/task_19/node-ir-implementation-critical-context.md`

**Purpose**: Hard-earned implementation wisdom from Task 18 (template system). This document contains:
- Specific bugs you WILL hit and their solutions
- File locations and line numbers that matter
- Performance measurements from real testing
- The circular import trap and how to avoid it
- Why certain patterns exist and must be preserved

**Why read first**: This will save you hours of debugging by learning from actual implementation experience.

### 2. SECOND: Read the Comprehensive Implementation Guide
**File**: `.taskmaster/tasks/task_19/node-ir-comprehensive-implementation-guide.md`

**Purpose**: Complete architectural design and implementation plan. This document contains:
- Detailed problem analysis with examples
- Step-by-step implementation for each component
- Code examples with critical annotations
- The full path validation approach
- Testing strategies

**Why read second**: This gives you the complete picture of WHAT to build and HOW to build it.

### 3. THIRD: Read the Formal Specification
**File**: `.taskmaster/tasks/task_19/18_spec.md`

**Purpose**: Exact requirements, test criteria, and acceptance conditions. This document contains:
- Precise inputs/outputs for each component
- All 17 rules that must be followed
- Complete test criteria (24 items)
- Performance requirements
- Error handling specifications

**Why read third**: This ensures you meet all formal requirements after understanding the context and design.

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

## Your Implementation Order

1. **Start with understanding**: Read the MetadataExtractor tests to see all format variations
2. **Implement scanner changes**: Add dependency injection and interface parsing
3. **Update validator**: Full path traversal replacing heuristics
4. **Simplify context builder**: Remove parsing, use stored data
5. **Run full test suite**: Ensure nothing breaks
6. **Clean up**: Remove all old heuristic code

## What NOT to Do

- **DON'T** modify any node implementations
- **DON'T** change the workflow IR structure
- **DON'T** add backward compatibility for old registry format
- **DON'T** hide or skip errors - fail fast with clear messages
- **DON'T** optimize prematurely - get it working first

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

Good luck! You're fixing a fundamental flaw that will make pflow significantly more reliable.
