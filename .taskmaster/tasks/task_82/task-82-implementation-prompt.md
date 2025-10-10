# Task 82: Implement System-Wide Binary Data Support - Agent Instructions

## The Problem You're Solving

pflow crashes when downloading binary files (images, PDFs) because nodes only handle text data - HTTP corrupts binary using `response.text`, write-file can't write binary mode, and the shared store has no consistent pattern for binary data. Users cannot build workflows that download images, process PDFs, or handle any non-text content, severely limiting real-world use cases.

## Your Mission

Implement comprehensive binary data support across all file-handling nodes using a base64 encoding contract with explicit binary flags, enabling workflows to download, process, and save binary files transparently.

## Required Reading (IN THIS ORDER)

### 1. FIRST: Understand the Epistemic Approach
**File**: `.taskmaster/workflow/epistemic-manifesto.md`

**Purpose**: Core principles for deep understanding and robust development. This document establishes:
- Your role as a reasoning system, not just an instruction follower
- The importance of questioning assumptions and validating truth
- How to handle ambiguity and uncertainty
- Why elegance must be earned through robustness

**Why read first**: This mindset is critical for implementing any task correctly. You'll need to question existing patterns, validate assumptions, and ensure the solution survives scrutiny.

### 2. SECOND: Task Overview
**File**: `.taskmaster/tasks/task_82/task-82.md`

**Purpose**: High-level overview of the task, its objectives, and current state. This document provides the essential context and background for understanding what needs to be built.

**Why read second**: This gives you the big picture before diving into detailed specifications and implementation guides.

### 3. Read ALL Context Files
**Directory**: `.taskmaster/tasks/task_82/starting-context/`

**Files to read (in this order):**
1. `task-82-spec.md` - The specification (FOLLOW THIS PRECISELY - source of truth for requirements)
2. `task-82-handover.md` - Critical context from investigation phase (namespacing trap, real test workflow)
3. `implementation-research-findings.md` - Deep technical findings (exact line numbers, namespacing issues)
4. `code-examples.md` - Complete implementation examples and test patterns

**Instructions**: Read EACH file listed above. After reading each file, pause to consider:
- What this document tells you about the task
- How it relates to other files you've read
- What implementation decisions it implies

**IMPORTANT**: The specification file (`task-82-spec.md`) is the source of truth for requirements and test criteria. Follow it PRECISELY.

## What You're Building

A system-wide base64 encoding contract that enables binary data handling across all file operations. Nodes detect binary content, encode it as base64 strings with `_is_binary` suffix flags, allowing binary data to flow through workflows transparently.

Example:
```python
# HTTP node detects binary
if "image/" in content_type:
    shared["response"] = base64.b64encode(response.content).decode('ascii')
    shared["response_is_binary"] = True

# Write-file decodes when flag present
if shared.get("content_is_binary", False):
    content = base64.b64decode(content)
    with open(path, "wb") as f:
        f.write(content)
```

## Key Outcomes You Must Achieve

### Core Binary Support Implementation
- HTTP node: Binary detection via Content-Type, base64 encoding, `response_is_binary` flag
- Write-file node: Base64 decoding when flag present, binary write mode
- Read-file node: Binary file detection, base64 encoding, `content_is_binary` flag
- Shell node: Binary stdout/stderr handling with encoding and flags

### Backward Compatibility
- All existing text workflows continue working unchanged
- Missing binary flags default to text mode
- No modifications to template resolution system
- No changes to shared store structure

### Testing & Validation
- Spotify workflow (`.pflow/workflows/spotify-art-generator.json`) downloads and saves album art
- All 18 test criteria from spec passing
- Mixed binary/text workflows function correctly
- No regressions in existing test suite

## Implementation Strategy

### Phase 1: InstrumentedWrapper Safety (30 min)
Verify the type guards are in place to prevent crashes (already partially done)

### Phase 2: HTTP Node Binary Support (1.5 hours)
1. Add binary detection logic (lines 126-137)
2. Use `response.content` for binary (not `response.text`)
3. Implement base64 encoding in post() method
4. Update Interface documentation

