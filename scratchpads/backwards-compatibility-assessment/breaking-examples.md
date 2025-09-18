# Breaking Change Examples: Template Parameter Skipping

## Examples of Workflows That Would Break

### 1. Debugging Workflow Pattern

**Current workflow that would break:**
```json
{
  "ir_version": "0.1.0",
  "inputs": {
    "config_file": {
      "type": "string",
      "required": false,
      "description": "Optional config file path"
    }
  },
  "nodes": [
    {
      "id": "debug_info",
      "type": "write-file",
      "params": {
        "file_path": "debug.log",
        "content": "Config: ${config_file}, Missing: ${undefined_param}, Runtime: ${runtime_data}"
      }
    }
  ]
}
```

**Current output (when config_file not provided):**
```
Config: ${config_file}, Missing: ${undefined_param}, Runtime: ${runtime_data}
```

**New output (with parameter skipping):**
```
Config: , Missing: , Runtime:
```

**User impact:** Loss of debugging information about which parameters are missing.

### 2. Template Literal Workflow

**Workflow expecting literal template syntax:**
```json
{
  "nodes": [
    {
      "id": "generate_template",
      "type": "write-file",
      "params": {
        "file_path": "template.txt",
        "content": "Dear ${customer_name}, your order ${order_id} is ready."
      }
    }
  ]
}
```

**Current behavior:** Generates template file with literal `${customer_name}` and `${order_id}`
**New behavior:** Generates template file with empty strings: `"Dear , your order  is ready."`

**User impact:** Template files become malformed.

### 3. Conditional Logic Based on Unresolved State

**Advanced workflow pattern:**
```json
{
  "nodes": [
    {
      "id": "check_env",
      "type": "write-file",
      "params": {
        "file_path": "status.txt",
        "content": "Environment: ${ENVIRONMENT_TYPE}, API: ${API_ENDPOINT}"
      }
    },
    {
      "id": "validate_config",
      "type": "shell",
      "params": {
        "command": "if grep -q '${' status.txt; then echo 'Missing config detected'; exit 1; fi"
      }
    }
  ]
}
```

**Current behavior:** Shell command can detect unresolved templates
**New behavior:** Shell command would not detect missing config (false negative)

**User impact:** Configuration validation logic breaks.

## Examples of Workflows That Would Continue Working

### 1. Normal Input Parameter Usage

**Standard workflow (CONTINUES WORKING):**
```json
{
  "ir_version": "0.1.0",
  "inputs": {
    "source_file": {"type": "string", "required": true},
    "destination": {"type": "string", "required": true}
  },
  "nodes": [
    {
      "id": "copy",
      "type": "copy-file",
      "params": {
        "source": "${source_file}",
        "destination": "${destination}"
      }
    }
  ]
}
```

**Behavior:** Unchanged - all templates resolve properly.

### 2. Node-to-Node Data Flow

**Data pipeline (CONTINUES WORKING):**
```json
{
  "nodes": [
    {
      "id": "read_data",
      "type": "read-file",
      "params": {"file_path": "input.txt"}
    },
    {
      "id": "process",
      "type": "llm",
      "params": {
        "prompt": "Summarize: ${read_data.content}"
      }
    },
    {
      "id": "save",
      "type": "write-file",
      "params": {
        "file_path": "output.txt",
        "content": "${process.response}"
      }
    }
  ]
}
```

**Behavior:** Unchanged - all node outputs resolve correctly.

### 3. Mixed Resolved/Unresolved (BEHAVIOR CHANGE)

**Workflow with mix of resolved and unresolved:**
```json
{
  "inputs": {
    "title": {"type": "string", "required": true}
  },
  "nodes": [
    {
      "id": "generate",
      "type": "write-file",
      "params": {
        "file_path": "report.txt",
        "content": "Title: ${title}\nAuthor: ${author}\nDate: ${date}"
      }
    }
  ]
}
```

**Current behavior:**
```
Title: My Report
Author: ${author}
Date: ${date}
```

**New behavior:**
```
Title: My Report
Author:
Date:
```

**User impact:** Different output format, but workflow still completes successfully.

## Migration Examples

### For Debugging Workflows

**Old approach:**
```json
{
  "params": {
    "message": "Config: ${config_file}, API: ${api_url}"
  }
}
```

**New debugging approaches:**

**Option A - Use log analysis:**
```bash
# Check pflow logs for template resolution warnings
uv run pflow workflow.json --trace | grep "could not be resolved"
```

**Option B - Add explicit defaults:**
```json
{
  "inputs": {
    "config_file": {"type": "string", "required": false, "default": "[not provided]"},
    "api_url": {"type": "string", "required": false, "default": "[not configured]"}
  },
  "params": {
    "message": "Config: ${config_file}, API: ${api_url}"
  }
}
```

**Option C - Add validation nodes:**
```json
{
  "nodes": [
    {
      "id": "validate",
      "type": "shell",
      "params": {
        "command": "echo 'Checking required env vars...'; test -n \"$CONFIG_FILE\" && test -n \"$API_URL\""
      }
    }
  ]
}
```

### For Template Generation

**Old approach (generates literal templates):**
```json
{
  "params": {
    "content": "Hello ${customer_name}"
  }
}
```

**New approach (escape or use different syntax):**
```json
{
  "params": {
    "content": "Hello \\${customer_name}"  // Escaped template
  }
}
```

**Or use a different template system:**
```json
{
  "params": {
    "content": "Hello {{customer_name}}"  // Different template syntax
  }
}
```

## Test Update Examples

### Template Resolver Tests

**Current test (WOULD BREAK):**
```python
def test_preserves_unresolved_templates(self):
    """Test that unresolved templates remain unchanged."""
    context = {"found": "yes"}
    template = "Found: ${found}, Missing: ${missing}"
    # OLD EXPECTATION:
    assert TemplateResolver.resolve_string(template, context) == "Found: yes, Missing: ${missing}"
```

**Updated test:**
```python
def test_skips_unresolved_templates(self):
    """Test that unresolved templates are skipped."""
    context = {"found": "yes"}
    template = "Found: ${found}, Missing: ${missing}"
    # NEW EXPECTATION:
    assert TemplateResolver.resolve_string(template, context) == "Found: yes, Missing: "
```

### Node Wrapper Tests

**Current test (WOULD BREAK):**
```python
def test_unresolved_templates_remain(self):
    assert "'missing': '${undefined}'" in shared["result"]
```

**Updated test:**
```python
def test_unresolved_templates_skipped(self):
    assert "'missing': ''" in shared["result"]  # Empty string instead
```

## Summary

**Workflows that break:** Primarily debugging and template generation workflows
**Workflows that continue:** Standard data processing workflows (majority)
**Migration effort:** Low to medium - mostly requires updating expectations rather than workflow logic
