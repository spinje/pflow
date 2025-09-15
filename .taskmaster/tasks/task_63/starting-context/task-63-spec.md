# Feature: pre_execution_risk_assessment

## Objective

Validate workflows for dangerous operations before execution.

## Requirements

- Must analyze workflow IR for risky command patterns
- Must prompt users for confirmation in interactive mode
- Must support automation bypass with --force flag
- Must persist risk acceptance decisions
- Must detect modifications to saved workflows

## Scope

- Does not evaluate runtime template values
- Does not monitor executing commands
- Does not provide sandboxing or containerization
- Does not protect against malicious actors
- Does not modify workflow execution behavior

## Inputs

- `ir_data`: dict[str, Any] - Workflow IR structure to analyze
- `registry`: Registry - Node registry for accessing node classes
- `force`: bool - Skip all risk prompts when True
- `accept_risk`: bool - Accept all risks without prompting when True
- `is_interactive`: bool - Whether running in interactive mode

## Outputs

Returns: list[RiskAssessment] - Identified risks with levels and descriptions

Side effects:
- Raises CriticalRiskError for CRITICAL level risks
- Updates settings.json with pattern approvals
- Updates workflow metadata with risk hash
- Displays risk warnings to stderr in interactive mode

## Structured Formats

```python
class RiskLevel(Enum):
    CRITICAL = "CRITICAL"  # Always block
    HIGH = "HIGH"          # Require confirmation
    MEDIUM = "MEDIUM"      # Warn only
    SAFE = "SAFE"          # No action

@dataclass
class RiskAssessment:
    level: RiskLevel
    node_id: str
    node_type: str
    pattern: str
    parameter_name: str
    description: str

# Node risk pattern declaration
RISK_PATTERNS: ClassVar[dict[str, list[str]]] = {
    "CRITICAL": [...],
    "HIGH": [...],
    "MEDIUM": [...]
}

# Settings persistence
{
    "risk_acceptance": {
        "approved_patterns": [
            {
                "pattern": str,
                "node_type": str,
                "approved_at": str,  # ISO 8601
                "expires_at": str | None
            }
        ],
        "denied_patterns": [...]
    }
}

# Workflow metadata
{
    "metadata": {
        "risk_approval": {
            "approved": bool,
            "risk_hash": str,  # SHA256 of risky operations
            "approved_at": str
        }
    }
}
```

## State/Flow Changes

- `unchecked` → `analyzed` when WorkflowRiskAnalyzer.analyze() completes
- `analyzed` → `approved` when user confirms risks
- `approved` → `expired` when approval timestamp exceeds expiry
- `approved` → `invalidated` when risk hash changes

## Constraints

- Risk analysis must complete in < 100ms for 100-node workflows
- Template variables normalized to wildcards for pattern matching
- Pattern approvals expire after 30 days by default
- Critical risks cannot be bypassed even with --force
- Risk hash computed only from risky operations

## Rules

1. Extract RISK_PATTERNS from node classes via registry
2. Normalize template variables to wildcards before pattern matching
3. Match patterns case-insensitively using substring search
4. Assign highest matching risk level per parameter
5. Deduplicate identical risks by (node_id, pattern, parameter_name)
6. Sort risks by level (CRITICAL first) then node_id
7. Raise CriticalRiskError immediately for CRITICAL risks
8. Check pattern approvals in settings.json before prompting
9. Skip expired approvals based on expires_at timestamp
10. Calculate risk hash from sorted risky operations only
11. Compare risk hash with workflow metadata for saved workflows
12. Invalidate approval if risk hash differs
13. Display risks to stderr in interactive mode
14. Prompt with [y/N/always/never] choices in interactive mode
15. Store "always" choices in settings.json with 30-day expiry
16. Store "never" choices in denied_patterns
17. Update workflow metadata with risk_approval on save
18. Fail in non-interactive mode without --force for HIGH risks
19. Skip all prompts when --force or --accept-risk is True
20. Cache approvals in memory for 5 minutes within session

## Edge Cases

- Empty workflow (no nodes) → return empty risk list
- Unknown node type → skip node silently
- Node without RISK_PATTERNS → skip node silently
- Malformed pattern in settings.json → skip pattern with warning
- Settings.json write failure → continue without persistence
- Non-TTY terminal → treat as non-interactive
- Template variable ${var} and $var → both normalize to *
- Wildcard pattern "*" → matches everything
- Circular workflow reference → process each node once
- Risk hash collision → include node IDs in hash input

## Error Handling

- Missing registry → raise ValueError with clear message
- Invalid risk level in RISK_PATTERNS → skip with warning
- JSON decode error in settings → create fresh settings
- File permission error on settings → log warning and continue
- Interrupted during prompt → treat as rejection

## Non-Functional Criteria

- Pattern compilation cached per analyzer instance
- Early return on first CRITICAL risk found
- Lazy loading of settings.json
- Atomic writes using temp file + rename
- Thread-safe settings updates

## Examples