### Phase 3: Write-File Binary Support (1 hour)
1. Check `content_is_binary` flag in prep()
2. Decode base64 when flag present
3. Add binary write mode (`wb`/`ab`)
4. Update Interface documentation

### Phase 4: Read-File Binary Support (1.5 hours)
1. Detect binary files by extension
2. Read in binary mode when detected
3. Encode as base64 in post()
4. Handle UnicodeDecodeError fallback
5. Update Interface documentation

### Phase 5: Shell Node Binary Support (1.5 hours)
1. Handle binary stdout/stderr
2. Catch UnicodeDecodeError
3. Encode binary output as base64
4. Set binary flags appropriately
5. Update Interface documentation

### Phase 6: Comprehensive Testing (2 hours)
Write unit tests for each node's binary handling
Create integration tests for binary workflows
Test the Spotify workflow end-to-end

### Use Subagents effectively

Use subagents to maximize efficiency and avoid context window limitations.

> Always use @agent-pflow-codebase-searcher to gather information, context, do research and verifying assumptions. This is important!
> Always use the @agent-test-writer-fixer subagent for writing tests, fixing test failures, and debugging test issues.
> Always give subagents small isolated tasks, never more than fixes for one file at a time.
> Always deploy subagents in parallel, never sequentially. This means using ONE function call block to deploy all subagents simultaneously.

Implementation should be done by yourself! Write tests using the @agent-test-writer-fixer subagent AFTER implementation is complete.

## Critical Technical Details

### The Namespacing Trap
**YOU CANNOT PASS METADATA BETWEEN NODES**. With namespacing enabled, nodes write to isolated namespaces:
```python
# THIS WILL NOT WORK:
# HTTP writes to shared["http_id"]["response_encoding"]
# Write-file CANNOT see this

# USE SUFFIX CONVENTION INSTEAD:
shared["response"] = base64_string
shared["response_is_binary"] = True  # Same namespace!
```

### Binary Detection Patterns
```python
# HTTP: Check Content-Type
BINARY_CONTENT_TYPES = ["image/", "video/", "audio/", "application/pdf",
                        "application/octet-stream", "application/zip"]
is_binary = any(ct in content_type for ct in BINARY_CONTENT_TYPES)

# Files: Check extension first, catch decode errors
BINARY_EXTENSIONS = {'.png', '.jpg', '.pdf', '.zip'}
is_binary = Path(file).suffix.lower() in BINARY_EXTENSIONS
```

### Template Resolution Constraint
The template resolver at `src/pflow/runtime/template_resolver.py:284` calls `str()` on all values. We use base64 to avoid modifying this core system. The shared store CAN handle bytes - we're choosing base64 for safety.

## Critical Warnings from Experience

### The Type Guard is Already Added
InstrumentedWrapper already has type guards added to prevent the crash. Don't revert these changes at lines 774-775.

### response.text Corrupts Binary
NEVER use `response.text` for binary data - it attempts UTF-8 decode and corrupts the data. Always use `response.content` for binary.

### Binary Flags Are Required
Without `_is_binary` flags, write-file cannot distinguish base64 strings from regular text. The flag MUST be set for binary data to be decoded.

### The Real Test Is Spotify Workflow
Unit tests are good, but the actual validation is the Spotify workflow at `.pflow/workflows/spotify-art-generator.json`. It must successfully download and save album art images.

## Key Decisions Already Made

1. **Base64 encoding chosen over direct bytes** - Avoids template resolver modifications (33% overhead accepted)
2. **Explicit flags over auto-detection** - `_is_binary` suffix for deterministic behavior
3. **All 4 nodes must be updated** - Consistency across the system, not just HTTP/write-file
4. **50MB soft limit for binary files** - Log warning but don't fail
5. **Backward compatibility is mandatory** - Missing flags default to text mode
6. **No streaming/chunking in MVP** - All data in memory

