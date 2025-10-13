# MCP Server Utils

## Purpose

Security and convenience layer between MCP services and core pflow. Three modules with single responsibilities:

- **errors.py** - Sanitize sensitive data (API keys, tokens) before returning to LLMs
- **resolver.py** - Unified workflow loading (handles dict/library name/file path)
- **validation.py** - Security validation (parameters, paths, dummy values for testing)

## resolver.py - Workflow Resolution

**Handles three input types:**

```python
resolve_workflow(workflow) -> (workflow_ir | None, error | None, source)

# 1. Dict → Use as IR directly
workflow = {"nodes": [...]}  # → (ir, None, "direct")

# 2. String → Try as library name
workflow = "fix-issue"  # → (ir, None, "library")

# 3. String → Try as file path
workflow = "./my-workflow.json"  # → (ir, None, "file")

# 4. Not found → Return suggestions
workflow = "fx"  # → (None, "Not found: 'fx'\n\nDid you mean:\n  - fix-issue", "")
```

**Suggestion mechanism:**
- Uses `find_similar_items()` from core (substring matching, not fuzzy)
- Returns top 5 matches sorted by length
- Always provides actionable guidance

**Security note:** File reads have NO path validation. Design decision: "user is reading their own files on their own machine" (local MCP server = trusted environment).

## validation.py - Security Boundaries

### 1. validate_execution_parameters()

**Three-layer protection:**

```python
# Layer 1: Parameter name security (delegates to core)
from pflow.core.validation_utils import is_valid_parameter_name
# Blocks: $, |, >, <, &, ;, spaces, quotes
# Allows: hyphens, dots, numbers at start

# Layer 2: Size limits (DoS prevention)
if len(json.dumps(params)) > 1024 * 1024:  # 1MB max
    return False, "Parameters too large"

# Layer 3: Code injection detection
suspicious_patterns = [
    r"__import__", r"eval\s*\(", r"exec\s*\(",
    r"compile\s*\(", r"globals\s*\(", r"locals\s*\("
]
```

**Used by:** ExecutionService._resolve_and_validate_workflow()

### 2. generate_dummy_parameters()

**Creates placeholders for validation without real values:**

```python
inputs = {"api_key": {"type": "string"}, "repo": {"type": "string"}}
dummy = generate_dummy_parameters(inputs)
# Result: {"api_key": "__validation_placeholder__", "repo": "__validation_placeholder__"}

# Enables template validation without exposing real keys
WorkflowValidator.validate(workflow_ir, extracted_params=dummy)
```

**Why this matters:** Templates like `${api_key}` resolve successfully during validation without requiring actual API keys.

**Used by:** ExecutionService.validate_workflow()

### 3. validate_file_path()

**Path traversal prevention:**
- Blocks: `..`, `~`, null bytes
- Optionally blocks: absolute paths (`/`, `C:\`)
- Resolution check: ensures path stays within cwd

**Status:** Function exists but **never called** in codebase (resolver.py doesn't use it).

## errors.py - Sensitive Data Protection

**Purpose:** Redact sensitive data before returning to LLMs.

**Pattern:**
```python
def sanitize_parameters(params: dict[str, Any]) -> dict[str, Any]:
    # 1. Sensitive key detection (19 keywords from core/security_utils)
    if any(sensitive in key.lower() for sensitive in SENSITIVE_KEYS):
        sanitized[key] = "<REDACTED>"

    # 2. Length-based truncation (potential keys/tokens)
    elif isinstance(value, str) and len(value) > 100:
        sanitized[key] = value[:20] + "...<truncated>"

    # 3. Recursive for nested dicts
    elif isinstance(value, dict):
        sanitized[key] = sanitize_parameters(value)
```

**Sensitive keywords** (from `pflow.core.security_utils.SENSITIVE_KEYS`):
- password, token, api_key, secret, auth, credential
- private_key, access_key, client_secret, bearer
- authorization, jwt, session_id, cookie, passphrase

**Status:** Function exists but **never called** in services layer. This is a **security gap** - sensitive data may leak in error messages.

## Integration with Core

**Strategic delegation pattern** - MCP utils wrap core utilities:

```python
# validation.py delegates to core
from pflow.core.validation_utils import is_valid_parameter_name

# resolver.py uses core suggestions
from pflow.core.suggestion_utils import find_similar_items

# errors.py uses core security keywords
from pflow.core.security_utils import SENSITIVE_KEYS
```

**Why this works:** CLI/MCP share validation logic (single source of truth), core improvements auto-propagate.

## Critical Patterns

### Pattern 1: Helpful Error Messages

All failures include actionable guidance:

```python
# ✅ Good
"Workflow not found: 'fix'\n\nDid you mean one of these?\n  - fix-issue\n  - fix-bug"

# ❌ Bad
"Workflow not found: fix"
```

### Pattern 2: Progressive Security

Multiple validation layers catch different attack vectors:

```python
# In ExecutionService._resolve_and_validate_workflow()
# 1. Resolve workflow (source validation)
workflow_ir, error, source = resolve_workflow(workflow)

# 2. Validate parameters (injection protection)
is_valid, error = validate_execution_parameters(parameters)

# 3. Sanitize on error (redact sensitive data) - NOT IMPLEMENTED
```

### Pattern 3: Stateless Pure Functions

All utilities are pure functions with no side effects:
- Thread-safe by default
- Easy to test (no mocking needed)
- Composable with core utilities

## Common Pitfalls

### Pitfall 1: Assuming Path Validation

**Problem:** File reads in resolver.py have no path validation

```python
# Current behavior (NO validation)
path = Path(workflow)
if path.exists():
    workflow_ir = json.loads(path.read_text())  # Reads any accessible file

# validate_file_path() exists but is never called
```

**Rationale:** Local MCP server = trusted environment. Re-evaluate if adding remote MCP support.

### Pitfall 2: Skipping Parameter Validation

**Problem:** Only ExecutionService validates parameters, other entry points may not

```python
# ✅ ExecutionService does validation
is_valid, error = validate_execution_parameters(parameters)

# ⚠️  Check if new service methods need validation too
```

### Pitfall 3: Forgetting Dummy Parameters Break Validation

**Problem:** Templates fail validation without parameter values

```python
# ❌ Templates unresolved
WorkflowValidator.validate(workflow_ir)  # ${api_key} → error!

# ✅ Use placeholders
dummy = generate_dummy_parameters(workflow_ir.get("inputs", {}))
WorkflowValidator.validate(workflow_ir, extracted_params=dummy)  # ${api_key} → __validation_placeholder__
```

## Security Gaps

**Current implementation has gaps:**

1. **errors.py unused** - `sanitize_parameters()` never called in services
2. **Path validation unused** - `validate_file_path()` never called in resolver
3. **Partial parameter validation** - Only execution path validates, validation/save may not

**Impact:** Sensitive data may leak in error messages, but MCP runs locally (low risk).

**Recommendation:** Either implement sanitization throughout or remove dead code.

## When Adding New Utilities

**Ask these questions:**
1. Does core already provide this? (avoid duplication)
2. Should this be in core? (if CLI needs it too)
3. Is this MCP-specific? (then utils is correct place)

**Pattern to follow:**
```python
# Import core utilities
from pflow.core.X import Y

# Add MCP-specific logic
def mcp_specific_wrapper(data):
    # Validate/transform for MCP context
    validated = Y(data)
    # Add MCP-specific handling
    return format_for_mcp(validated)
```
