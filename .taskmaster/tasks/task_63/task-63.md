# Task 63: Implement Pre-Execution Risk Assessment System for shell nodes

## ID
63

## Title
Implement Pre-Execution Risk Assessment System for shell nodes

## Description
Create a validation-phase risk assessment system that analyzes workflows for dangerous operations (rm -rf /, sudo commands, etc.) before execution begins. The system will prompt users for confirmation in interactive mode and support automation with --force flags, preventing accidental execution of destructive commands while maintaining backward compatibility.

## Status
not started

## Dependencies
None
<!-- This is a new validation layer that integrates with existing infrastructure -->

## Priority
high

## Details
The Risk Assessment System will provide pre-execution safety validation for pflow workflows by identifying potentially dangerous operations and requiring user confirmation before workflow execution begins. This addresses the critical need to prevent accidental system damage from commands like `rm -rf /` or unauthorized privilege escalation.

### Core Architecture
The system follows a validation-phase approach, adding risk assessment as a new validation step in the existing WorkflowValidator pipeline. This leverages existing patterns without requiring runtime changes.

### Key Design Decisions (MVP Approach)
- **Static analysis only** - Analyze command structure, not runtime values
- **Nodes own their risk knowledge** - Reuse existing DANGEROUS_PATTERNS from shell node
- **Three risk levels** - CRITICAL (always block), HIGH (require confirmation), MEDIUM (warn only)
- **Pattern-based persistence** - Store approved patterns in ~/.pflow/settings.json
- **Workflow-level approval** - Store risk approval in saved workflow metadata
- **No runtime overhead** - All analysis happens pre-execution

### Implementation Components
1. **Node Pattern Declaration** - Add RISK_PATTERNS class attribute to shell, claude_code, and delete_file nodes
2. **WorkflowRiskAnalyzer** - Core analysis engine that aggregates patterns from nodes
3. **Validation Integration** - New _validate_risks() phase in WorkflowValidator
4. **CLI Integration** - Add --force flag and interactive prompts
5. **Persistence Layer** - Three-tier system (pattern approval, workflow approval, session cache)

### User Experience
**Interactive Mode:**
- Display clear risk warnings with specific patterns identified
- Offer [y/N/always/never] options for pattern-based approval
- Store "always" approvals in settings.json with optional expiry

**Non-Interactive Mode:**
- Fail safely by default on HIGH risks
- Support --force flag for CI/CD automation
- Respect PFLOW_ACCEPT_RISK environment variable

**Critical Risks:**
- Always block execution (no override possible)
- Clear error message explaining the danger

### Technical Specifications
- Risk analysis must complete in <100ms for typical workflows
- Template variables treated as wildcards for pattern matching
- Risk hash calculation for saved workflows to detect modifications
- 30-day default expiry for pattern approvals
- Pattern matching is case-insensitive substring search

### Integration Points
- Extends existing WorkflowValidator without breaking changes
- Reuses OutputController for interactive mode detection
- Leverages existing click.confirm() patterns for prompts
- Integrates with existing settings.json structure

## Test Strategy
Comprehensive testing will ensure the risk assessment system works correctly across all scenarios:

### Unit Tests (test_risk_assessment.py)
- Pattern matching for each risk level (CRITICAL, HIGH, MEDIUM)
- Template variable handling (${var} treated as wildcards)
- Risk deduplication across multiple nodes
- Unknown node type handling
- Pattern expiry checking

### Integration Tests (test_risk_prompts.py)
- Interactive mode prompt acceptance/rejection
- Non-interactive mode failure without --force
- --force flag bypasses all prompts
- --accept-risk flag functionality
- CRITICAL risks always blocked (even with --force)
- Environment variable (PFLOW_ACCEPT_RISK) handling

### Persistence Tests
- Pattern approval storage and retrieval
- Workflow risk hash calculation and validation
- Approval expiry enforcement
- Settings.json atomic write safety

### End-to-End Tests
- Real shell commands with various risk levels
- Workflows with mixed risk levels
- Template-heavy workflows
- Saved workflow modification detection
- Performance validation (<100ms overhead)

---

*Session ID: da9eac43-be8c-4efd-a169-5682389cb709*