**📋 Note on Specifications**: The specification file (`task-82-spec.md`) is the authoritative source. Follow it precisely - do not deviate from specified behavior, test criteria, or implementation requirements unless you discover a critical issue (in which case, document the deviation clearly or STOP and ask the user for clarification).

## Success Criteria

Your implementation is complete when:

- ✅ Spotify workflow successfully downloads and saves 4 album art images
- ✅ All 18 test criteria from the spec pass
- ✅ HTTP node correctly detects and encodes binary responses
- ✅ Write-file correctly decodes base64 and writes binary files
- ✅ Read-file correctly detects and encodes binary files
- ✅ Shell node handles binary stdout/stderr
- ✅ Backward compatibility maintained - text workflows unchanged
- ✅ `make test` passes with no regressions
- ✅ `make check` passes (linting, type checking)

## Common Pitfalls to Avoid

- **DON'T try to pass metadata between nodes** - Use suffix convention on same key
- **DON'T use response.text for binary** - Always use response.content
- **DON'T forget to set binary flags** - Required for proper decoding
- **DON'T modify template resolver** - Use base64 to work within constraints
- **DON'T skip backward compatibility** - Missing flags must default to text
- **DON'T add features beyond spec** - No streaming, no size enforcement
- **DON'T test with mock data only** - Run the actual Spotify workflow

## 📋 Create Your Implementation Plan FIRST

Before writing any code, you MUST create a comprehensive implementation plan. This is not optional - it's a critical step that will save hours of rework and prevent subagents from conflicting.

### Why Planning Matters

1. **Prevents duplicate work and conflicts**: Multiple subagents won't edit the same files
2. **Identifies dependencies**: Discover what needs to be built in what order
3. **Optimizes parallelization**: Know exactly what can be done simultaneously
4. **Surfaces unknowns early**: Find gaps before they block implementation

### Step 1: Context Gathering with Parallel Subagents

Start by deploying parallel subagents to gather ALL necessary context:

```markdown
## Context Gathering Tasks (Deploy in Parallel)

1. **Current Binary Handling Analysis**
   - Task: "Analyze how src/pflow/nodes/http/http.py currently handles responses and identify exact locations for binary detection"
   - Task: "Examine src/pflow/nodes/file/write_file.py to understand current write modes and parameter handling"

2. **Test Structure Discovery**
   - Task: "Analyze tests/test_nodes/test_http/ structure and identify where to add binary tests"
   - Task: "Find existing integration tests that combine HTTP and write-file nodes"

3. **Interface Documentation Patterns**
   - Task: "Extract the Interface documentation pattern from existing nodes to ensure consistency"
   - Task: "Identify how union types are documented in node interfaces"

4. **Workflow Testing Setup**
   - Task: "Analyze .pflow/workflows/spotify-art-generator.json structure and identify the failing nodes"
   - Task: "Find how to run specific workflows in tests"
```

### Step 2: Write Your Implementation Plan

Create your plan at: `.taskmaster/tasks/task_82/implementation/implementation-plan.md`

Your plan should include:

1. **Comprehensive task breakdown** - Every file to create/modify
2. **Dependency mapping** - What must be done before what
3. **Subagent task assignments** - Who does what, ensuring no conflicts
4. **Risk identification** - What could go wrong and mitigation strategies
5. **Testing strategy** - How you'll verify each component works

### Subagent Task Scoping Guidelines

**✅ GOOD Subagent Tasks:**
```markdown
- "test-writer-fixer: Write unit tests for HTTP binary response handling in test_http_binary.py"
- "test-writer-fixer: Create integration test for download-and-save workflow with binary files"
- "pflow-codebase-searcher: Find all places where response.text is used in HTTP node"
```

**❌ BAD Subagent Tasks:**
```markdown
- "Implement all binary support" (too broad)
- "Fix everything related to binary" (too vague)
- "Update all nodes" (multiple agents will conflict)
```

## Your Implementation Order

### 0. Create Progress Log (FIRST!)

