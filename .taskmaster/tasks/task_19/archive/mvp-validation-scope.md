# MVP Validation Fix: What We're Actually Building

## The Problem (Simple)
Template validator guesses which variables come from nodes using a hardcoded list. If your variable isn't "content" or "result", it fails validation even when a node provides it.

## The Solution (Simple)
Look at what nodes actually write instead of guessing.

## The Implementation (Still Simple)

### 1. Scanner Update (~20 lines)
```python
# Add to existing scanner
from pflow.registry.metadata_extractor import MetadataExtractor

# In extract_metadata():
extractor = MetadataExtractor()
parsed = extractor.extract_metadata(cls)
metadata["interface"] = parsed  # That's it!
```

### 2. Context Builder Simplification (Remove ~100 lines)
```python
# Before: Dynamic imports and parsing
# After: Just use registry data
interface = node_info["interface"]
```

### 3. Validator Fix (~30 lines)
```python
# Get what nodes write from registry
for output in interface["outputs"]:
    written_vars.add(output["key"])

# Now validation is accurate!
```

## What We're NOT Doing (Unnecessary Complexity)

❌ **Backward compatibility** - Just regenerate registry
❌ **Migration strategies** - It's a one-time update
❌ **Complex error recovery** - Basic try/except is enough
❌ **Minimal metadata** - Store everything (context builder needs it anyway)
❌ **New parsing code** - MetadataExtractor already exists

## Why This is the Right MVP Approach

1. **We're moving code, not adding it** - Parser already exists, just runs at scan time now
2. **Multiple problems solved** - Validation + context builder performance + Task 17 prep
3. **Clean architecture** - Parse once, use everywhere
4. **No user impact** - System is pre-release

## Complexity Analysis

**Actual new code**: ~50 lines total
**Code removed**: ~100 lines from context builder
**Net result**: LESS code, better architecture

The "complexity" in the implementation doc is mostly:
- Explaining the existing system
- Showing what MetadataExtractor already does
- Being thorough about edge cases

But the actual implementation is quite simple!
