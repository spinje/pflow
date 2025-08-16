# Template Variable Ambiguity with Dots

## Problem Statement

The current template variable system has a fundamental ambiguity when dots appear in parameter values, particularly in filenames. The parser cannot reliably distinguish between:

1. **Path traversal dots**: `${config.data}` accessing a nested field
2. **Literal dots**: `${filename.json}` where `.json` is a file extension

### Examples of Ambiguity

```bash
# Ambiguous case 1
--path=${config.data.json}
# Is this:
#   - Variable: ${config.data.json} (treating 'json' as a nested field)?
#   - Variable: ${config.data} with literal '.json' extension?
#   - Variable: ${config} with literal '.data.json'?

# Ambiguous case 2
--path=${api.response.data.xml}
# Multiple valid interpretations possible

# Ambiguous case 3
--path=report-${date.csv}
# This works only because 'csv' starts with 'c' (valid identifier)
# But conceptually '.csv' should be literal
```

## Current Implementation Behavior

The regex pattern `\$([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)` greedily matches valid identifiers after dots:

- `${config.data.json}` → Entire string treated as variable path (incorrect for file extension)
- `${config.data}.123` → Treated as `${config.data}` (stops at invalid identifier)
- `${report.csv}` → Entire string treated as variable path (incorrect)

This causes problems when users expect `.json`, `.csv`, `.md` etc. to be literal file extensions.

## Why This Must Be Fixed

### 1. Violates User Expectations
Developers universally expect file extensions to be literal:
```bash
# Users expect this to work:
write-file --path=report-${date.pdf}
# They expect: report-2024-01-31.pdf
# They get: Error - no variable named "date.pdf"
```

### 2. Forces Awkward Workarounds
The MVP workaround requires using complete paths as single variables:
```json
// Forced to do this:
{"path": "${output_file}"}  // where output_file = "report-2024.pdf"

// Instead of natural composition:
{"path": "report-${date.pdf}"}
```

### 3. Limits Template Expressiveness
Cannot naturally combine variables with extensions:
```bash
# These patterns should work but don't:
--output=${build_dir}/app-${version.jar}
--report=analysis-${timestamp.html}
--config=${env.settings.yaml}
```

### 4. Inconsistent with Shell Conventions
Shell variable expansion handles this correctly:
```bash
# Shell clearly distinguishes:
echo "file-${date}.txt"  # Variable is 'date', '.txt' is literal
```

## Proposed Solution for v2.0

### Option 1: Explicit Delimiters (Recommended)
Support curly braces for clear boundaries:
```bash
--path=${config.data}.json  # Clear: variable ends at }
--path=report-${date}.pdf   # Unambiguous
--path=${api.response.data}.xml  # Explicit boundary
```

### Option 2: Context-Aware Parsing
In parameter contexts ending with known file extensions, treat them as literal:
```python
KNOWN_EXTENSIONS = ['.json', '.xml', '.pdf', '.md', '.txt', ...]
# If parameter ends with known extension, don't include it in variable
```

### Option 3: Escape Sequences
Allow escaping to force literal interpretation:
```bash
--path=${config.data}\.json  # \. forces literal dot
```

## Implementation Priority

**HIGH PRIORITY** - This issue:
- Affects common use cases (file operations)
- Causes user confusion
- Forces unnatural workflow design
- Has clear solution patterns from other tools

## Migration Path

1. **v1.x**: Document limitation, recommend workarounds
2. **v2.0**: Implement curly brace syntax `${var}`
3. **v2.x**: Deprecate ambiguous syntax, warn users
4. **v3.0**: Remove support for ambiguous patterns

## Current Workarounds (MVP)

Until fixed, users should:

1. **Use complete paths as variables**:
   ```json
   {"path": "${output_file}"}  // output_file includes extension
   ```

2. **Use simple variables without dots**:
   ```json
   {"path": "report-${date.md}"}  // Works if 'date' has no dots
   ```

3. **Avoid path variables in filenames**:
   ```json
   // Don't: "data-${config.version.json}"
   // Do: "${output_path}"
   ```

## Related Issues

- Template array indexing (`${items}[0]`) - not supported
- Template string interpolation (`prefix_${var}_suffix`) - not supported
- Template expressions (`${count} + 1`) - not supported

All of these could be addressed with a comprehensive template syntax redesign in v2.0.

## References

- Current implementation: `src/pflow/runtime/template_resolver.py`
- Similar solutions: Bash `${var}`, Make `$(var)`, Ansible `{{var}}`
- Task 17 discoveries: Ambiguity found during planner implementation

---

*Issue discovered: 2024-01-31 during Task 17 implementation*
*Priority: HIGH - Affects core usability*
*Target: v2.0 release*
