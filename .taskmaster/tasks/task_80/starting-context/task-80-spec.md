# Feature: api_key_management_settings

## Objective

Enable automatic workflow input population from persistent API key storage.

## Requirements

- Must have existing SettingsManager with functional env field
- Must have workflow executor that populates workflow inputs
- Must have CLI command structure for settings management
- Must have file permission control capability

## Scope

- Does not encrypt stored keys
- Does not integrate with OS keychains
- Does not modify existing environment variables
- Does not validate API key formats
- Does not support key rotation scheduling
- Does not modify workflow IR schema

## Inputs

- `set_env_key`: str - Environment variable name to set
- `set_env_value`: str - Environment variable value to store
- `unset_env_key`: str - Environment variable name to remove
- `list_env_flags`: dict[str, bool] - Options for listing (show_values: bool)
- `workflow_inputs`: dict[str, Any] - Declared workflow input requirements
- `cli_params`: dict[str, Any] - User-provided CLI parameters

## Outputs

Returns:
- `set_env`: bool - True if key set successfully
- `unset_env`: bool - True if key removed successfully
- `list_env`: list[dict[str, str]] - List of env entries with key and optionally masked value
- `populated_inputs`: dict[str, Any] - Merged workflow inputs with settings values
- `settings_path`: Path - Path to settings file after operation

Side effects:
- Settings file created if not exists
- Settings file permissions set to 600
- Settings file content updated atomically

## Structured Formats

```json
{
  "settings_env": {
    "type": "dict[str, str]",
    "example": {
      "replicate_api_token": "r8_xxx",
      "dropbox_token": "sl.xxx",
      "OPENAI_API_KEY": "sk-..."
    }
  },
  "list_output": {
    "type": "list[dict]",
    "schema": {
      "key": "str",
      "value": "str | masked"
    },
    "example": [
      {"key": "replicate_api_token", "value": "r8_***"},
      {"key": "OPENAI_API_KEY", "value": "sk-***"}
    ]
  }
}
```

## State/Flow Changes

- None

## Constraints

- Settings file path: ~/.pflow/settings.json
- File permissions: 600 (owner read/write only)
- Key names: valid Python identifiers or uppercase with underscores
- Value masking: show first 3 chars then asterisks

## Rules

1. If settings file does not exist then create with empty env dict
2. If set_env with existing key then overwrite value
3. If set_env with new key then add to env dict
4. If unset_env with existing key then remove from dict
5. If unset_env with non-existent key then return False
6. If list_env with show_values=false then mask all values
7. If list_env with show_values=true then show full values
8. If workflow input name matches settings env key then use settings value
9. If workflow input provided via CLI then use CLI value
10. If workflow input not in CLI and not in settings then raise error
11. Always set file permissions to 600 after write
12. Always use atomic file operations for updates
13. CLI parameters always override settings values
14. Settings values only apply to declared workflow inputs

## Edge Cases

- Settings file corrupted → use defaults and log warning
- Settings file wrong permissions → fix permissions automatically
- Empty env dict → valid state
- Key with empty string value → valid state
- Key with whitespace → trim whitespace
- Unicode characters in values → preserve as-is
- Concurrent access → last write wins
- Settings path not writable → raise permission error

## Error Handling

- File permission denied → raise PermissionError with fix instructions
- Invalid JSON in settings → log warning and use defaults
- Non-string value in env → convert to string
- File system full → raise IOError

## Non-Functional Criteria

- File operations complete < 100ms
- Atomic writes prevent corruption
- Masking preserves first 3 characters for identification
- Settings persist across pflow sessions

## Examples

Setting a key:
```bash
pflow settings set-env replicate_api_token r8_xxx
# Returns: True, file updated
```

Workflow input population:
```python
# settings.env: {"replicate_api_token": "r8_xxx"}
# workflow inputs: {"replicate_api_token": {"required": true}}
# cli params: {}
# Result: populated_inputs = {"replicate_api_token": "r8_xxx"}
```

