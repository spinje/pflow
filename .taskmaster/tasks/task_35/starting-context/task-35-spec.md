# Feature: migrate_template_syntax

## Objective

Replace $variable syntax with ${variable} syntax across codebase.

## Requirements

- Must update regex patterns in template_resolver.py and template_validator.py
- Must update template replacement logic for unresolved variables
- Must update all planner prompt examples
- Must update all test files and documentation
- Must preserve path traversal capability
- Must implement escaped syntax handling
- Must allow hyphens in variable names
- Must delete existing saved workflows

## Scope

- Does not maintain backward compatibility
- Does not migrate saved workflows
- Does not modify prompt template system ({{variable}})
- Does not support numeric indices in paths
- Does not create migration scripts

## Inputs

- None

## Outputs

Side effects:
- Modified regex patterns in 2 core files
- Updated template replacement logic in template_resolver.py
- Modified 12+ examples in workflow_generator.md
- Updated 50+ source files containing template references
- Modified 230+ documentation occurrences
- Updated all test files
- Deleted saved workflows in ~/.pflow/workflows/

## Structured Formats

```json
{
  "old_syntax": {
    "pattern": "$variable",
    "regex": "(?<!\\$)\\$([a-zA-Z_]\\w*(?:\\.[a-zA-Z_]\\w*)*)(?=\\s|$|[^\\w])",
    "escaped": "$$variable",
    "escaped_output": "$$variable"
  },
  "new_syntax": {
    "pattern": "${variable}",
    "regex": "(?<!\\$)\\$\\{([a-zA-Z_][\\w-]*(?:\\.[a-zA-Z_][\\w-]*)*)\\}",
    "escaped": "$${variable}",
    "escaped_output": "${variable}"
  }
}
```

## State/Flow Changes

- None

## Constraints

- Must complete atomically without intermediate dual-syntax support
- Must preserve all current functionality
- Must maintain test coverage

## Rules

1. Update TEMPLATE_PATTERN in template_resolver.py:24 to `r"(?<!\$)\$\{([a-zA-Z_][\w-]*(?:\.[a-zA-Z_][\w-]*)*)\}"`
2. Update _PERMISSIVE_PATTERN in template_validator.py:338 to `r"\$\{([a-zA-Z_][\w-]*(?:\.[\w-]*)*)\}"`
3. Change template replacement in template_resolver.py:181 from `f"${var_name}"` to `f"${{{var_name}}}"`
4. Change template replacement in template_resolver.py:192 from `f"${var_name}"` to `f"${{{var_name}}}"`
5. Update log messages in template_resolver.py:183,194,200 from `${var_name}` to `${{{var_name}}}`
6. Update docstring examples in template_resolver.py:137-142 from `$variable` to `${variable}`
7. Update error messages in template_validator.py:218,245,253,259,260,264,283,291,292,296 from `${template}` to `${{{template}}}`
8. Update error suggestions in planning/nodes.py:1123,1125 from `${param_name}` to `${{{param_name}}}`
9. Replace all `$variable` examples in workflow_generator.md with `${variable}` syntax
10. Update all test assertions from `$variable` to `${variable}` syntax
11. Update all documentation examples from `$variable` to `${variable}`
12. Delete all files in ~/.pflow/workflows/ directory
13. Handle escaped syntax `$${variable}` to output literal `${variable}` via negative lookbehind

## Edge Cases

- Empty braces `${}` → invalid template
- Unclosed brace `${variable` → not matched as template
- Extra closing brace `${variable}}` → matches `${variable}` with trailing `}`
- Variable with hyphen `${user-id}` → valid template
- Nested braces `${${inner}}` → invalid template
- Path traversal `${node.field.subfield}` → valid template
- Escaped template `$${variable}` → outputs literal `${variable}`
- Adjacent templates `${var1}${var2}` → both resolve independently
- Template in middle of word `prefix${var}suffix` → resolves correctly

## Error Handling

- None

## Non-Functional Criteria

- Regex performance must not degrade
- Template resolution must remain O(n) complexity

## Examples

