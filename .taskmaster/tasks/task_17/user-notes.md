

line 663 in context_builder.py

```python
 # Show template variable usage instead of misleading "none"
 template_vars = []
 for inp in inputs:
     if isinstance(inp, dict):
         key = inp["key"]
         template_vars.append(f'{key}: "${key}"')
 if template_vars:
     lines.append("**Template Variables**: Use $variables in params field for inputs:")
     for var in template_vars[:3]:  # Limit to first 3 to avoid bloat
         lines.append(f"- {var}")
     if len(template_vars) > 3:
         lines.append(f"- ... and {len(template_vars) - 3} more")
 else:
     lines.append("**Template Variables**: Use $variables in params field for any input")
```