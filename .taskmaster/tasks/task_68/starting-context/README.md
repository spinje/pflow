# Task 68: Implementation Guide

## Overview

This directory contains the complete specification for implementing Task 68: Refactor RuntimeValidation and Workflow Execution. All specifications have been verified through comprehensive codebase analysis.

## 📋 Implementation Order

### Step 1: Read Architecture Overview
Start with `master-architecture-spec.md` to understand the overall vision and key decisions.

### Step 2: Implement Phase 1 - Foundation
Follow `phase-1-foundation-spec.md` to:
- Extract WorkflowExecutorService from CLI
- Create display abstractions
- Refactor CLI to thin pattern
- Ensure all tests pass before proceeding

### Step 3: Implement Phase 2 - Repair Service
Follow `phase-2-repair-spec.md` to:
- Extend InstrumentedNodeWrapper with checkpoint tracking
- Remove RuntimeValidationNode from planner
- Implement repair service with resume capability
- Update tests for 11-node planner

### Step 4: Read Supporting Documentation
- `research-findings.md` - Deep technical insights and gotchas

## ✅ Key Verifications

All critical assumptions have been verified:
- InstrumentedNodeWrapper is ALWAYS outermost (compiler.py:571) ✅
- WorkflowExecutorService does NOT exist (create from scratch) ✅
- `shared["__execution__"]` is available for checkpoint data ✅
- All line numbers have been verified and updated in specs ✅

## 🎯 Success Criteria

1. **Phase 1**: No user-visible changes, all tests pass
2. **Phase 2**: Planner has 11 nodes, repair works, no duplicate execution
3. **Overall**: CLI reduced to ~200 lines, self-healing workflows enabled

## ⏱️ Estimated Timeline

- Phase 1: 6-8 hours
- Phase 2: 8-10 hours
- Testing: 4-6 hours
- **Total**: ~20 hours

## 🚨 Important Notes

- **Line numbers in specs are VERIFIED** - Use them with confidence
- **Handler signatures must be preserved EXACTLY** - Parameter order matters
- **Intermediate function must be kept** - `_execute_workflow_and_handle_result`
- **Test after each phase** - Phase 1 must work standalone
- **Stop after each phase** - Do not try to do both phases at once. Stop and wait for user feedback and review before proceeding.

## 📁 Files in this Directory

- `master-architecture-spec.md` - Overall vision and architecture
- `phase-1-foundation-spec.md` - Extract services, create abstractions
- `phase-2-repair-spec.md` - Implement repair with resume
- `research-findings.md` - Technical insights from codebase analysis
- `README.md` - This file
- `task-68-handover.md` - Handover document with hard to uncover insights and gotchas

---

Ready for implementation. Start by reading all the documents in this directory then wait for the users instructions.