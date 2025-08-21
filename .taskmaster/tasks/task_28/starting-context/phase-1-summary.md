# Task 28 - Phase 1 Summary: Discovery Prompt Improvement

## What Was Completed

### Problem Statement
- Discovery prompt had 52.6% accuracy
- High false positive rate (matching "send email", "deploy to production")
- Tests focused on confidence scores instead of decisions

### Root Cause Analysis
The investigation revealed three layers of problems:

1. **Architectural Issue**: Rich metadata was being generated but not saved
2. **Context Issue**: Discovery only saw workflow names and descriptions
3. **Prompt Issue**: Vague and contradictory instructions

### Solutions Implemented

#### 1. Architecture Fix
**Problem**: Metadata was lost between generation and storage

**Solution**: Clean separation of concerns
- Kept metadata OUT of IR schema (IR = pure structure)
- Updated WorkflowManager to accept metadata as separate parameter
- Modified CLI to pass metadata directly to WorkflowManager

**Files Modified**:
- `src/pflow/core/ir_schema.py` - Removed metadata field
- `src/pflow/core/workflow_manager.py` - Added metadata parameter to save()
- `src/pflow/cli/main.py` - Pass metadata separately, not embedded in IR

#### 2. Context Enhancement
**Problem**: LLM only saw names and descriptions

**Solution**: Rich context with multiple signals
- Added node flow display: `github-list-issues → llm → write-file → github-create-pr`
- Added capabilities: What the workflow can do
- Added use cases: When to use it
- Removed keywords from display (kept internal)

**Files Modified**:
- `src/pflow/planning/context_builder.py` - Added _build_node_flow(), enhanced display format

**New Context Format**:
```
**1. `generate-changelog`** - Generate changelog from GitHub issues and create PR
   **Flow:** `github-list-issues → llm → write-file → github-create-pr`
   **Can:** GitHub integration, Issue fetching, Changelog generation
   **For:** Release preparation, Version updates
```

#### 3. Prompt Improvement
**Problem**: Contradictory and vague instructions

**Solution**: Clear, structured decision process
- Changed role: "discovery system" → "workflow router"
- Made node flow the PRIMARY evidence
- Added step-by-step decision process
- Included concrete examples
- Clear principles (5 simple rules)

**Files Modified**:
- `src/pflow/planning/prompts/discovery.md` - Complete rewrite with structured approach

#### 4. Test Suite Refinement
**Problem**: 19 tests with redundancy, wrong focus

**Solution**: Quality over quantity
- Reduced from 19 → 12 high-quality tests
- Removed 5 redundant performance tests
- Focus on decision correctness, not confidence scores
- Clear categories: Core Matches, Core Rejections, Data Distinctions, Language Handling

**Files Modified**:
- `tests/test_planning/llm/prompts/test_discovery_prompt.py` - Refined test cases and scoring

### Results Achieved

| Metric | Before | After |
|--------|--------|-------|
| Accuracy | 52.6% | ~83% |
| Test Count | 19 | 12 |
| Test Focus | Confidence scores | Decision correctness |
| Context | Names + descriptions | Names + descriptions + flows + capabilities + use cases |
| Architecture | Metadata lost | Metadata properly stored and used |

### Key Lessons for Other Prompts

1. **Verify Data Flow First**: The best prompt can't work without data
2. **Architecture Matters**: Clean separation of concerns prevents issues
3. **Show, Don't Tell**: Node flows show exactly what happens
4. **Test What Matters**: Decision correctness is key, not confidence
5. **Context is Critical**: Rich, structured information enables good decisions

## Next Agent Actions

For Phase 2, the next agent should:

1. **Choose next prompt** (suggest: component_browsing.md)
2. **Follow implementation-steps.md** pattern
3. **Update progress-log.md** as they work
4. **Apply lessons from Phase 1**

The pattern is established, the tools are ready, and the path forward is clear.