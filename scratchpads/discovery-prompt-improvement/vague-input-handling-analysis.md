# Vague Input Handling Analysis

## The Problem

When users provide vague inputs like "generate changelog", there's an architectural question about where this should be handled:

**ComponentBrowsingNode** (current focus): Selects available nodes/workflows
**ParameterDiscoveryNode** (downstream): Discovers parameters from user input

## Key Insight

There are **two different types of "vagueness"**:

### Type 1: Vague Instructions (ComponentBrowsingNode concern)
- **Example**: "generate changelog"
- **Problem**: Instructions are so vague it's unclear what workflow to create
- **Question**: Should ComponentBrowsingNode handle this by selecting a broad range of components?
- **Alternative**: Should this fail earlier as "insufficient instructions"?

### Type 2: Missing Parameters (ParameterDiscoveryNode concern)
- **Example**: "create changelog from GitHub issues" (clear intent, missing specifics)
- **Problem**: Clear workflow intent but missing parameters like issue count, file path, etc.
- **Handled by**: ParameterDiscoveryNode can extract what's available, mark others as missing

## Current Architecture Flow

```
User: "generate changelog"
├─ Path A (Discovery): No existing workflow matches
└─ Path B:
   ├─ ComponentBrowsingNode: Must select components for vague request
   ├─ ParameterDiscoveryNode: Must extract parameters from vague request
   ├─ WorkflowGeneratorNode: Must create workflow from minimal information
   └─ ParameterMappingNode: Will likely find missing parameters
```

## The Tension

**ComponentBrowsingNode perspective:**
- Job is to "curate available nodes to make downstream jobs easier"
- With "generate changelog", should select: github, llm, file, git nodes
- Over-inclusive approach helps even with vague inputs

**System perspective:**
- Can create workflows even with missing parameters (they get marked as required inputs)
- BUT cannot create meaningful workflows if instructions are too vague
- "generate changelog" has enough context to imply: fetch data → process → output

## Hypothesis

**Vague inputs with clear domain intent should proceed:**
- "generate changelog" → implies GitHub data + processing + file output
- "create report" → implies data gathering + analysis + output
- "process files" → implies file input + transformation + output

**Vague inputs without clear domain should fail:**
- "help me" → no clear domain or intent
- "do something" → completely ambiguous

## Testing Strategy Impact

For ComponentBrowsingNode tests, we should include:
1. **Clear domain, vague details**: "generate changelog" → expect github, llm, file nodes
2. **Clear domain, clear details**: Full north star examples → expect specific node sequences
3. **No clear domain**: "help me automate" → expect very broad selection OR failure

## Questions for Resolution

1. Should ComponentBrowsingNode have logic to reject inputs that are too vague?
2. Or should it always select broadly and let downstream nodes handle the specifics?
3. Where is the right place to detect "insufficient instructions for workflow creation"?

## Current Recommendation

**Keep ComponentBrowsingNode broad and permissive:**
- Its job is curation, not validation
- Vague inputs with domain context (like "generate changelog") should get broad component selection
- Let ParameterDiscoveryNode and ParameterMappingNode handle the parameter resolution
- This matches the "over-inclusive" philosophy

**But document this architectural decision** so future developers understand the intent.