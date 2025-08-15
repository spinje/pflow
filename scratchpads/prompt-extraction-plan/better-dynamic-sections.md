# Better Approach: Full Structure in Markdown

## Current Problem
We're hiding prompt structure in Python code, making it hard to:
- Review the complete prompt
- Understand what information the LLM receives
- Edit prompt structure without changing code

## Better Solution: Everything in Markdown

### Key Principles
1. **Complete structure visible** - All sections in markdown, even if sometimes empty
2. **XML tags for structure** - Better prompt engineering practice
3. **Python only computes values** - Not structure
4. **Empty sections are fine** - LLMs handle them gracefully

### Example Transformation

#### Old Approach (Structure Hidden):
```markdown
User request: {{user_input}}{{context_section}}{{stdin_section}}
```

Python builds:
```python
context_section = f"\n\nAvailable components:\n{context}" if context else ""
```

#### New Approach (Structure Visible):
```markdown
# Parameter Discovery Prompt

You are a parameter discovery system that extracts named parameters from natural language requests.

<user_request>
{{user_input}}
</user_request>

<available_components>
{{planning_context}}
</available_components>

<selected_components>
Nodes: {{selected_nodes}}
Workflows: {{selected_workflows}}
</selected_components>

<stdin_info>
{{stdin_info}}
</stdin_info>

Extract parameters with their likely names and values...
```

Python just provides values:
```python
format_prompt(template, {
    "user_input": prep_res["user_input"],
    "planning_context": prep_res.get("planning_context", "None"),
    "selected_nodes": ", ".join(nodes) if nodes else "None",
    "selected_workflows": ", ".join(workflows) if workflows else "None",
    "stdin_info": prep_res.get("stdin_info", "None")
})
```

### Benefits
1. **Complete prompt visible** - Can see entire structure in markdown
2. **Self-documenting** - Clear what data the prompt expects
3. **XML helps LLM** - Better parsing of structured sections
4. **Simpler Python** - Just value formatting, no structure building
5. **Easier testing** - Can test prompt with mock data directly

### Handling Different Cases

#### When data exists:
```xml
<selected_components>
Nodes: read-file, write-file, llm
Workflows: generate-changelog, analyze-code
</selected_components>
```

#### When data is empty:
```xml
<selected_components>
Nodes: None
Workflows: None
</selected_components>
```

The LLM understands "None" means no data available.

### For Complex Prompts (WorkflowGeneratorNode)

Even complex prompts can follow this pattern:

```markdown
<validation_errors>
{{validation_errors}}
</validation_errors>

<previous_attempts>
{{generation_attempts}}
</previous_attempts>

<discovered_parameters>
{{discovered_params}}
</discovered_parameters>
```

Python:
```python
{
    "validation_errors": "\n".join(errors) if errors else "None",
    "generation_attempts": str(attempts),
    "discovered_params": format_params(params) if params else "None"
}
```

### Migration Strategy

1. **Put ALL sections in markdown** - Even optional ones
2. **Use XML tags** for structure
3. **Use "None" for empty** - Clear signal to LLM
4. **Format lists properly** - Comma-separated or newline-separated
5. **Keep formatting simple** - Let markdown handle structure

### Example: ParameterDiscoveryNode Rewrite

```markdown
# Parameter Discovery Prompt

You are a parameter discovery system that extracts named parameters from natural language requests.

<user_request>
{{user_input}}
</user_request>

<context>
<planning_context>
{{planning_context}}
</planning_context>

<selected_nodes>
{{selected_nodes}}
</selected_nodes>

<selected_workflows>
{{selected_workflows}}
</selected_workflows>
</context>

<stdin_available>
{{stdin_info}}
</stdin_available>

Extract parameters with their likely names and values. Focus on:
1. File paths and names (e.g., "report.csv" → filename: "report.csv")
2. Numeric values (e.g., "last 20" → limit: "20")
3. States/filters (e.g., "closed issues" → state: "closed")
4. Formats (e.g., "as JSON" → output_format: "json")
5. Identifiers (e.g., "repo pflow" → repo: "pflow")

Return parameters as a simple name:value mapping. If stdin is present, note its type.

Examples:
- "process data.csv and convert to json" → {"filename": "data.csv", "output_format": "json"}
- "last 20 closed issues from repo" → {"limit": "20", "state": "closed"}
- "analyze the piped data" → {} (parameters will come from stdin)
```

### This is Better Because:
1. **Everything visible** - Full prompt structure in one place
2. **Reviewable** - Can understand prompt without reading Python
3. **Editable** - Can adjust prompt structure without code changes
4. **Testable** - Can test with simple string substitution
5. **LLM-friendly** - XML tags help with parsing