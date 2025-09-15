# Task 63 Implementation Handoff: Pre-Execution Risk Assessment System

## 🎯 Critical Architectural Insight - READ THIS FIRST

**The user initially asked about shell command risk blocking, which led to discovering we need a comprehensive risk assessment system.** But here's the crucial insight that will save you hours:

**DO NOT implement runtime wrappers or complex interception mechanisms.** We spent significant time exploring a `RiskAssessmentWrapper` approach that would intercept node execution at runtime. The user correctly pushed back - this is over-engineering. The breakthrough realization: **dangerous command structures are static**. Even with template variables like `rm -rf ${path}`, the risky part is `rm -rf`, not the path value. This means **static pre-execution analysis is sufficient**.

## 🔴 The Persistence Gap That Changed Everything

The original design only handled one-time prompts. The user asked the critical question: "where are we saving the responses if the user wants to allow something forever?" This exposed a fundamental gap that requires a **three-tier persistence system**:

1. **Pattern-based approval** in `~/.pflow/settings.json` - for trusted operations
2. **Workflow-level approval** in workflow metadata - for saved workflows
3. **Session cache** in memory - for rapid re-runs

Without this, the system would be unusable - constantly re-prompting for the same operations.

## 🧩 Workflow Identity Crisis You Must Understand

Different workflow types have fundamentally different identity characteristics:

- **Planner-generated workflows**: Always slightly different even for identical requests. Can't track identity. Must rely on pattern matching.
- **Saved workflows**: Have stable identity via filename. Use risk hash in metadata.
- **Modified workflows**: The risk hash MUST detect changes and force re-validation.
- **Piped workflows**: No persistence possible, always prompt.

This isn't a minor detail - it's core to the design. The `calculate_risk_hash()` function must hash ONLY the risky operations, not the entire workflow, or you'll get false positives on benign changes.

## ⚡ Existing Patterns You MUST Leverage

**Critical**: The shell node (`src/pflow/nodes/shell/shell.py`) ALREADY HAS risk patterns:
- `DANGEROUS_PATTERNS` (lines 51-80) - these become CRITICAL risks
- `WARNING_PATTERNS` (lines 83-92) - these become HIGH risks

Don't duplicate these! The design intentionally has nodes expose their existing patterns via a new `RISK_PATTERNS` class attribute. This keeps knowledge with the implementation.

Similarly, `claude_code.py` has `DANGEROUS_BASH_PATTERNS` and `delete_file.py` requires `confirm_delete`. Reuse this existing security knowledge.

## 🚨 Validation Integration Point - Don't Get This Wrong

Risk assessment is NOT a separate system. It's a new phase in the existing `WorkflowValidator`:

```python
# In src/pflow/core/workflow_validator.py
def validate(self, ir_data, registry):
    self._validate_structure(ir_data)
    self._validate_templates(ir_data)
    self._validate_node_types(ir_data, registry)
    self._validate_risks(ir_data, registry)  # NEW - just another validation phase
```

The insertion point in CLI is critical: **AFTER compilation but BEFORE execution** in `execute_json_workflow()` around line 1410. This gives you access to the compiled workflow, registry, and OutputController.

## 💡 Pattern Matching Subtleties

When implementing `_matches_pattern()`:
- Normalize template variables to wildcards: `${anything}` → `*`
- Use case-insensitive substring matching for most patterns
- The wildcard pattern `"*"` (used by delete_file) matches everything
- Don't try to evaluate template values - that's a runtime concern

## 🎮 Interactive Mode Detection

Use the existing `OutputController` class - don't reinvent:
- `output_controller.is_interactive()` handles all the edge cases
- Respects `-p/--print` flag, JSON mode, TTY detection
- Already battle-tested

## ⚠️ The "Always/Never" UI Pattern

The user expects more than y/n prompts. Implement:
```
Continue? [y/N/always/never]:
```

- `always` → Add pattern to approved list with 30-day default expiry
- `never` → Add to denied patterns (always prompt)
- Store in existing `settings.json` structure
- Use `click.Choice` for validation

## 🔒 Critical Risks Must Be Unbypassable

Even with `--force`, CRITICAL risks (rm -rf /, fork bombs) must ALWAYS block execution. This is non-negotiable. The `CriticalRiskError` should be raised during validation, not CLI handling.

## 📁 Files and Patterns to Study

**Essential reads before implementing:**
1. `/Users/andfal/projects/pflow/src/pflow/nodes/shell/shell.py` - Lines 51-92, 191-208 for existing patterns and validation
2. `/Users/andfal/projects/pflow/src/pflow/core/workflow_validator.py` - Understand the validation pipeline
3. `/Users/andfal/projects/pflow/src/pflow/cli/main.py` - Line ~1410 for insertion point
4. `/Users/andfal/projects/pflow/src/pflow/core/settings.py` - For settings structure
5. `/Users/andfal/projects/pflow/src/pflow/core/output_controller.py` - For interactive mode detection

**Documentation created during design:**
- `/Users/andfal/projects/pflow/scratchpads/risk-acceptance-architecture/SPECIFICATION.md` - Formal spec
- `/Users/andfal/projects/pflow/scratchpads/risk-acceptance-architecture/IMPLEMENTATION_PLAN.md` - Step-by-step plan
- `/Users/andfal/projects/pflow/scratchpads/risk-acceptance-architecture/persistence-analysis.md` - Critical persistence insights

## 🐛 Edge Cases and Gotchas

1. **Template normalization**: Both `${var}` and `$var` syntax must be handled
2. **Risk deduplication**: Same pattern in multiple parameters shouldn't show twice
3. **Approval expiry**: Check expiry timestamps when loading approvals
4. **Atomic writes**: Settings updates must use temp file + rename pattern
5. **Non-TTY piped input**: Must detect and handle gracefully
6. **Empty workflows**: Don't crash on workflows with no nodes

## 🎯 Performance Constraints

- Risk analysis must complete in <100ms for 100-node workflows
- Compile regex patterns once, not per-node
- Use early returns in pattern matching
- Don't analyze nodes without RISK_PATTERNS attribute

## 🔄 Testing Priorities

The most critical test scenarios:
1. **Critical risks with --force** - Must still block
2. **Modified saved workflows** - Risk hash must detect changes
3. **Pattern approval persistence** - Actually saves and loads
4. **Template variable workflows** - Patterns still match
5. **Non-interactive mode** - Fails safely without --force

## 💭 User's Mental Model

The user thinks of this as "accident prevention", not security. They want:
- Protection from typos and mistakes
- Ability to trust frequently-used commands
- No interference with automation (--force flag)
- Clear communication about what's dangerous and why

They explicitly said they understand this won't stop malicious actors - it's about preventing "oh no, I just deleted production" moments.

## 🎬 Final Critical Insight

The entire conversation pivoted on the realization that **static analysis is sufficient**. Don't second-guess this - we explored runtime interception extensively and rejected it for good reasons. The simplicity of the final design is its strength.

---

**To the implementing agent**: Do not begin implementation immediately. Read through all the documentation, understand the existing patterns in the codebase, and confirm you understand the three-tier persistence model and workflow identity challenges. Say you're ready to begin only after you've absorbed this context.