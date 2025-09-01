# Critical Decision: Remove --file Flag Completely

## Decision Importance: 5/5 (Architectural)

This fundamentally changes the CLI interface but makes it dramatically simpler.

### Context

Currently, users must use `--file` to load workflow files:
```bash
pflow --file workflow.json              # Works
pflow workflow.json                     # Doesn't work (goes to planner)
```

But saved workflows work without any flag:
```bash
pflow my-workflow                       # Works
```

This inconsistency confuses users and adds unnecessary complexity.

### The Radical Simplification

Remove `--file` entirely and make everything "just work":

```bash
# ALL of these would work naturally:
pflow my-workflow                       # Saved workflow
pflow my-workflow.json                  # Saved workflow (strips .json)
pflow workflow.json                     # Local file (detects .json)
pflow ./workflow.json                   # Local file (detects path)
pflow /tmp/workflow.json                # Absolute path
pflow "analyze this"                    # Natural language (has spaces)
```

### Options

- [x] **Option A: Remove --file Completely**
  - ✅ Simplest, most intuitive interface
  - ✅ Remove ~200 lines of code
  - ✅ Everything "just works"
  - ❌ Breaking change (but we have NO users!)
  - ❌ Can't force file reading if ambiguous (but ./ prefix solves this)

- [ ] **Option B: Keep --file but Make Optional**
  - ✅ Backward compatible
  - ✅ Explicit control when needed
  - ❌ Keeps complexity in codebase
  - ❌ Users still confused about when to use it
  - ❌ Two ways to do the same thing

- [ ] **Option C: Deprecate --file Gradually**
  - ✅ Gentle transition
  - ❌ Even MORE complexity (deprecation warnings)
  - ❌ We have no users to transition!
  - ❌ Delays the simplification

**Strong Recommendation: Option A - Remove --file completely**

Since we have ZERO users and are building an MVP, this is the perfect time to make breaking changes that result in a better architecture.

## Implementation Impact

### Code Deletion Festival! 🎉
We can DELETE:
- `get_input_source()` - 45 lines
- `_determine_workflow_source()` - 15 lines
- `_determine_stdin_data()` - 35 lines
- `process_file_workflow()` - 35 lines
- `_execute_json_workflow_from_file()` - 35 lines
- `_get_file_execution_params()` - 20 lines
- Various validation logic - 20 lines

**Total: ~200 lines removed!**

### What We Add (Minimal)
- `resolve_workflow()` - 30 lines
- Enhanced `is_likely_workflow_name()` - 10 lines
- Unified execution path - 20 lines

**Total: ~60 lines added**

**Net reduction: 140 lines!**

## Risk Assessment

### Potential Issues
1. **Ambiguity**: What if "analyze" is both a file and saved workflow?
   - **Solution**: Clear precedence: File paths (with .json or /) → Saved workflows → Natural language

2. **User Intent**: How do we know if user wants file vs saved?
   - **Solution**: The format tells us! `./foo.json` is clearly a file, `foo` is clearly saved

3. **Backward Compatibility**: Existing scripts using --file break
   - **Solution**: We have NO users! Perfect time to break things

## The Beautiful End Result

```python
# The ENTIRE workflow resolution logic becomes:
def main():
    first_arg = workflow[0] if workflow else ""

    # Try to resolve as workflow (file or saved)
    if not has_spaces(first_arg):  # Not natural language
        workflow_ir, source = resolve_workflow(first_arg)
        if workflow_ir:
            params = parse_params(workflow[1:])
            execute_workflow(workflow_ir, params)
            return

    # Natural language fallback
    execute_with_planner(input)
```

That's it. The entire routing logic in ~10 lines instead of ~200.

## Decision Required

Should we proceed with removing `--file` completely for a radically simpler interface?

The benefits are enormous, the risks are minimal (no users), and the code becomes beautiful.

What do you think?