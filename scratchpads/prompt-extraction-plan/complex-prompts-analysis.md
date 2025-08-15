# Handling Complex Prompts with Dynamic Sections

## The Challenge

Some prompts have dynamic sections that are conditionally added based on runtime state:

### Example: WorkflowGeneratorNode
```python
# Base prompt always present
prompt = f"""Generate a workflow for: {prep_res["user_input"]}
...
Available nodes:
{prep_res["planning_context"]}
..."""

# Conditionally added sections:
if prep_res.get("discovered_params"):
    prompt += f"""
DISCOVERED PARAMETERS:
{discovered_params_text}
"""

if prep_res["generation_attempts"] > 0 and prep_res.get("validation_errors"):
    prompt += f"""
VALIDATION ERRORS FROM PREVIOUS ATTEMPT:
{formatted_errors}
Fix these specific issues...
"""
```

## Options Analysis

### Option 1: Template with Placeholders for Optional Sections
```markdown
# generator.md
Generate a workflow for: {{user_input}}
...
{{optional_discovered_params}}
{{optional_validation_errors}}
```

**Pros:**
- Single source of truth
- Clear what's optional
- Easy to read the full prompt

**Cons:**
- Empty placeholders leave blank lines
- Need convention for "empty" vs "has content"

### Option 2: Separate Template Files
```
prompts/
├── generator_base.md
├── generator_discovered_params.md
└── generator_validation_errors.md
```

**Pros:**
- Each piece is focused
- Easy to test individually
- Clear separation of concerns

**Cons:**
- Multiple files to maintain
- Need to ensure consistent voice/style
- Loading logic more complex

### Option 3: Hybrid - Base Template + Code Composition
```python
# In nodes.py
base_prompt = load_prompt("generator_base")
formatted = format_prompt(base_prompt, {...})

# Add dynamic sections in code
if discovered_params:
    formatted += "\n\n" + self._build_discovered_params_section(...)
if validation_errors:
    formatted += "\n\n" + self._build_validation_errors_section(...)
```

**Pros:**
- Static content in markdown
- Dynamic logic stays in Python
- Flexible for complex conditions

**Cons:**
- Not everything externalized
- Need to maintain both files and code

### Option 4: Template with Conditional Markers
```markdown
# generator.md
Generate a workflow...

{{#if discovered_params}}
DISCOVERED PARAMETERS:
{{discovered_params}}
{{/if}}

{{#if validation_errors}}
VALIDATION ERRORS:
{{validation_errors}}
{{/if}}
```

**Pros:**
- Single file
- Clear conditions
- Familiar syntax (like Handlebars)

**Cons:**
- Need template engine
- More complex than simple string replacement
- Overkill for our needs?

### Option 5: Composition Functions in Loader
```python
# loader.py
def load_prompt_with_sections(
    base_name: str,
    variables: Dict,
    sections: Dict[str, Optional[str]]
) -> str:
    """Load base prompt and append optional sections."""
    base = load_prompt(base_name)
    formatted = format_prompt(base, variables)

    for section_name, section_content in sections.items():
        if section_content:
            formatted += f"\n\n{section_content}"

    return formatted
```

**Pros:**
- Reusable pattern
- Clean separation
- Easy to test

**Cons:**
- Another abstraction layer
- Need to decide what goes where

## Recommendation

**For WorkflowGeneratorNode specifically**, I recommend **Option 3: Hybrid Approach**

### Why:
1. **The base prompt is 90% of the content** - worth externalizing
2. **Dynamic sections have complex formatting logic** - better in Python
3. **Maintains clarity** - markdown has the "what", Python has the "how"
4. **Progressive enhancement** - can extract more later if patterns emerge

### Implementation Plan:

1. Extract the base prompt to `generator_base.md`
2. Keep section builders as methods in the node class
3. Compose final prompt in `exec()` method

Example:
```python
class WorkflowGeneratorNode:
    def exec(self, prep_res):
        # Load base prompt
        base_prompt = load_prompt("generator_base")
        prompt = format_prompt(base_prompt, {
            "user_input": prep_res["user_input"],
            "planning_context": prep_res["planning_context"]
        })

        # Add dynamic sections
        if prep_res.get("discovered_params"):
            prompt += self._build_params_hint(prep_res["discovered_params"])

        if prep_res.get("validation_errors"):
            prompt += self._build_errors_section(prep_res["validation_errors"])

        # Continue with LLM call...
```

## Decision Points

1. **Should we extract everything possible?**
   - No, keep complex logic in Python where it's testable

2. **What's the threshold for extraction?**
   - Static content > 5 lines → extract
   - Dynamic logic → keep in code
   - Formatting/conditionals → keep in code

3. **How to handle variables in dynamic sections?**
   - Build complete sections in Python
   - Pass as single variables to template if needed

## For Simpler Dynamic Prompts

For prompts like ParameterDiscoveryNode with simple conditionals:
```python
context_section = f"\n\nContext: {context}" if context else ""
stdin_section = f"\n\nStdin: {stdin_type}" if stdin_data else ""
```

**Recommendation**: Include these as optional variables with empty defaults:
```markdown
User request: {{user_input}}{{context_section}}{{stdin_section}}
```

Then in code:
```python
format_prompt(template, {
    "user_input": user_input,
    "context_section": f"\n\nContext: {context}" if context else "",
    "stdin_section": f"\n\nStdin: {stdin_type}" if stdin_data else ""
})
```

## Next Steps

1. Start with **ParameterDiscoveryNode** - simpler dynamic sections
2. Then **ParameterMappingNode** - moderate complexity
3. Then **WorkflowGeneratorNode** - use hybrid approach
4. Finally **MetadataGenerationNode** - straightforward with variables

What do you think of this approach?