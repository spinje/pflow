# Structured Metadata for Path-Based Proxy Mapping Validation

## Overview

This document describes a future enhancement to support full validation of path-based proxy mappings in pflow. Currently, the planner can generate sophisticated mappings like `"issue_data.user.login"`, but validation is limited to checking that root keys exist.

## The Current Limitation

### What We Have Now
Node metadata currently provides simple lists of input/output keys:
```python
# From metadata extraction
{
    "github-get-issue": {
        "inputs": ["issue_number", "repo"],
        "outputs": ["issue_data", "issue_title"]
    }
}
```

### What We Can't Validate
When the planner generates path-based mappings:
```json
{
    "input_mappings": {
        "author_name": "issue_data.user.login",
        "bug_label": "issue_data.labels[?name=='bug']",
        "first_comment": "issue_data.comments[0].body"
    }
}
```

We can only verify that `issue_data` exists, not whether:
- It has a `user` property with a `login` field
- It contains a `labels` array with objects having `name` properties
- It includes a `comments` array with at least one item

## Why This Matters

### 1. Runtime Failures
Invalid paths cause runtime errors that could have been caught during planning:
- User sees "Cannot read property 'login' of undefined"
- Workflow fails after potentially expensive operations
- Debugging requires understanding the data structure

### 2. Limited Planner Intelligence
Without structure information, the planner relies entirely on the LLM's training knowledge:
- GitHub API structures are well-known and usually work
- Custom or internal APIs have no documentation
- API version changes aren't reflected

### 3. Missed Optimization Opportunities
Path-based mappings can eliminate intermediate nodes, but only if we're confident the paths are valid:
```
# Current (safe but verbose):
api-call >> json-extract-user >> json-extract-login >> process-author

# Could be (with validation):
api-call >> process-author  # with mapping: {"author": "response.user.login"}
```

## The Needed Enhancement

### Structured Output Definitions
Nodes need a way to declare the structure of their outputs, not just the key names. This would enable:

1. **Full path validation** - Verify every segment of a path exists
2. **Type checking** - Ensure array access on arrays, property access on objects
3. **Better planner hints** - LLM can see available paths without guessing
4. **IDE-like autocomplete** - Future tooling could suggest valid paths

### Benefits Beyond Validation

1. **Documentation** - Developers understand what data shapes to expect
2. **Contract enforcement** - Nodes can't change output structure without updating metadata
3. **Testing** - Generate test data matching declared structures
4. **Migration tools** - Detect breaking changes between node versions

## Scope and Complexity

This enhancement involves:
- Extending metadata extraction to parse structure definitions
- Choosing a schema format (JSON Schema, TypeScript-like, custom)
- Updating validation to traverse paths using schema information
- Backwards compatibility with existing simple metadata

## Why It's Deferred

1. **MVP can function without it** - LLMs know common API structures
2. **Complexity vs. value** - Significant work for edge case prevention
3. **Learning opportunity** - Real usage will show which nodes need structure docs
4. **Iterative enhancement** - Can be added without breaking changes

## Related Future Work

- **Type system for pflow** - Full type checking across workflows
- **Schema inference** - Learn structures from successful executions
- **API versioning** - Handle different API versions in mappings
- **Visual path builder** - GUI for constructing valid paths

## Conclusion

While path-based proxy mappings are powerful and included in MVP, full validation requires structured metadata that is deferred to a future version. The current approach of validating root keys and trusting LLM knowledge is sufficient for initial release, with clear errors at runtime for invalid paths.
