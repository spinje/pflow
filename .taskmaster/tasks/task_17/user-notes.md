

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






---





We've successfully prepared the infrastructure for the planner integration:

  What We Changed:

  1. Updated execute_json_workflow signature (line 291-296):
    - Added execution_params: dict[str, Any] | None = None parameter
    - Updated docstring to document the new parameter
  2. Pass params to compiler (line 325):
    - Now calls: compile_ir_to_flow(ir_data, registry, initial_params=execution_params)
    - Template variables will now be resolved correctly when params are provided
  3. Updated existing caller (line 384):
    - Passes None for now (no execution_params from file-based workflows)
    - Will be used when we integrate the planner

  Why This Matters:

  Before:
  # Templates couldn't be resolved - workflows with $variables would fail
  flow = compile_ir_to_flow(ir_data, registry)  # No params!

  After:
  # Templates can now be resolved with parameters from the planner
  flow = compile_ir_to_flow(ir_data, registry, initial_params=execution_params)

  Next Steps:

  When we integrate the planner (replacing the TODO), we can now simply call:
  execute_json_workflow(
      ctx,
      planner_output["workflow_ir"],
      stdin_data,
      output_key,
      planner_output["execution_params"]  # ← Clean and direct!
  )

  The infrastructure is ready. The main integration will be much simpler now!