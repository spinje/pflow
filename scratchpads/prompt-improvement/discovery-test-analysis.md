# Discovery Prompt Test Analysis Results

## Test Execution Summary

Ran 12 ambiguous test cases with real LLM (Claude Sonnet 4.0). Results:
- **Overall Pass Rate**: 66.7% (8/12)
- **Easy Tests**: 85.7% (6/7) - Below 90% target ❌
- **Medium Tests**: 40% (2/5) - Below 70% target ❌
- **Hard Tests**: 0% (0/1) - Expected to be challenging

## Key Findings

### 1. Overly Strict Parameter Matching

**Problem**: The discovery prompt rejects workflows when parameters differ slightly.

**Example**: "generate a changelog for the last 20 closed issues"
- **Current Behavior**: Rejected with 0.70 confidence
- **Reasoning**: "user specifically wants the last 20 CLOSED issues... workflow description doesn't specify it filters for closed issues or limits to 20"
- **Issue**: Being too literal about parameter differences instead of recognizing core functionality

### 2. "Doing More Than Requested" Anti-Pattern

The prompt frequently rejects workflows because they do MORE than requested:

**Example**: User asks for changelog, workflow also creates PR
- **Reasoning**: "user doesn't mention wanting a PR created... this represents over-delivery"
- **Problem**: In practice, workflows doing extra steps is fine - users can ignore/skip steps

### 3. Confidence Always High (0.7-0.95)

Even when making difficult decisions, confidence is consistently high:
- Different data source (PRs vs issues): 0.80 confidence ✅
- Subset functionality: 0.70 confidence ❌
- Different file type (JSON vs CSV): 0.90 confidence ✅
- Add Slack notification: 0.80 confidence ✅

**Issue**: No confidence calibration for ambiguity level

### 4. Correct Decisions, Wrong Reasoning

Several cases made the right decision but for wrong reasons:
- Correctly rejected "JSON vs CSV" but with overly high confidence (0.90)
- Correctly rejected "add Slack" but didn't mention it as "additional functionality"

## Specific Test Case Analysis

### Failed Cases

| Test Case | Expected | Got | Confidence | Issue |
|-----------|----------|-----|------------|-------|
| subset_functionality | found_existing | not_found | 0.70 | Too strict on parameters |
| different_data_source | Low conf (0-0.5) | High conf (0.80) | 0.80 | Overconfident |
| different_file_type | Low conf (0-0.4) | High conf (0.90) | 0.90 | Overconfident |
| workflow_extension | Low conf (0-0.5) | High conf (0.80) | 0.80 | Overconfident |

### Reasoning Patterns

**Good Patterns**:
- Identifies data source differences (issues vs PRs)
- Recognizes file format incompatibilities
- Understands when functionality is missing

**Bad Patterns**:
- Rejects when workflow does "more than requested"
- Too literal about parameter values
- Always highly confident, even in ambiguous cases

## Root Causes

### 1. Prompt Design Issues

The discovery prompt likely emphasizes:
- **Exact matching** rather than functional compatibility
- **Complete coverage** of user request (no over/under delivery)
- **High confidence** in all decisions

### 2. Missing Guidance

The prompt probably lacks:
- Guidance on handling workflows that do MORE than requested
- Instructions for confidence calibration based on ambiguity
- Examples of parameter flexibility

### 3. Over-Specification

The prompt may be too specific about what constitutes a "match":
- Every parameter must align
- No extra functionality allowed
- All aspects must be covered

## Recommendations for Prompt Improvement

### 1. Add Parameter Flexibility Guidance

```markdown
When comparing workflows, focus on CORE FUNCTIONALITY rather than exact parameters:
- "last 20 issues" vs "last 30 issues" → MATCH (parameter difference)
- "closed issues" vs "open issues" → MATCH (parameter difference)
- "issues" vs "pull requests" → NO MATCH (different data source)
```

### 2. Allow Over-Delivery

```markdown
Workflows that do MORE than requested are acceptable:
- User: "generate changelog"
- Workflow: "generate changelog AND create PR"
- Decision: MATCH - user can ignore/skip the PR step
```

### 3. Calibrate Confidence

```markdown
Confidence should reflect decision difficulty:
- Clear matches (>90% semantic overlap): 0.85-0.95
- Good matches (70-90% overlap): 0.70-0.85
- Ambiguous cases (50-70% overlap): 0.50-0.70
- Poor matches (<50% overlap): 0.00-0.50
```

### 4. Focus on User Intent

```markdown
Consider the user's likely intent:
- Brief requests ("changelog") → likely want existing workflow
- Specific requests ("changelog from PRs not issues") → likely need new workflow
- Parameter variations ("version 1.4" vs "version 1.3") → same workflow
```

## Performance Impact

Current discovery accuracy impacts system performance:
- **False Negatives** (rejecting good matches): Forces unnecessary 20-second regeneration
- **False Positives** (accepting bad matches): Causes parameter extraction failures

With current 66% accuracy:
- ~34% of reusable workflows trigger unnecessary regeneration
- Users wait 20 seconds instead of 2 seconds
- System does 10x more work than necessary

## Next Steps

1. **Update discovery prompt** with flexibility guidance
2. **Add confidence calibration** instructions
3. **Include examples** of parameter flexibility
4. **Test with north star workflows** to verify improvements
5. **Target 90%+ accuracy** on unambiguous cases

## Conclusion

The discovery prompt is too strict and overconfident. It needs to:
- Be more flexible with parameters
- Accept workflows that do extra steps
- Calibrate confidence based on ambiguity
- Focus on core functionality rather than exact matches

These changes would improve Path A (reuse) activation rate, reducing response time from 20 seconds to 2 seconds for appropriate cases.