CLI override:
```python
# settings.env: {"replicate_api_token": "r8_old"}
# cli params: {"replicate_api_token": "r8_new"}
# Result: populated_inputs = {"replicate_api_token": "r8_new"}
```

## Test Criteria

1. Create settings file if not exists → verify file created with empty env
2. Set new env key → verify key added to settings
3. Overwrite existing env key → verify value updated
4. Remove existing env key → verify key removed
5. Remove non-existent env key → verify returns False
6. List env with masking → verify values show first 3 chars + asterisks
7. List env without masking → verify full values shown
8. Workflow input matches settings key → verify settings value used
9. CLI parameter provided → verify CLI value overrides settings
10. Input not in CLI or settings → verify error raised
11. File permissions after write → verify 600 permissions
12. Concurrent writes → verify last write persists
13. Corrupted settings file → verify defaults used with warning
14. Fix wrong permissions → verify permissions corrected to 600
15. Empty env dict → verify valid operations
16. Empty string value → verify preserved
17. Whitespace in key → verify trimmed
18. Unicode in values → verify preserved correctly
19. Permission denied → verify PermissionError with instructions
20. Invalid JSON → verify warning and defaults
21. Non-string env value → verify converted to string
22. File system full → verify IOError raised
23. Settings persist → verify values available in new session
24. Atomic write → verify no partial updates on failure

## Notes (Why)

- Plain text storage follows AWS CLI standard practice for developer tools
- Option 2 (auto-populate matching keys) chosen for simplicity over complex mappings
- CLI override precedence enables CI/CD flexibility
- File permission 600 provides reasonable local security
- Atomic writes prevent corruption during concurrent access
- Masking balances security with usability for list command

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
| ------ | -------------------------- |
| 1      | 1                          |
| 2      | 3                          |
| 3      | 2                          |
| 4      | 4                          |
| 5      | 5                          |
| 6      | 6                          |
| 7      | 7                          |
| 8      | 8                          |
| 9      | 9                          |
| 10     | 10                         |
| 11     | 11                         |
| 12     | 12, 24                     |
| 13     | 9                          |
| 14     | 8, 10                      |

## Versioning & Evolution

- v1.0.0 - Initial API key management implementation

## Epistemic Appendix

### Assumptions & Unknowns

- Assumes SettingsManager.env field exists but is currently unused (verified in code at line 34)
- Assumes workflow executor can be modified to check settings before execution
- Assumes users understand plain text storage security implications
- Unknown: exact integration point in workflow executor for input population

### Conflicts & Resolutions

- User conversation preferred Option 2 (auto-populate) over Option 1 (env injection) - Resolution: spec follows Option 2

### Decision Log / Tradeoffs

- Plain text vs encryption: Chose plain text for MVP simplicity following AWS CLI pattern
- Direct name matching vs complex mapping: Chose direct matching for determinism
- Environment injection vs input population: Chose input population to avoid side effects
- Mask all vs show first chars: Chose partial masking for usability

### Ripple Effects / Impact Map

- WorkflowExecutor must check settings.env during input validation
- CLI must add new settings subcommands (set-env, unset-env, list-env)
- SettingsManager save() must set file permissions
- Documentation must explain security implications

### Residual Risks & Confidence

- Risk: API keys exposed if settings.json committed to git - Mitigation: documentation and .gitignore
- Risk: Plain text storage security - Mitigation: file permissions 600
- Risk: Key naming collisions - Mitigation: exact matching only
- Confidence: High for implementation, Medium for user adoption

### Epistemic Audit (Checklist Answers)

1. Assumed settings.env exists unused and workflow executor is modifiable
2. Wrong assumptions would require different integration approach
3. Prioritized robustness (atomic writes, permissions) over elegance
4. All rules have corresponding tests
5. Touches SettingsManager, WorkflowExecutor, and CLI
6. Integration point in executor uncertain; Confidence: High for design, Medium for integration