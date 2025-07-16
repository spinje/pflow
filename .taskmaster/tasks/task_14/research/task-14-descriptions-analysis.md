# Adding Descriptions to Output Fields - Analysis

## Why This Is Critical

### Current Problem
The planner sees:
```python
- Writes: shared["data"]: dict
    - id: int
    - state: str
    - merged: bool
    - login: str
```

But it doesn't know:
- Is `id` a GitHub issue ID? PR ID? User ID?
- What values can `state` have? ("open", "closed", "draft"?)
- What does `merged` mean in this context?
- Is `login` a username? Email? Display name?

### With Descriptions
```python
- Writes: shared["data"]: dict
    - id: int  # GitHub issue number
    - state: str  # Issue state: "open" or "closed"
    - merged: bool  # Whether PR has been merged
    - login: str  # GitHub username of the author
```

## Benefits for the Planner

1. **Semantic Understanding**
   - "Get the author" → planner knows to use `login` field
   - "Check if PR is merged" → planner knows to check `merged` field

2. **Value Constraints**
   - Knowing `state` can be "open" or "closed" helps generate correct filters
   - Understanding boolean meanings helps with conditional logic

3. **Disambiguation**
   - Multiple "id" fields become clear: `issue.id` vs `user.id` vs `repo.id`
   - Generic names like "data", "value", "result" get context

4. **Better Natural Language Mapping**
   - User says "find PRs by john" → planner knows `user.login` is the username field
   - User says "get open issues" → planner knows to filter `state == "open"`

## Real Example Impact

### GitHub Issue Structure
```python
# Without descriptions - planner has to guess:
- Writes: shared["issue_data"]: dict
    - number: int
    - state: str
    - user: dict
      - login: str
      - type: str
    - assignee: dict
      - login: str

# With descriptions - planner understands:
- Writes: shared["issue_data"]: dict
    - number: int  # Issue number (use for API calls)
    - state: str  # "open" or "closed"
    - user: dict  # Issue creator
      - login: str  # GitHub username
      - type: str  # "User" or "Organization"
    - assignee: dict  # Person assigned to work on this
      - login: str  # GitHub username
```

Now the planner can distinguish between `user` (creator) and `assignee` (assigned to).

## Syntax Options

### Option 1: Inline Comments (Recommended)
```python
- Writes: shared["data"]: dict
    - id: int  # Unique identifier
    - name: str  # Display name (may contain spaces)
    - slug: str  # URL-safe name (lowercase, no spaces)
```
Pros: Familiar Python style, compact
Cons: Need to handle # in parsing

### Option 2: Separate Description Line
```python
- Writes: shared["data"]: dict
    - id: int
      desc: Unique identifier
    - name: str
      desc: Display name (may contain spaces)
```
Pros: Clear structure
Cons: More verbose, more complex parsing

### Option 3: Quoted After Type
```python
- Writes: shared["data"]: dict
    - id: int "Unique identifier"
    - name: str "Display name"
```
Pros: Compact
Cons: New syntax pattern

## Implementation Considerations

1. **Optional but Encouraged**
   - Descriptions are optional to maintain compatibility
   - But strongly recommended for:
     - Ambiguous field names (id, name, value, data)
     - Fields with constrained values (enums, states)
     - Boolean fields (what does true mean?)
     - Nested structures (what is this object for?)

2. **What to Document**
   - Purpose/meaning of the field
   - Possible values for enums/states
   - Format constraints (date formats, ID formats)
   - Relationships to other fields

3. **What NOT to Document**
   - Don't repeat the type
   - Don't describe implementation details
   - Keep it concise (one line)

## Migration Impact

Since we're already updating all nodes for types, adding descriptions now makes sense:
- One migration instead of two
- Developers are already updating docstrings
- Better to get the format right once

## Examples for Common Patterns

```python
# API Response
- Writes: shared["response"]: dict
    - status: int  # HTTP status code (200, 404, etc.)
    - ok: bool  # True if request succeeded
    - data: dict  # API response payload

# File Operations
- Writes: shared["metadata"]: dict
    - size: int  # File size in bytes
    - modified: str  # ISO 8601 timestamp
    - is_directory: bool  # True for directories, False for files

# Error Handling
- Writes: shared["error"]: str  # Human-readable error message
- Writes: shared["error_code"]: str  # Machine-readable error code (e.g., "FILE_NOT_FOUND")
```

## Recommendation

Add optional descriptions using inline comment syntax. This provides maximum value to the planner with minimal format complexity. Since we're already making breaking changes, now is the time to get this right.
