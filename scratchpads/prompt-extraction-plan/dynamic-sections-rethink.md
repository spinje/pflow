# Rethinking Dynamic Sections Integration

## Current Problem

With ParameterDiscoveryNode, we have:
```markdown
User request: {{user_input}}{{context_section}}{{stdin_section}}
```

But `context_section` and `stdin_section` are actually complex formatted strings built in Python:
- `context_section` can be one of two different formats based on conditions
- They're empty strings when not needed
- The template doesn't show what these sections actually look like

## Issues with Current Approach

1. **Opaque Templates**: You can't understand the prompt from the markdown alone
2. **Hidden Structure**: The actual prompt structure is split between .md and .py
3. **Testing Difficulty**: Can't test prompts without understanding Python logic
4. **Maintenance Problem**: Changes require coordinating between two files

## Alternative Approaches

### Option A: Structured Sections in Template
```markdown
User request: {{user_input}}

{{#if has_context}}
Available components context:
{{context_content}}
{{/if}}

{{#if has_stdin}}
Stdin data available: {{stdin_info}}
{{/if}}
```

**Problem**: We'd need a template engine, adding complexity.

### Option B: All Variants in Markdown
```markdown
# Parameter Discovery Prompt

You are a parameter discovery system that extracts named parameters from natural language requests.

User request: {{user_input}}

{{#when planning_context}}
Available components context:
{{planning_context}}
{{/when}}

{{#when browsed_components}}
Selected components:
- Nodes: {{selected_nodes}}
- Workflows: {{selected_workflows}}
{{/when}}

{{#when stdin_info}}
Stdin data available: {{stdin_info}}
{{/when}}
```

**Problem**: Still needs conditional logic, but at least structure is visible.

### Option C: Complete Sections as Variables (Better Current)
Instead of:
```markdown
User request: {{user_input}}{{context_section}}{{stdin_section}}
```

Do:
```markdown
User request: {{user_input}}

{{context_section}}

{{stdin_section}}
```

And pass complete sections including newlines:
```python
context_section = "" if not context else f"""
Available components context:
{context}"""

stdin_section = "" if not stdin else f"""
Stdin data available: {stdin_info}"""
```

**Problem**: Still builds sections in Python, but cleaner template.

### Option D: Document Expected Sections in Comments
```markdown
# Parameter Discovery Prompt

You are a parameter discovery system that extracts named parameters from natural language requests.

User request: {{user_input}}

<!-- Optional: context_section
When provided, contains either:
- "Available components context: [component list]"
- "Selected components: Nodes: [nodes], Workflows: [workflows]"
-->
{{context_section}}

<!-- Optional: stdin_section
When provided, contains: "Stdin data available: [stdin type]"
-->
{{stdin_section}}
```

**Benefits**:
- Template shows structure
- Comments document what to expect
- Python still handles complex logic

### Option E: Semantic Variable Names (Minimal Change)
Just rename variables to be more descriptive:
```markdown
User request: {{user_input}}{{optional_context_section}}{{optional_stdin_section}}
```

Or with newlines:
```markdown
User request: {{user_input}}
{{optional_context_section}}
{{optional_stdin_section}}
```

**Benefits**: Clear that these are optional, minimal change.

## The Real Problem

The core issue is that we're trying to externalize prompts that have **business logic** embedded in them:
- If planning_context exists, format one way
- Elif browsed_components exists, format another way
- Truncate at 2000 chars
- Join lists with specific formatting

This logic doesn't belong in templates - it's application logic.

## Recommendation: Hybrid with Clear Boundaries

### For ParameterDiscoveryNode specifically:

1. **Keep the prompt simple and explicit**:
```markdown
# Parameter Discovery Prompt

You are a parameter discovery system that extracts named parameters from natural language requests.

User request: {{user_input}}
{{components_context}}
{{stdin_context}}

Extract parameters with their likely names and values. Focus on:
1. File paths and names (e.g., "report.csv" → filename: "report.csv")
...
```

2. **Build complete formatted sections in Python**:
```python
# Build components context (business logic stays in Python)
components_context = ""
if prep_res["planning_context"]:
    # Format for planning context
    components_context = f"\nAvailable components context:\n{prep_res['planning_context'][:2000]}"
elif prep_res["browsed_components"]:
    # Format for browsed components
    nodes = ...
    components_context = f"\nSelected components:\n- Nodes: {nodes}\n- Workflows: {workflows}"

# Build stdin context
stdin_context = ""
if prep_res["stdin_info"]:
    stdin_context = f"\nStdin data available: {prep_res['stdin_info']}"
```

3. **Add template documentation**:
```markdown
<!--
Variables:
- user_input: The user's request
- components_context: (optional) Formatted context about available components
- stdin_context: (optional) Information about stdin data if available
-->
```

## Decision Framework

**Extract to markdown when:**
- Content is mostly static
- Variable substitution is straightforward
- No complex conditionals or formatting

**Keep in Python when:**
- Complex if/elif logic
- Data transformation (truncation, joining)
- Multiple format variants based on conditions

**Document in template when:**
- Variables are optional
- Format varies based on runtime data
- Future maintainers need to understand the structure

## For Task 33 Going Forward

1. **ParameterDiscoveryNode**: Already done, but could improve with documentation
2. **ParameterMappingNode**: Similar pattern - base prompt + dynamic sections
3. **WorkflowGeneratorNode**: Definitely hybrid - base prompt in .md, complex sections in Python
4. **MetadataGenerationNode**: Mostly static, good for full extraction

What do you think? Should we:
A. Keep current approach but add documentation
B. Refactor to use clearer section boundaries (newlines between sections)
C. Go hybrid with well-documented boundaries
D. Something else?