Create and continuously update: `.taskmaster/tasks/task_82/implementation/progress-log.md`

```markdown
# Task 82 Implementation Progress Log

## [Timestamp] - Starting Implementation
Reading epistemic manifesto and understanding the approach...
```

**Update this file AS YOU WORK** - every discovery, every bug, every insight!

### Implementation Steps

1. Verify InstrumentedWrapper type guards are in place
2. Implement HTTP node binary detection and encoding
3. Implement write-file base64 decoding and binary mode
4. Implement read-file binary detection and encoding
5. Implement shell binary stdout/stderr handling
6. Write comprehensive unit tests for each node
7. Create integration tests for binary workflows
8. Test with Spotify workflow end-to-end
9. Verify backward compatibility with existing tests
10. Update all Interface documentation

## Real-Time Learning Capture

**AS YOU IMPLEMENT**, continuously append to your progress log:

```markdown
## [Timestamp] - [What I'm trying]
Attempting to add binary detection to HTTP node...

Result: Content-Type detection working
- ✅ What worked: Substring match for "image/" catches all image types
- ❌ What failed: Initial attempt used response.text
- 💡 Insight: Must use response.content for binary

Code that worked:
```python
if any(ct in content_type for ct in BINARY_CONTENT_TYPES):
    response_data = response.content  # bytes
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
- Original plan: Auto-detect base64 in write-file
- Why it failed: Too fragile, false positives
- New approach: Require explicit _is_binary flag
- Lesson: Explicit is better than implicit for binary detection
```

## Test Creation Guidelines

**Use the `test-writer-fixer` subagent**: Deploy this specialized agent for all test tasks - it writes tests that catch real bugs, not just achieve coverage. Also use it for a final test review after implementation.

**Core Principle**: "Test what matters"

**Focus on quality over quantity**:
- Test public interfaces and critical paths
- Test edge cases where bugs typically hide
- Create integration tests when components interact
- Document only interesting test discoveries in your progress log

**What to test**:
- **Binary detection**: Each node correctly identifies binary content
- **Encoding/decoding**: Base64 conversion preserves exact bytes
- **Flag handling**: Missing flags default to text mode
- **Integration**: Binary data flows correctly through workflows
- **Real workflow**: Spotify workflow successfully downloads images

**What NOT to test**:
- Simple getters/setters
- Configuration loading
- Framework code
- Internal helper functions (unless complex)

**Progress Log - Only document testing insights**:
```markdown
## 14:50 - Testing revealed edge case
Binary detection failed for "application/json; charset=utf-8"
because substring match caught "application". Fixed by
checking for "application/json" explicitly first.
```

**Remember**: Quality tests that catch real bugs > many trivial tests

## What NOT to Do

- **DON'T** modify template resolver even though it seems like the "right" fix
- **DON'T** try to pass metadata between nodes through shared store
- **DON'T** use response.text for binary data
- **DON'T** forget backward compatibility for text workflows
- **DON'T** add streaming or chunking - keep it simple
- **DON'T** enforce size limits - just log warnings
- **DON'T** skip the Spotify workflow test

## Getting Started

1. Create progress log and implementation plan FIRST
2. Deploy context gathering subagents in parallel
3. Start with HTTP node - it's the entry point for binary data
4. Test frequently with small binary files
5. Run Spotify workflow as final validation

## Final Notes

- The handover memo contains critical discoveries about namespacing - READ IT
- Base64 overhead is acceptable for the use cases
- The crash is already fixed with type guards - focus on binary support
- Test with real files, not just mock data
- Document every discovery in your progress log

## Remember

You're implementing a foundational feature that enables real-world workflows with binary data. The base64 approach is pragmatic - we're working around a single line in template resolution rather than risking core system changes. When the Spotify workflow successfully downloads and saves album art, you'll have unlocked a major capability for pflow users.

The shared store CAN handle bytes perfectly - we're choosing base64 for safety and compatibility. Trust the research that went into this decision.

Good luck! This feature transforms pflow from text-only to a system that handles real-world data.