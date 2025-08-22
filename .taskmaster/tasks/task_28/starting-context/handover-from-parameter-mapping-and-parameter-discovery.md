# Task 28 Handoff: The Hard Truth About Prompt Testing

## 🎯 What You're Building On

We successfully improved parameter_discovery and parameter_mapping prompts to exceed 80% accuracy. But the real breakthrough wasn't the accuracy - it was discovering that **our tests were lying to us**.

## 🔥 The Critical Insight That Changes Everything

**Your tests are probably too easy.**

I started with 10 tests that gave us 90%+ accuracy. Felt great. Then I asked: "What's actually HARD for parameter extraction?" The answer changed everything.

### The Journey You Need to Understand

1. **Original tests (10)**: Basic extraction like finding "30" in "30 issues" → Everyone passes
2. **Refined tests (6)**: Removed redundancy, still easy → 83% accuracy
3. **HARD tests (7)**: Real challenges → gpt-5-nano: 85.7%, Claude: 100%

The HARD tests finally differentiated model quality. **This is what real testing looks like.**

## 🧠 The 7 Challenges That Actually Matter

These are what make parameter extraction genuinely difficult:

1. **Topic vs Instruction Boundary**: "Write analysis about ML in healthcare" - where's the line?
2. **Ambiguous References**: "this" (stdin) vs "that" (unclear) vs "yesterday" (parameter)
3. **Vague Quantifiers**: "few dozen" → 24? 36? Keep as-is?
4. **Negation/Exclusion**: "all except PDFs and images" - how to represent?
5. **Context-Dependent**: "latest 50" - of what?
6. **Composite Values**: "Q4 2023" - one param or two?
7. **Implicit Instructions**: Extract "active" from "should be filtered for active users"

**These are in the HARD test suite** at `tests/test_planning/llm/prompts/test_parameter_discovery_prompt.py`

## ⚠️ Architectural Gotchas I Discovered

### ParameterMappingNode Applies Defaults During Extraction
The test expected `{"repo": "pflow"}` but the node returns `{"repo": "pflow", "limit": 10, "state": "open"}` because it applies defaults. This is in the implementation at `src/pflow/planning/nodes.py:760`:

```python
if "default" in param_spec:
    result["extracted"][param_name] = param_spec["default"]
```

**This conflates extraction with preparation.** The test-writer-fixer agent pointed this out - it makes tests harder to reason about.

### The Data Flow You Must Verify
Before improving ANY prompt, trace the data flow:
- `ParameterDiscoveryNode.prep()` → What context is built?
- `context_builder.py` → Is the data actually reaching the prompt?
- Check for architectural issues (like metadata not being saved in discovery prompt improvement)

## 📁 Critical Files and Their Roles

### The Tests That Matter
- `tests/test_planning/llm/prompts/test_parameter_discovery_prompt.py` - The HARD tests
- `tests/test_planning/llm/prompts/test_parameter_mapping_prompt.py` - Still needs HARD version

### The Test Patterns to Follow
Look at `test_discovery_prompt.py` - it's the gold standard:
- Parametrized tests for parallel execution
- `report_failure()` for real-time feedback
- File-based failure reporting (bypasses pytest capture)
- `get_test_cases()` at module level

### Documentation of the Journey
- `.taskmaster/tasks/task_28/implementation/hard-test-analysis.md` - Why tests need to be hard
- `.taskmaster/tasks/task_28/implementation/test-quality-audit-plan.md` - How to audit test quality
- `.taskmaster/tasks/task_28/implementation/quality-testing-insights.md` - What we learned

## 🚨 Warnings from Battle Scars

### Don't Trust Easy Tests
If gpt-5-nano gets 95%+, your tests are too easy. Real challenges should differentiate models.

### The Test Framework Has Opinions
- The `tools/test_prompt_accuracy.py` manages frontmatter - don't edit manually
- It will ask about version increment when prompt hash changes - answer 'n' to keep history
- Use `--dry-run` to avoid updates during iteration

### Allow Flexible Validation
Natural language has multiple valid interpretations. "Few dozen" could be:
- "few dozen" (kept as-is)
- "24" (interpreted)
- "36" (different interpretation)

Your test should accept variations, not demand one answer.

### Test What's Observable
- ✅ Test: Values extracted
- ❌ Don't test: Exact parameter names (for discovery)
- ✅ Test: Required params identified as missing
- ❌ Don't test: Confidence scores

## 🔍 Questions You Should Investigate

1. **Should ParameterMappingNode include defaults in extracted?**
   - Current: YES (implementation)
   - Tests expected: NO
   - What's correct for the architecture?

2. **Where should "too vague" be caught?**
   - ParameterDiscoveryNode (be permissive)?
   - ParameterMappingNode (be strict)?
   - Both?

3. **How sophisticated should type inference be?**
   - "enabled" → true (boolean)
   - "30" → 30 (integer)
   - Where's the line?

## 💡 Patterns That Work

### For Prompt Improvement
1. Structured decision process (Step 1, 2, 3...)
2. Comprehensive examples covering edge cases
3. Clear DO/DON'T rules
4. Evidence hierarchy (primary, secondary, supporting)

### For Test Design
1. Each test validates ONE behavior
2. Document the challenge it tests
3. Allow acceptable variations
4. Focus on what's HARD, not what's easy

## 🎪 The Meta-Pattern

**Context is king, but test quality is emperor.**

You can have perfect prompts with great context, but if your tests are easy, you're lying to yourself about capability. The difference between 100% on easy tests and 85% on hard tests is the difference between false confidence and real understanding.

## 📊 Where We Stand

### parameter_discovery
- **Prompt**: Solid structure with comprehensive examples
- **Tests**: 7 HARD tests that actually challenge the system
- **Accuracy**: 85.7% (gpt-5-nano), 100% (Claude)
- **Status**: DONE with meaningful tests

### parameter_mapping
- **Prompt**: Improved with strict mapping rules
- **Tests**: Still using easier tests (needs HARD version)
- **Accuracy**: 80% (both models)
- **Status**: Meets target but tests could be harder

## 🏁 Final Wisdom

The user pushed me to think about test quality, and it revealed everything. Don't optimize for accuracy on easy tests - optimize for understanding where the system breaks.

The HARD tests aren't just tests - they're a specification of what makes this problem actually difficult. Study them. Understand why each one is hard. That's where the real learning is.

---

**Next Agent**: Read this handoff, understand why test quality matters more than test quantity, then say you're ready to begin. Don't start implementing until you've absorbed why HARD tests changed everything.