# Task 56: Implement Runtime Validation and Error Feedback Loop for planner

## ID
56

## Title
Implement Runtime Validation and Error Feedback Loop

## Description
Enable workflows to self-correct during initial generation by feeding runtime errors back to the planner for automatic fixes. This allows the planner to make educated guesses about data structures (like API responses) and correct them based on actual runtime feedback, eliminating the need for pre-knowledge of external data formats.

## Status
not started

## Dependencies
- Task 54: Implement HTTP Node - The HTTP node is the primary use case that would benefit from runtime validation, as it deals with unknown API response structures
- Task 17: Implement Natural Language Planner System - The planner needs to be extended to handle runtime error feedback and generate corrected workflows

## Priority
medium

## Details
The Runtime Validation system transforms pflow from a static workflow executor into a learning system that can discover and adapt to unknown data structures during workflow generation. This is particularly crucial for API integrations where response formats are unknown at planning time.

### Core Concept
Currently, the planner must guess API field names and structures without seeing actual responses. With runtime validation:
1. Planner makes best guess at field extraction (e.g., assumes "username" field exists)
2. Workflow runs and encounters runtime error (e.g., "Field 'username' not found, available fields: login, id, bio...")
3. Error feeds back to planner with actual data structure
4. Planner corrects the workflow using real field names
5. Workflow succeeds and saves with correct extraction logic

### Key Components to Build

**1. Enhanced HTTP Node** (or new extraction capability)
- Support optional `extract` parameter for dot/array path extraction (e.g., `$.field`, `$.nested.field`, `$.items[0].name`)
- On success, include an `extracted` object in results while keeping existing `response` semantics (no separate `raw` key)
- On missing path, raise `RuntimeValidationError` including attempted paths, available top-level keys, and a structure sample
- HTTP `exec_fallback` MUST re-raise `RuntimeValidationError` unchanged

**2. Runtime Validation Loop (Planner)**
- Add `RuntimeValidationNode` to the planner after metadata generation
- Execute the generated workflow once (actual run) and collect runtime issues
- Populate `shared["runtime_errors"]` for fixable issues and route actions:
  - `runtime_fix` when fixable issues exist and attempts < 3
  - `failed_runtime` when only fatal issues exist or attempts ≥ 3
  - default when no issues are detected
- Implement retry logic with corrected workflow (max 3 attempts)

**3. Planner Runtime Fix Capability**
- New planner prompt/mode for fixing runtime errors
- Include actual data structure in context for correction
- Generate updated workflow IR with fixed extraction paths and/or corrected tool arguments using `shared["runtime_errors"]`
- Preserve original intent while correcting technical details

**4. MCP Runtime Targets (MVP)**
- Treat namespaced node `error` values and missing downstream `${mcp_node.*}` template paths as fixable when they indicate argument/field mismatches

### Example Flow
```python
# User: "fetch GitHub user torvalds and extract username and biography"

# Attempt 1: Planner guesses field names
{
  "name": "http",
  "params": {
    "url": "https://api.github.com/users/torvalds",
    "extract": {
      "username": "$.username",  # Wrong guess
      "biography": "$.biography"  # Wrong guess
    }
  }
}

# Runtime error: "Field '$.username' not found. Available: login, bio, name..."

# Attempt 2: Planner corrects based on error
{
  "name": "http",
  "params": {
    "url": "https://api.github.com/users/torvalds",
    "extract": {
      "username": "$.login",     # Corrected
      "biography": "$.bio"       # Corrected
    }
  }
}

# Success! Workflow saved with correct extraction
```

### Design Decisions
- Limit runtime correction attempts to prevent infinite loops (max 3)
- Execute all nodes during runtime validation (actual run); double execution on retries is accepted for MVP
- Runtime validation happens only during initial workflow generation
- Once saved, workflows remain deterministic (no auto-fixing in production)
- Focus on field extraction errors first, expand to other error types later

### Benefits
- Eliminates need for pre-knowledge of API structures
- Reduces dependency on LLM for simple field extraction
- Makes workflows more deterministic after initial generation
- Enables true "learning by doing" for workflow creation
- Universal solution that could work for file paths, git branches, etc.

### Future Extension (Not in MVP)
The system could eventually support post-generation self-healing where saved workflows adapt to API changes over time, but this requires workflow versioning and is out of scope for initial implementation.

## Test Strategy
Testing will focus on the feedback loop and planner correction capabilities:

**Unit Tests:**
- Test extraction error detection and field availability reporting
- Test planner's ability to parse runtime errors
- Test correction logic for various error types
- Test retry limit enforcement

**Integration Tests:**
- End-to-end test with mock API returning unexpected structure
- Test workflow generation → error → correction → success flow
- Test with nested JSON structures and arrays
- Test failure cases where correction isn't possible

**Key Test Scenarios:**
- Simple field name mismatch (username vs login)
- Nested path correction ($.data.user vs $.user)
- Array access correction ($.items[0] vs $.data[0])
- Multiple field corrections in single attempt
- Non-correctable errors (API returns HTML instead of JSON)
- Retry limit exhaustion