```python
# Shell node with critical risk
ir_data = {
    "nodes": [{
        "id": "dangerous",
        "node_type": "shell",
        "config": {"command": "rm -rf /"}
    }]
}
# Raises: CriticalRiskError

# Template variable normalization
"sudo rm -rf ${path}" → matches "sudo " pattern (HIGH)

# Pattern approval
Continue? [y/N/always/never]: always
# Adds to settings.json:
{
    "pattern": "sudo systemctl restart nginx",
    "node_type": "shell",
    "approved_at": "2024-01-15T10:30:00Z",
    "expires_at": "2024-02-14T10:30:00Z"
}

# Risk hash change detection
Original: {"command": "sudo apt update"}
Modified: {"command": "sudo apt remove"}
# risk_hash changes → re-prompt required
```

## Test Criteria

1. Shell node with "rm -rf /" → CriticalRiskError raised
2. Shell node with "sudo command" → HIGH risk returned
3. Shell node with "echo hello" → empty risk list
4. Unknown node type "fake" → empty risk list
5. Node without RISK_PATTERNS → empty risk list
6. Template "${var}" in command → normalized to * for matching
7. Template "$var" in command → normalized to * for matching
8. Duplicate risks → deduplicated in output
9. Mixed risk levels → sorted CRITICAL, HIGH, MEDIUM
10. Pattern in approved_patterns → risk skipped
11. Expired approval (past expires_at) → risk not skipped
12. Pattern in denied_patterns → risk always shown
13. Risk hash unchanged → workflow approval valid
14. Risk hash changed → workflow approval invalid
15. Interactive mode + HIGH risk → prompt shown
16. Non-interactive + HIGH risk → error raised
17. --force flag + HIGH risk → no prompt
18. --accept-risk flag + HIGH risk → no prompt
19. CRITICAL risk + --force → still raises error
20. "always" response → pattern added to settings
21. "never" response → pattern added to denied list
22. Settings write failure → warning logged, continues
23. Empty workflow → empty risk list
24. Wildcard pattern "*" → matches any command
25. Session cache hit → no re-analysis for 5 minutes
26. Risk analysis time for 100 nodes → < 100ms
27. Atomic settings update → no partial writes
28. Circular workflow → each node analyzed once

## Notes (Why)

- Static analysis suffices because dangerous patterns are structural not data-dependent
- Three-tier persistence handles different workflow lifecycles appropriately
- Pattern-based approval works for planner-generated workflows that vary slightly
- Risk hash enables detection of modifications to saved workflows
- 30-day expiry balances convenience with security hygiene
- Session cache reduces prompts for rapid iteration
- CRITICAL risks unbypassable to prevent catastrophic accidents

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1, 2, 3                   |
| 2      | 6, 7                      |
| 3      | 1, 2                      |
| 4      | 9                         |
| 5      | 8                         |
| 6      | 9                         |
| 7      | 1, 19                     |
| 8      | 10, 11                    |
| 9      | 11                        |
| 10     | 13, 14                    |
| 11     | 13, 14                    |
| 12     | 14                        |
| 13     | 15                        |
| 14     | 15                        |
| 15     | 20                        |
| 16     | 21                        |
| 17     | 13                        |
| 18     | 16                        |
| 19     | 17, 18                    |
| 20     | 25                        |

## Versioning & Evolution

- v1.0.0 - Initial risk assessment implementation

## Epistemic Appendix

### Assumptions & Unknowns

- Assumes nodes will expose RISK_PATTERNS as class attributes
- Assumes settings.json is writable in user home directory
- Assumes 30-day expiry is reasonable default
- Unknown: optimal session cache duration (5 minutes chosen)
- Unknown: performance impact of pattern matching on large workflows

### Conflicts & Resolutions

- Runtime wrapping vs static analysis → Chose static (simpler, sufficient)
- Binary vs three-tier risk levels → Chose three-tier (better UX)
- Exact vs fuzzy pattern matching → Chose exact initially (simpler)
- User-specific vs system-wide settings → Chose user-specific (follows existing pattern)

### Decision Log / Tradeoffs

- Static analysis over runtime: Simpler implementation, covers 95% of cases
- Pattern approval over workflow approval for planner: Handles workflow variance
- Risk hash over full hash: Avoids false positives on benign changes
- 30-day expiry over forever: Balances convenience with security
- Substring matching over regex: Simpler, sufficient for current patterns

### Ripple Effects / Impact Map

- Shell node must expose existing DANGEROUS_PATTERNS as RISK_PATTERNS
- Claude_code node must expose DANGEROUS_BASH_PATTERNS similarly
- WorkflowValidator gains new validation phase
- CLI main.py gains --force and --accept-risk flags
- Settings.json schema extended with risk_acceptance
- Workflow metadata schema extended with risk_approval

### Residual Risks & Confidence

- Risk: Sophisticated pattern obfuscation bypasses detection; Confidence: High (acceptable for accident prevention)
- Risk: Settings corruption loses approvals; Confidence: Medium (recreate from scratch)
- Risk: Performance degradation on huge workflows; Confidence: High (100ms budget sufficient)
- Risk: User fatigue from repeated prompts; Confidence: Medium (mitigated by persistence)

### Epistemic Audit (Checklist Answers)

1. Assumed writable home directory for settings persistence
2. Read-only filesystem would prevent pattern approval storage
3. Prioritized robustness (static analysis) over elegance (runtime interception)
4. All rules mapped to tests, all tests cover rules
5. Touches validation, CLI, settings, and node implementations
6. Uncertainty on optimal cache/expiry durations; Confidence: High overall