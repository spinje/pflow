# Prompt: Update All Interface Examples to Enhanced Format

You are tasked with updating all Interface examples in the pflow documentation from the old simple format to the new Enhanced Interface Format with type annotations and descriptions.

## Your Mission

Update 23 Interface examples across 11 documentation files to use the Enhanced Interface Format that includes:
- Type annotations for all inputs, outputs, and parameters
- Semantic descriptions using `#` comments
- The exclusive params pattern (don't duplicate inputs in params)
- Multi-line format for better readability

## Required Reading

Before starting, you MUST read these two documents in the scratchpad folder:
1. **interface-update-plan.md** - Detailed plan with file inventory and transformation rules
2. **interface-update-context.md** - Critical context about the enhanced format and patterns

## Quick Example

You'll be transforming examples from this:
```python
Interface:
- Reads: shared["file_path"], shared["encoding"]
- Writes: shared["content"], shared["error"]
- Params: file_path, encoding, line_numbers
- Actions: default, error
```

To this:
```python
Interface:
- Reads: shared["file_path"]: str  # Path to the file to read
- Reads: shared["encoding"]: str  # File encoding (optional, default: utf-8)
- Writes: shared["content"]: str  # File contents with line numbers
- Writes: shared["error"]: str  # Error message if operation failed
- Params: line_numbers: bool  # Include line numbers (default: true)
- Actions: default (success), error (failure)
```

Note how:
- Every field has a type annotation (`: str`, `: bool`)
- Every field has a helpful description after `#`
- `file_path` and `encoding` are NOT in Params (exclusive params pattern)
- Multi-line format makes it more readable

## Process

1. **Start with high-priority files**:
   - `docs/reference/node-reference.md`
   - `docs/features/simple-nodes.md`
   - `docs/implementation-details/metadata-extraction.md`

2. **For each file**:
   - Find all Interface examples
   - Apply the transformation rules from the plan
   - Ensure consistency within the file
   - Move to the next file

3. **Use these grep commands to find examples**:
   ```bash
   # Find all Interface sections
   grep -n "Interface:" docs/**/*.md

   # Find specific patterns
   grep -n "Reads:" docs/**/*.md
   grep -n "Writes:" docs/**/*.md
   ```

## Critical Rules

1. **Exclusive Params Pattern**: Parameters that are in Reads should NOT be in Params
2. **Valid Types Only**: Use str, int, float, bool, dict, list, any
3. **Meaningful Descriptions**: Focus on what the field represents, not just its name
4. **Multi-line Format**: Use for clarity, especially with 3+ items

## Quality Check

Before considering a file complete, verify:
- ✅ All Reads/Writes/Params have type annotations
- ✅ All fields have helpful descriptions
- ✅ No duplicate parameters (exclusive params applied)
- ✅ Consistent format within the file
- ✅ Types are valid Python types

## Start Now

Begin by reading the two context documents, then start with the first high-priority file. Update each Interface example systematically, ensuring quality and consistency.

Remember: The goal is to make the documentation match the actual implementation and help developers understand how to use the Enhanced Interface Format effectively. Think hard to get this right.
