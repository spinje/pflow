# Template Variables Example

## Purpose
This example demonstrates the use of template variables (`$variable` syntax) throughout an IR. It shows:
- Variables in different contexts (URLs, headers, paths, text)
- How variables enable dynamic, reusable workflows
- Variables referencing both input parameters and runtime values

## Use Case
Template variables are essential for:
- Configurable workflows that adapt to different environments
- Reusable workflows with different inputs
- Dynamic content generation
- API integrations with varying endpoints

## Visual Flow
```
[fetch: http-get] → [extract: json-extract] → [notify: send-email]
     ↓                      ↓                         ↓
 $api_endpoint          $data_path              $recipient_email
 $api_token            $default_value           $result, $timestamp
```

## Template Variables Used
- **$api_endpoint**: The API URL to fetch from
- **$api_token**: Authentication token for API access
- **$data_path**: JSON path to extract from response
- **$default_value**: Fallback if extraction fails
- **$recipient_email**: Who to notify
- **$result**: Runtime value from extraction
- **$timestamp**: Runtime value for when processed

## Node Explanation
1. **fetch**: Makes HTTP GET request
   - Uses variables for both URL and auth header

2. **extract**: Extracts data from JSON response
   - Configurable extraction path and default

3. **notify**: Sends email notification
   - Combines static text with multiple variables

## How Variables Are Resolved
Variables are resolved at runtime from:
1. Initial workflow parameters
2. Shared store values set by nodes
3. System-provided values (like $timestamp)

## How to Validate
```python
from pflow.core import validate_ir
import json

with open('template-variables.json') as f:
    ir = json.load(f)
    validate_ir(ir)  # Variables are valid strings

# At runtime, you'd provide values:
# params = {
#     "api_endpoint": "https://api.example.com/data",
#     "api_token": "secret-token",
#     "data_path": "$.results[0].value",
#     "default_value": "N/A",
#     "recipient_email": "user@example.com"
# }
```

## Common Variations
1. **Nested variables**: `"path": "/users/$user_id/posts/$post_id"`
2. **Mixed content**: `"message": "Hello $name, your order #$order_id is ready"`
3. **Conditional defaults**: Different default values based on context
4. **Variable interpolation**: Building complex strings from multiple variables

## Notes
- Variables are treated as literal strings during validation
- The $ prefix is the only special syntax recognized
- Variables can appear anywhere a string value is expected
- Resolution happens at runtime, not during IR validation
