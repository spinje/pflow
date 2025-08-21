# Task 28: Prompt Improvement Handover

## 🎯 The Core Insight That Changes Everything

**Context provision is the primary lever for accuracy, not prompt wording.**

I discovered this the hard way with discovery prompt: spent time crafting better instructions only to find the LLM was making decisions with minimal information. The breakthrough came from providing rich, structured context (node flows, capabilities, use cases). Prompt clarity matters, but context richness matters more.

## 🏗️ The Architecture Discovery That Almost Got Missed

**Critical Issue Found**: The planner generates rich metadata (capabilities, keywords, use cases) but it was being lost in the storage pipeline. Here's what I found:

1. **MetadataGenerationNode** creates detailed metadata
2. **CLI** receives it separately from workflow_ir
3. **CLI** only saves workflow_ir → metadata disappears
4. **Discovery context** only has names + descriptions

**The Fix**: I separated concerns cleanly:
- Metadata stays OUT of IR schema (IR = pure structure)
- WorkflowManager accepts metadata as separate parameter
- Metadata stored at wrapper level (`rich_metadata` field)
- Context builder reads from wrapper level

**Why This Matters for Other Prompts**: If a prompt needs rich information for decisions, verify the data flow first. Don't assume information is available just because it's generated somewhere.

## 📊 The Test Philosophy Revolution

**Old Thinking**: Test confidence scores in rigid ranges (HIGH/MEDIUM/LOW)
**New Thinking**: Test decision correctness only

This change was as impactful as prompt improvements:
- Reduced tests from 19 → 12 high-quality cases
- Focus on observable outcomes (found/not_found, select/don't_select)
- Log confidence for information, never fail on it
- Each test validates something distinct with clear rationale

**For Future Prompts**: If tests are failing on confidence ranges, that's a test problem, not a prompt problem. Fix the tests first.

## 🔍 Context Enhancement Patterns That Work

### Pattern 1: Show, Don't Tell
Instead of describing capabilities, show actual execution:
```
Before: "Generates changelog from GitHub"
After: "Flow: github-list-issues → llm → write-file → github-create-pr"
```

The node flow became "primary evidence" because it shows exactly what happens. LLM can see data sources (issues not PRs), processing (LLM), outputs (files, PRs).

### Pattern 2: Multiple Signal Layers
```
**1. `workflow-name`** - Clear description
   **Flow:** `actual-execution-sequence`
   **Can:** What it can do
   **For:** When to use it
```

Don't show search keywords to users (kept internal), but do show capabilities and use cases.

### Pattern 3: Compact But Complete
- No truncation of any field - LLM can handle longer text
- Structured formatting with clear hierarchy
- Full information beats brevity for accuracy

## 🧠 Prompt Improvement Patterns That Actually Work

### Structure That Works:
```markdown
## Your Task
[Clear role - "workflow router" better than "discovery system"]

## Decision Process
### Step 1: Understand the Input
### Step 2: Examine the Evidence
### Step 3: Make the Decision

## Return X when:
[Concrete criteria with examples]

## Key Principles
[5 simple, memorable rules]
```

### What Doesn't Work:
- Contradictory instructions ("be strict but don't miss matches")
- Abstract criteria without examples
- Complex decision trees
- Confidence score guidance

## 🛠️ Test Framework Mastery

### Using test_prompt_accuracy.py Effectively:
```bash
# Baseline measurement (ALWAYS do this first)
uv run python tools/test_prompt_accuracy.py [prompt] --model gpt-5-nano

# Iteration with cheap model
uv run python tools/test_prompt_accuracy.py [prompt] --model gpt-5-nano --dry-run

# Final validation
uv run python tools/test_prompt_accuracy.py [prompt]
```

### Parallel Testing Setup:
Tests MUST use pytest parametrization:
```python
@pytest.mark.parametrize("test_case", get_test_cases(), ids=lambda tc: tc.name)
def test_scenario(self, fixture, test_case):
    # Individual test execution
```

And immediate failure reporting for real-time feedback.

### Success Metrics:
- >80% accuracy on test suite
- <10 seconds execution with parallel testing
- <$0.01 cost with gpt-5-nano
- Decision correctness focus

## 📂 Key Files and Their Roles

### Prompt Files (`src/pflow/planning/prompts/`)
- YAML frontmatter managed by test tool (don't edit manually)
- Template variables like `{{discovery_context}}`
- Markdown content with clear structure

### Context Builders (`src/pflow/planning/context_builder.py`)
- `build_workflows_context()` - what I enhanced for discovery
- Other `build_*_context()` functions may need similar enhancement
- Key insight: _build_node_flow() function shows execution sequence

### Planning Nodes (`src/pflow/planning/nodes.py`)
- Each node has prep() → exec() → post() pattern
- prep() builds context, exec() calls LLM, post() routes
- Look for what context each node actually provides

### Test Files (`tests/test_planning/llm/prompts/`)
- Follow parametrized testing pattern
- Include failure reporting function
- Focus on decision outcomes

## 🎯 Recommendations for Remaining Prompts

### component_browsing.md
**Likely Issues**: May need enhanced registry context showing node capabilities
**Context Check**: What information does ComponentBrowsingNode receive about available nodes?
**Test Focus**: Selection correctness (chose right nodes/workflows)

### parameter_discovery.md
**Likely Issues**: May need examples of parameter extraction patterns
**Context Check**: Does it see user input with good parameter examples?
**Test Focus**: Extraction completeness and accuracy

### parameter_mapping.md
**Likely Issues**: May need clear parameter schemas and type information
**Context Check**: Does it see workflow input requirements clearly?
**Test Focus**: Mapping correctness and validation

### workflow_generator.md
**Likely Issues**: Most complex - may need enhanced component interfaces
**Context Check**: Does it understand how nodes connect and what edges are valid?
**Test Focus**: Generated workflow validity and execution correctness

### metadata_generation.md
**Likely Issues**: May need examples of good metadata patterns
**Context Check**: Does it see the workflow structure clearly enough?
**Test Focus**: Metadata quality and searchability

## ⚠️ Critical Pitfalls to Avoid

### Don't Assume Data Is Available
I wasted time improving discovery prompt before realizing metadata wasn't being saved. Always trace the data flow first.

### Don't Fight the Test Framework
The test_prompt_accuracy.py tool wants to manage frontmatter. Let it. Manual edits get overwritten.

### Don't Optimize Confidence Scores
They're internal LLM mechanics. Focus on observable decisions that affect users.

### Don't Add Complexity to Fix Clarity Issues
Simple, structured prompts beat complex decision trees. When in doubt, simplify.

## 🔮 What I'd Do Next

1. **Start with component_browsing** - probably has similar context issues as discovery
2. **Check the registry metadata** - components may need richer descriptions
3. **Apply the same patterns** - structured decision process, evidence hierarchy
4. **Enhance context before prompt** - verify data flow, enhance if needed
5. **Refine tests in parallel** - don't wait until end

## 💎 The Meta-Insight

**Prompts are interfaces to intelligence.** Like any interface, they work best when:
- Input (context) is rich and well-structured
- Instructions are clear and unambiguous
- Output (decisions) is measurable and testable
- Feedback loop (testing) enables rapid iteration

The discovery improvement wasn't just about better prompts - it was about building a better interface to the LLM's decision-making capability.

---

**Next Agent**: Read this handover, understand the patterns, then dive into your chosen prompt. Don't start implementing until you've read everything and said you're ready to begin.