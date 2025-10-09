# Task 80: Implement API Key Management via Settings

## ID
80

## Title
Implement API Key Management via Settings

## Description
Enable users to store API keys in `~/.pflow/settings.json` that automatically populate workflow inputs, eliminating the need to manually provide keys for every workflow execution. This improves the local development experience by allowing users to set their API keys once and use them across all workflows.

## Status
not started

## Dependencies
- Task 50: Node Filtering System with Settings Management - The settings.py infrastructure is already in place with an unused `env` field that this task will implement

## Priority
medium

## Details
Currently, users must provide API keys either as environment variables or as workflow inputs every time they run a workflow. This is cumbersome for local development where users repeatedly run workflows with the same credentials.

The solution implements **Option 2: Auto-populate workflow inputs from matching keys** in the existing `env` field of settings.json:

### Implementation Approach
- Store API keys in `~/.pflow/settings.json` under the existing `env` field (currently defined but unused at line 34 of `settings.py`)
- When a workflow declares an input (e.g., `replicate_api_token`), check if a matching key exists in `settings.env`
- If found and not provided via CLI, use the value from settings as the default
- CLI arguments always take precedence over settings values
- No changes needed to workflow IR format or existing workflows

### Key Design Decisions (MVP Approach)
- Simple key-value storage in plain text (following AWS CLI pattern)
- Direct name matching: workflow input name must exactly match settings key
- No complex mapping or transformation logic
- File permissions set to 600 for security
- No encryption in v1 (standard practice for CLI tools like AWS CLI)

### Technical Considerations
- Modify workflow executor to check settings.env when populating workflow inputs
- Add CLI commands for managing env settings (set-env, list-env, unset-env)
- Ensure file permissions are restrictive (chmod 600)
- Mask values when displaying in list-env command
- Document security implications clearly

### Example Usage
```bash
# Set API keys once
pflow settings set-env replicate_api_token r8_xxx
pflow settings set-env dropbox_token sl.xxx

# Run workflow without specifying tokens
pflow spotify-art-generator --sheet_id abc123
# Keys are automatically populated from settings!
```

### Settings Structure
```json
{
  "version": "1.0.0",
  "registry": { ... },
  "env": {
    "replicate_api_token": "r8_xxx",
    "dropbox_token": "sl.xxx",
    "OPENAI_API_KEY": "sk-...",
    "GITHUB_TOKEN": "ghp_..."
  }
}
```

## Test Strategy
Testing will ensure proper key management, security, and precedence rules:

- Unit tests for SettingsManager env field operations (get, set, list, unset)
- Test that workflow inputs are correctly populated from settings.env
- Test CLI argument precedence (CLI args override settings values)
- Test file permission setting (should be 600 after save)
- Test value masking in list-env command output
- Integration test with real workflow execution using settings-based keys
- Test handling of missing keys (should error as today)
- Test concurrent access to settings file
- Verify no regression in existing settings functionality (node filtering)