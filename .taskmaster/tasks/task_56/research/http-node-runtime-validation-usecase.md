# HTTP Node Runtime Validation Use Case

## The Problem: Unknown API Response Structures

When users create workflows that interact with APIs, the planner faces a fundamental challenge: **it doesn't know the structure of API responses**. This forces users to either:

1. Use an LLM node to parse every response (expensive, non-deterministic)
2. Manually create workflows with correct field paths (requires API knowledge)
3. Trial-and-error workflow editing (frustrating, time-consuming)

## Current Limitation Example

### User Request
"Fetch GitHub user information for torvalds and extract their username, biography, and number of repositories"

### What the Planner Must Guess
```json
{
  "name": "http",
  "params": {
    "url": "https://api.github.com/users/torvalds",
    "extract": {
      "username": "???",      // Is it $.username? $.user? $.login? $.name?
      "biography": "???",     // Is it $.biography? $.bio? $.description?
      "repositories": "???"   // Is it $.repositories? $.repos? $.public_repos?
    }
  }
}
```

### Current Workaround: LLM Parsing (Inefficient)
```json
{
  "nodes": [
    {
      "name": "http",
      "params": {"url": "https://api.github.com/users/torvalds"}
    },
    {
      "name": "llm",
      "params": {
        "prompt": "Extract username, bio, and repository count from: ${response}",
        "model": "gpt-4"
      }
    }
  ]
}
```

This works but has major drawbacks:
- **Cost**: Every execution uses LLM tokens
- **Speed**: Adds 1-3 seconds per execution
- **Non-deterministic**: LLM might format differently each time
- **Overkill**: Using AI for simple JSON field extraction

## The Solution: Runtime Validation

### Phase 1: Initial Guess
Planner makes educated guess based on common naming patterns:

```json
{
  "name": "http",
  "params": {
    "url": "https://api.github.com/users/torvalds",
    "extract": {
      "username": "$.username",      // Common guess
      "biography": "$.biography",     // Reasonable assumption
      "repositories": "$.repositories" // Logical naming
    }
  }
}
```

### Phase 2: Runtime Error with Context
HTTP node fails but provides helpful error:

```
RuntimeError: Field extraction failed:
- Path '$.username' not found
- Path '$.biography' not found
- Path '$.repositories' not found

Available root fields in response:
[login, id, node_id, avatar_url, gravatar_id, url, html_url, followers_url,
following_url, gists_url, starred_url, subscriptions_url, organizations_url,
repos_url, events_url, received_events_url, type, site_admin, name, company,
blog, location, email, hireable, bio, twitter_username, public_repos,
public_gists, followers, following, created_at, updated_at]

Response structure sample:
{
  "login": "torvalds",
  "bio": "None",
  "public_repos": 7,
  ...
}
```

### Phase 3: Automatic Correction
Planner receives error and corrects based on actual structure:

```json
{
  "name": "http",
  "params": {
    "url": "https://api.github.com/users/torvalds",
    "extract": {
      "username": "$.login",           // Corrected from error
      "biography": "$.bio",             // Corrected from error
      "repositories": "$.public_repos"  // Corrected from error
    }
  }
}
```

### Phase 4: Success and Save
Workflow executes successfully and saves with correct paths for future use.

## Real-World API Examples

### Example 1: Weather API
**User**: "Get current temperature and humidity for Seattle"

**Guess**: `$.temperature`, `$.humidity`
**Actual**: `$.main.temp`, `$.main.humidity`
**Corrected automatically!**

### Example 2: Stock API
**User**: "Fetch Apple stock price and volume"

**Guess**: `$.price`, `$.volume`
**Actual**: `$.quote.latestPrice`, `$.quote.latestVolume`
**Corrected automatically!**

### Example 3: News API
**User**: "Get top headlines and their sources"

**Guess**: `$.headlines`, `$.sources`
**Actual**: `$.articles[*].title`, `$.articles[*].source.name`
**Corrected with array notation!**

## Benefits for HTTP Node Specifically

1. **No API Documentation Required**
   - Users don't need to study API docs
   - System learns structure by trying

2. **Deterministic After Learning**
   - Once corrected, extraction is pure JSONPath
   - No LLM needed for future executions

3. **Progressive Enhancement**
   - Start with full response
   - Gradually add specific extractions
   - Refine based on actual usage

4. **Error Messages Guide Correction**
   - Show available fields
   - Suggest similar field names
   - Provide structure samples

## Implementation Requirements for HTTP Node

### 1. Enhanced exec() Method
```python
def exec(self, prep_res):
    response = requests.request(...)

    if "extract" in prep_res:
        result = {}
        errors = []

        for key, json_path in prep_res["extract"].items():
            try:
                value = jsonpath_extract(response.json(), json_path)
                if value is None:
                    errors.append({
                        "key": key,
                        "path": json_path,
                        "available": self._get_available_paths(response.json())
                    })
                else:
                    result[key] = value
            except Exception as e:
                errors.append({"key": key, "path": json_path, "error": str(e)})

        if errors:
            raise RuntimeValidationError(
                errors=errors,
                structure=self._sample_structure(response.json()),
                available_fields=self._list_all_paths(response.json())
            )

        return {"extracted": result, "raw": response.json()}
```

### 2. Helpful Error Messages
```python
class RuntimeValidationError(Exception):
    def __init__(self, errors, structure, available_fields):
        self.errors = errors
        self.structure = structure
        self.available_fields = available_fields

        message = "Field extraction failed:\n"
        for err in errors:
            message += f"- Path '{err['path']}' for key '{err['key']}' not found\n"
        message += f"\nAvailable paths: {available_fields[:20]}..."
        message += f"\nStructure sample: {json.dumps(structure, indent=2)[:500]}..."

        super().__init__(message)
```

### 3. JSONPath Support
```python
# Support various JSONPath expressions:
"$.field"                  # Simple field
"$.nested.field"          # Nested object
"$.array[0]"              # Array index
"$.array[*].field"        # Array mapping
"$..field"                # Recursive descent
"$.data[?(@.active)]"     # Filtering
```

## Success Metrics

1. **Reduction in LLM Usage**
   - 80% fewer LLM calls for API data extraction
   - Deterministic extraction after initial learning

2. **Faster Workflow Development**
   - No need to consult API documentation
   - Automatic correction vs manual trial-and-error

3. **Better User Experience**
   - Clear error messages with solutions
   - Progressive refinement of workflows
   - "It just works" feeling

## Future Extensions

### Intelligent Field Matching
Use fuzzy matching or embeddings to suggest likely field mappings:
- User wants "username" → Suggest "login" (high similarity)
- User wants "biography" → Suggest "bio" (substring match)

### Schema Caching
Remember API structures across workflows:
- First user hits GitHub API → Learn structure
- Next user → Reuse knowledge

### Type Validation
Beyond field existence, validate types:
- Expected string, got number
- Expected array, got object

## Conclusion

Runtime validation transforms the HTTP node from a simple request maker into an intelligent API adapter that learns structures through use. This eliminates the need for users to understand API documentation or use expensive LLM parsing for simple field extraction, making API integration workflows both easier to create and more efficient to run.