### Valid templates
```
${username}                    → resolves to username value
${node.field}                  → resolves to nested field
${user-id}                     → resolves with hyphen in name
$${escaped}                    → outputs literal "${escaped}"
file_${timestamp}.json         → resolves without ambiguity
${var1}_${var2}               → both variables resolve
```

### Invalid templates
```
$variable                      → not matched (old syntax)
${                            → not matched (unclosed)
${double..dot}                → invalid (double dots)
${123start}                   → invalid (starts with number)
```

## Test Criteria

1. Regex pattern matches `${variable}` but not `$variable`
2. Regex pattern matches `${user-id}` with hyphen
3. Template replacement outputs `${unresolved}` for unresolved variables
4. Escaped syntax `$${var}` outputs literal `${var}`
5. All workflow_generator.md examples use `${variable}` syntax
6. Error messages show `${variable}` in examples
7. Test files assert against `${variable}` patterns
8. Documentation shows `${variable}` in all examples
9. ~/.pflow/workflows/ directory is empty after deletion
10. Path traversal `${node.field}` resolves correctly
11. Empty braces `${}` are rejected as invalid
12. Unclosed brace `${var` does not match
13. Adjacent templates `${a}${b}` resolve independently
14. Template in word `pre${var}post` resolves correctly

## Notes (Why)

- Explicit boundaries eliminate parsing ambiguities with underscores and punctuation
- Aligns with bash, JavaScript, Docker template syntax conventions
- Simpler regex without complex lookarounds improves maintainability
- Clean slate approach avoids migration complexity for zero-user MVP
- Hyphen support enables common naming patterns like `${user-id}`

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1, 2                       |
| 2      | 1, 11                      |
| 3      | 3                          |
| 4      | 3                          |
| 5      | 3                          |
| 6      | 8                          |
| 7      | 6                          |
| 8      | 6                          |
| 9      | 5                          |
| 10     | 7                          |
| 11     | 8                          |
| 12     | 9                          |
| 13     | 4                          |

| Edge Case                    | Covered By Test Criteria # |
| ---------------------------- | -------------------------- |
| Empty braces                 | 11                         |
| Unclosed brace              | 12                         |
| Extra closing brace         | 1                          |
| Variable with hyphen        | 2                          |
| Nested braces               | 11                         |
| Path traversal              | 10                         |
| Escaped template            | 4                          |
| Adjacent templates          | 13                         |
| Template in middle of word  | 14                         |

## Versioning & Evolution

- v1.0.0 - Initial specification for template syntax migration

## Epistemic Appendix

### Assumptions & Unknowns

- Assumes no users have production workflows requiring migration
- Assumes hyphen support will not conflict with existing parsing logic
- Unknown if any third-party integrations depend on old syntax

### Conflicts & Resolutions

- Saved workflows use old syntax → Resolution: Delete all, users regenerate
- Two separate regex patterns must stay synchronized → Resolution: Update both atomically
- Prompt templates use {{variable}} → Resolution: Explicitly exclude from scope

### Decision Log / Tradeoffs

- Clean slate over migration: Chose simplicity since MVP has no users
- Escaped syntax `$${var}` over `\${var}`: Maintains consistency with current pattern
- Allow hyphens in names: Small complexity increase for significant usability gain
- Atomic migration over gradual: Avoids temporary dual-syntax complexity

### Ripple Effects / Impact Map

- Planner will generate new syntax after workflow_generator.md update
- All existing documentation becomes outdated until updated
- Test fixtures using old syntax will fail until updated
- Any uncommitted code with templates needs manual update

### Residual Risks & Confidence

- Risk: Missing template occurrences in obscure files - Mitigation: Comprehensive grep search
- Risk: Regex performance regression - Mitigation: Simpler pattern should be faster
- Confidence: High - Clean slate approach eliminates migration risks

### Epistemic Audit (Checklist Answers)

1. Assumed no production users need migration
2. Wrong assumption would require migration script implementation
3. Prioritized robustness via explicit boundaries over elegant backward compatibility
4. Every rule maps to test criteria and vice versa
5. Ripple effects touch planner, tests, docs but not core execution engine
6. Uncertainty low on implementation, medium on finding all occurrences; Confidence: High