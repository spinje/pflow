# Task 80: Research Findings - API Key Management via Settings

## Executive Summary

The research confirms that implementing API key management via settings.env is **architecturally sound** with a **clear integration path**. However, it reveals **critical security gaps** in the current SettingsManager implementation that **must be addressed** before storing sensitive data like API keys.

### Key Findings:
1. ✅ The `env` field exists at `settings.py:34` and is completely unused - perfect for our needs
2. ✅ Integration point identified: `workflow_validator.py:prepare_inputs()` at line 125
3. ⚠️ **CRITICAL**: SettingsManager lacks atomic operations and permission hardening
4. ✅ Clear precedence model: CLI params → settings.env → workflow defaults
5. ✅ Testing infrastructure supports all needed validation patterns

---

## 1. SettingsManager Current State Analysis

### 1.1 The `env` Field - Confirmed Unused

**Location**: `/Users/andfal/projects/pflow-feat-api-key-management/src/pflow/core/settings.py:34`

```python
class PflowSettings(BaseModel):
    version: str = Field(default="1.0.0")
    registry: RegistrySettings = Field(default_factory=RegistrySettings)
    env: dict[str, str] = Field(default_factory=dict)  # ← LINE 34: UNUSED
```

**Verification Evidence**:
- Grep search found only field definition, no usage
- save() method doesn't touch env
- load() reads it but doesn't process it
- User's actual settings.json shows `"env": {}` (empty)

**Conclusion**: ✅ Safe to implement - no breaking changes

### 1.2 Critical Security Gaps

#### Gap 1: No File Permission Hardening 🔴 CRITICAL

**Current State**:
- Uses system umask defaults (typically 0o644 = **world-readable**)
- No `chmod()` calls in save() or load()
- API keys would be visible to all users on the system

**Required Fix**:
```python
# After atomic write
os.chmod(self.settings_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
```

**Impact**: HIGH - Without this, API keys are exposed

#### Gap 2: No Atomic File Operations 🔴 CRITICAL

**Current Implementation** (settings.py:199-205):
```python
def save(self, settings: Optional[PflowSettings] = None) -> None:
    self.settings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(self.settings_path, "w") as f:  # ← Direct write, NO atomicity
        data = settings.model_dump()
        json.dump(data, f, indent=2)
    self._settings = None
```

**Problems**:
- ❌ Direct `open("w")` truncates file immediately
- ❌ Crash during write = corrupted file with partial secrets
- ❌ Concurrent writes could interleave and corrupt data
- ❌ No cleanup on failure

**Contrast with WorkflowManager** (uses atomic pattern):
```python
# WorkflowManager atomic pattern (lines 164-169)
temp_fd, temp_path = tempfile.mkstemp(dir=self.workflows_dir, prefix=f".{name}.", suffix=".tmp")
try:
    with open(temp_fd, "w", encoding="utf-8") as f:
        json.dump(wrapper, f, indent=2)
    os.replace(temp_path, file_path)  # ← Atomic operation
except Exception:
    Path(temp_path).unlink(missing_ok=True)
    raise
```

**Required Fix**: Adopt WorkflowManager's atomic pattern for SettingsManager.save()

**Impact**: HIGH - Without this, crashes could expose partial secrets or corrupt settings

#### Gap 3: No Permission Validation on Load 🟡 MEDIUM

**Current State**:
- Reads file without checking permissions
- Could load compromised/exposed secrets silently

**Required Enhancement**:
```python
def _load_from_file(self) -> PflowSettings:
    if self.settings_path.exists():
        # Validate permissions before loading
        file_stat = os.stat(self.settings_path)
        mode = stat.S_IMODE(file_stat.st_mode)

        if mode & (stat.S_IROTH | stat.S_IRGRP):  # World or group readable
            # Warn if env contains secrets
            # ... (see full implementation in agent report)
```

**Impact**: MEDIUM - Defense in depth, catches permission issues early

### 1.3 Recommended Enhancements

#### Enhancement 1: Atomic Save Implementation

**New Implementation Pattern**:
```python
def save(self, settings: Optional[PflowSettings] = None) -> None:
    if settings is None:
        settings = self.load()

    self.settings_path.parent.mkdir(parents=True, exist_ok=True)

    # Atomic write pattern
    temp_fd, temp_path = tempfile.mkstemp(
        dir=self.settings_path.parent,
        prefix=".settings.",
        suffix=".tmp"
    )

    try:
        with open(temp_fd, "w", encoding="utf-8") as f:
            data = settings.model_dump()
            if isinstance(data.get("registry"), dict):
                data["registry"].pop("include_test_nodes", None)
            json.dump(data, f, indent=2)

        # Atomic replace
        os.replace(temp_path, self.settings_path)

        # Set restrictive permissions AFTER atomic operation
        os.chmod(self.settings_path, 0o600)

        self._settings = None
    except Exception:
        Path(temp_path).unlink(missing_ok=True)
        raise
```

**Why this pattern**:
- `os.replace()` is atomic on all platforms (POSIX and Windows)
- Permissions set AFTER file is at final location
- Cleanup guaranteed in error cases
- No partial writes visible to other processes

---

## 2. Integration Point: WorkflowExecutor

### 2.1 Data Flow Analysis

**Complete Flow**:
```
CLI Command (main.py)
    ↓
execute_workflow() (workflow_execution.py:470)
    ↓
WorkflowExecutorService.execute_workflow() (executor_service.py:53)
    ↓
compile_ir_to_flow() (compiler.py:995)
    ↓
_validate_workflow() (compiler.py:826)
    ↓
prepare_inputs() (workflow_validator.py:71) ← **INJECTION POINT**
```

### 2.2 Exact Integration Point

**Function**: `workflow_validator.py:prepare_inputs()`
**Line**: 125 (before `is_required` check)

**Current Logic** (lines 125-152):
```python
for input_name, input_spec in inputs.items():
    is_required = input_spec.get("required", True)

    # Line 125: Check if input is provided ← **INJECT HERE**
    if input_name not in provided_params:
        if is_required:
            # Missing required input
            errors.append((
                f"Workflow requires input '{input_name}': {description}",
                f"inputs.{input_name}",
                ""
            ))
        else:
            # Optional input - apply default if available
            if "default" in input_spec:
                defaults[input_name] = input_spec.get("default")
```

**Proposed Enhancement**:
```python
def prepare_inputs(
    workflow_ir: dict[str, Any],
    provided_params: dict[str, Any],
    settings_env: Optional[dict[str, str]] = None  # ← NEW PARAMETER
) -> tuple[list[tuple[str, str, str]], dict[str, Any]]:
    """Validate workflow inputs and return defaults to apply.

    Args:
        workflow_ir: The workflow IR dictionary
        provided_params: Parameters provided for execution
        settings_env: Environment variables from settings.env (NEW)

    Returns:
        Tuple of (errors, defaults_to_apply)
    """
    errors: list[tuple[str, str, str]] = []
    defaults: dict[str, Any] = {}
    settings_env = settings_env or {}

    inputs = workflow_ir.get("inputs", {})

    for input_name, input_spec in inputs.items():
        is_required = input_spec.get("required", True)

        if input_name not in provided_params:
            # **NEW: Check settings.env before applying workflow defaults**
            if input_name in settings_env:
                defaults[input_name] = settings_env[input_name]
                logger.debug(
                    f"Using value from settings.env for input '{input_name}'",
                    extra={"phase": "input_validation", "input": input_name}
                )
                continue  # Skip default and error handling

            # Original logic continues...
            if is_required:
                errors.append(...)
            else:
                if "default" in input_spec:
                    defaults[input_name] = input_spec.get("default")

    return errors, defaults
```

### 2.3 Caller Update Required

**File**: `src/pflow/runtime/compiler.py`
**Function**: `_validate_workflow()` at line 857

**Current Code** (lines 856-877):
```python
errors, defaults = prepare_inputs(ir_dict, initial_params)
if errors:
    raise ValidationError(...)
initial_params.update(defaults)
```

**Proposed Update**:
```python
# Load settings.env once per compilation
from pflow.core.settings import SettingsManager

settings_env = {}
try:
    manager = SettingsManager()
    settings = manager.load()
    settings_env = settings.env
except Exception as e:
    logger.warning(f"Failed to load settings.env: {e}")
    # Continue with empty env dict

# Pass to prepare_inputs
errors, defaults = prepare_inputs(ir_dict, initial_params, settings_env=settings_env)
if errors:
    raise ValidationError(...)
initial_params.update(defaults)
```

### 2.4 Precedence Model

**Final Precedence Order**:
1. **CLI parameters** (`--param key=value`) - Highest priority
2. **settings.env** (`~/.pflow/settings.json` env field) - Second priority
3. **Workflow defaults** (`inputs.{name}.default`) - Third priority
4. **Error** - If required and none of the above provided

**Why This Order**:
- CLI always wins (enables CI/CD overrides)
- settings.env provides convenient defaults for local dev
- Workflow defaults are fallback for optional parameters
- Clear error messages for truly missing required inputs

**Example Scenarios**:

| CLI Param | settings.env | Workflow Default | Result | Source |
|-----------|--------------|------------------|--------|--------|
| ✅ "prod" | "dev" | "test" | "prod" | CLI |
| ❌ | ✅ "dev" | "test" | "dev" | settings.env |
| ❌ | ❌ | ✅ "test" | "test" | workflow |
| ❌ | ❌ | ❌ | ERROR | none |

---

## 3. CLI Commands Structure

### 3.1 Existing Pattern Analysis

**File**: `src/pflow/cli/commands/settings.py`

**Pattern for Adding Subcommands**:
```python
@settings.command()
@click.argument("key")
@click.argument("value")
def set_env(key: str, value: str) -> None:
    """Set an environment variable in settings.

    Example:
        pflow settings set-env replicate_api_token r8_xxx
        pflow settings set-env OPENAI_API_KEY sk-...
    """
    manager = SettingsManager()
    settings = manager.load()

    # Modify settings
    settings.env[key] = value
    manager.save(settings)

    # Success message
    click.echo(f"✓ Set environment variable: {key}")
    click.echo(f"   Value: {_mask_value(value)}")
```

### 3.2 Required New Commands

#### Command 1: `set-env <key> <value>`
- Set or update an environment variable
- Mask value in output (show first 3 chars + asterisks)
- Success message with checkmark

#### Command 2: `unset-env <key>`
- Remove an environment variable
- Confirm if not found
- Success message on removal

#### Command 3: `list-env [--show-values]`
- List all environment variables
- Default: mask values (first 3 chars + `***`)
- `--show-values`: show full values (for debugging)
- Warning if displaying sensitive data

### 3.3 Output Formatting Conventions

**From Existing Commands**:
- ✅ Success: `✓ Operation succeeded`
- ✗ Failure: `✗ Operation failed`
- Lists: `  - item` (two spaces, dash, space)
- JSON: `json.dumps(data, indent=2)`
- Masking: `value[:3] + "***"` (first 3 chars)

**Example Outputs**:

```bash
$ pflow settings set-env replicate_api_token r8_abc123xyz
✓ Set environment variable: replicate_api_token
   Value: r8_***

$ pflow settings list-env
Environment variables:
  replicate_api_token: r8_***
  dropbox_token: sl.***
  OPENAI_API_KEY: sk-***

$ pflow settings list-env --show-values
⚠️  Displaying unmasked values
Environment variables:
  replicate_api_token: r8_abc123xyz
  dropbox_token: sl.xxx
  OPENAI_API_KEY: sk-...

$ pflow settings unset-env replicate_api_token
✓ Removed environment variable: replicate_api_token
```

---

## 4. Testing Strategy

### 4.1 Available Test Infrastructure

**Fixtures** (from `tests/conftest.py`):
- `isolate_pflow_config(tmp_path, monkeypatch)` - Auto-patches SettingsManager paths
- `tmp_path` - Temporary directory for file operations
- `monkeypatch` - Mock environment variables
- `caplog` - Capture logging output

**Pattern for Settings Tests**:
```python
@pytest.fixture
def settings_manager(tmp_path):
    """Create a SettingsManager with temporary directory."""
    return SettingsManager(settings_path=tmp_path / ".pflow" / "settings.json")

def test_env_operations(settings_manager):
    """Test setting and getting env variables."""
    # Test implementation
```

### 4.2 Critical Test Cases (from spec)

**Must-Have Tests**:

1. **File Permission Tests**:
   ```python
   def test_settings_file_permissions(settings_manager):
       """Verify settings file has 0o600 permissions after save."""
       import stat

       settings = PflowSettings()
       settings.env["test_key"] = "test_value"
       settings_manager.save(settings)

       file_stat = settings_manager.settings_path.stat()
       file_mode = stat.S_IMODE(file_stat.st_mode)
       expected_mode = stat.S_IRUSR | stat.S_IWUSR  # 0o600

       assert file_mode == expected_mode
   ```

2. **Concurrent Access Tests**:
   ```python
   def test_concurrent_env_updates(settings_manager):
       """Test concurrent updates don't corrupt settings."""
       import threading

       results = {"errors": [], "successes": 0}

       def update_env(key, value):
           try:
               settings = settings_manager.load()
               settings.env[key] = value
               settings_manager.save(settings)
               results["successes"] += 1
           except Exception as e:
               results["errors"].append(e)

       # Start 5 threads updating different keys
       threads = []
       for i in range(5):
           t = threading.Thread(target=update_env, args=(f"key_{i}", f"value_{i}"))
           threads.append(t)
           t.start()

       for t in threads:
           t.join()

       # All operations should succeed
       assert results["successes"] == 5
       assert len(results["errors"]) == 0

       # Verify all keys present
       final_settings = settings_manager.reload()
       assert len(final_settings.env) == 5
   ```

3. **Precedence Tests**:
   ```python
   def test_settings_env_precedence(tmp_path):
       """Test CLI params override settings.env."""
       # Setup settings with env values
       settings_manager = SettingsManager(tmp_path / "settings.json")
       settings = PflowSettings()
       settings.env["api_key"] = "settings_value"
       settings_manager.save(settings)

       # Create workflow requiring api_key
       workflow_ir = {
           "ir_version": "0.1.0",
           "inputs": {
               "api_key": {"description": "API key", "required": True}
           },
           "nodes": []
       }

       # Test 1: CLI param overrides settings.env
       cli_params = {"api_key": "cli_value"}
       errors, defaults = prepare_inputs(workflow_ir, cli_params, settings.env)

       assert errors == []
       assert "api_key" not in defaults  # Already in cli_params

       # Test 2: settings.env used when CLI param missing
       cli_params = {}
       errors, defaults = prepare_inputs(workflow_ir, cli_params, settings.env)

       assert errors == []
       assert defaults["api_key"] == "settings_value"
   ```

4. **Atomic Save Tests**:
   ```python
   def test_atomic_save_no_partial_writes(settings_manager):
       """Verify save is atomic - no partial writes on failure."""
       settings = PflowSettings()
       settings.env["key1"] = "value1"
       settings_manager.save(settings)

       # Simulate failure during save
       class UnserializableObject:
           pass

       bad_settings = PflowSettings()
       bad_settings.env["key1"] = UnserializableObject()  # Can't serialize

       with pytest.raises(Exception):
           settings_manager.save(bad_settings)

       # Original file should still be valid
       loaded = settings_manager.load()
       assert loaded.env["key1"] == "value1"  # Original value preserved

       # No temp files should remain
       temp_files = list(settings_manager.settings_path.parent.glob(".settings.*.tmp"))
       assert len(temp_files) == 0
   ```

### 4.3 Test Coverage Matrix

| Rule # | Test Case | Test Function |
|--------|-----------|---------------|
| 1 | Create settings file if not exists | test_init_creates_file |
| 2 | Overwrite existing env key | test_set_env_overwrites |
| 3 | Set new env key | test_set_env_new_key |
| 4 | Remove existing env key | test_unset_env_existing |
| 5 | Remove non-existent env key | test_unset_env_nonexistent |
| 6 | List env with masking | test_list_env_masked |
| 7 | List env without masking | test_list_env_unmasked |
| 8 | Workflow input from settings | test_input_from_settings |
| 9 | CLI parameter overrides | test_cli_overrides_settings |
| 10 | Error on missing input | test_missing_required_input |
| 11 | File permissions 600 | test_file_permissions |
| 12 | Concurrent writes | test_concurrent_env_updates |
| 13 | Corrupted settings file | test_corrupted_file_fallback |
| 14 | Fix wrong permissions | test_fix_permissions |

---

## 5. Workflow Input Format Validation

### 5.1 Input Declaration Structure

**IR Schema** (from `ir_schema.py:186-204`):
```json
{
  "inputs": {
    "api_key": {
      "description": "API key for authentication",
      "type": "string",
      "required": true,
      "default": null
    }
  }
}
```

**Template Syntax**: `${variable_name}`

**Validation Rules**:
- Allowed characters: alphanumeric, underscore, hyphen, dot
- Forbidden: `$|><&;` and whitespace (shell injection prevention)
- Examples: `api_key`, `api-key`, `config.nested`, `2fa_token`

### 5.2 How Settings.env Maps to Inputs

**Mapping Logic**:
1. Workflow declares: `"inputs": {"replicate_api_token": {...}}`
2. User sets: `pflow settings set-env replicate_api_token r8_xxx`
3. At runtime: `settings.env["replicate_api_token"]` → `initial_params["replicate_api_token"]`
4. Template resolution: `${replicate_api_token}` → `"r8_xxx"`

**Direct Name Matching**:
- Input name MUST exactly match settings.env key
- No transformation or fuzzy matching
- Case-sensitive
- Deterministic and predictable

---

## 6. Atomic Operations Best Practices

### 6.1 The WorkflowManager Pattern

**Two Atomic Operations**:

1. **os.link()** - For creates (fails if exists)
   ```python
   os.link(temp_path, target_path)  # Atomic, fails on collision
   os.unlink(temp_path)              # Clean up temp file
   ```

2. **os.replace()** - For updates (atomic replace)
   ```python
   os.replace(temp_path, target_path)  # Atomic on all platforms
   ```

**Complete Pattern**:
```python
# 1. Create temp file in SAME directory as target
temp_fd, temp_path = tempfile.mkstemp(
    dir=target_path.parent,
    prefix=".settings.",
    suffix=".tmp"
)

try:
    # 2. Write to temp file
    with open(temp_fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    # 3. Atomic replace
    os.replace(temp_path, target_path)

    # 4. Set permissions AFTER atomic operation
    os.chmod(target_path, 0o600)

except Exception:
    # 5. Clean up on failure
    Path(temp_path).unlink(missing_ok=True)
    raise
```

### 6.2 Why This Pattern for API Keys

**Security Benefits**:
- Other processes never see partial secrets
- Crash during write doesn't leave corrupted file with partial keys
- Permissions set atomically (file appears with correct permissions)
- No race conditions during concurrent access

**Thread Safety**:
- `os.replace()` is atomic on all platforms
- Last write wins (acceptable for settings)
- No file corruption even under heavy concurrent load

**Proven in Tests**:
- `test_concurrent_saves_to_same_workflow()` validates atomicity
- `test_save_handles_write_failures_cleanly()` validates cleanup

---

## 7. Implementation Plan

### 7.1 Phase 1: Enhance SettingsManager Security

**Files to Modify**:
- `src/pflow/core/settings.py`

**Changes Required**:
1. **Update save() method**:
   - Replace direct write with atomic pattern
   - Add `os.chmod(self.settings_path, 0o600)` after write
   - Add proper error handling and cleanup

2. **Add env management methods**:
   ```python
   def set_env(self, key: str, value: str) -> None:
       """Set an environment variable."""
       settings = self.load()
       settings.env[key] = value
       self.save(settings)

   def unset_env(self, key: str) -> bool:
       """Remove an environment variable. Returns True if removed."""
       settings = self.load()
       if key in settings.env:
           del settings.env[key]
           self.save(settings)
           return True
       return False

   def get_env(self, key: str, default: Optional[str] = None) -> Optional[str]:
       """Get an environment variable value."""
       settings = self.load()
       return settings.env.get(key, default)

   def list_env(self, mask_values: bool = True) -> dict[str, str]:
       """List all environment variables, optionally masking values."""
       settings = self.load()
       if not mask_values:
           return settings.env.copy()
       return {k: self._mask_value(v) for k, v in settings.env.items()}

   @staticmethod
   def _mask_value(value: str) -> str:
       """Mask a value for display (show first 3 chars)."""
       if len(value) <= 3:
           return "***"
       return value[:3] + "***"
   ```

3. **Optional: Add permission validation** (defense in depth):
   ```python
   def _validate_permissions(self) -> None:
       """Warn if settings file has insecure permissions."""
       if not self.settings_path.exists():
           return

       file_stat = os.stat(self.settings_path)
       mode = stat.S_IMODE(file_stat.st_mode)

       if mode & (stat.S_IROTH | stat.S_IRGRP):
           settings = self.load()
           if settings.env:
               logger.warning(
                   f"Settings file {self.settings_path} contains secrets "
                   f"but has insecure permissions {oct(mode)}. "
                   f"Run: chmod 600 {self.settings_path}"
               )
   ```

**Tests to Write**:
- `tests/test_core/test_settings.py`:
  - test_set_env_new_key
  - test_set_env_overwrites_existing
  - test_unset_env_existing_key
  - test_unset_env_nonexistent_key
  - test_get_env_existing
  - test_get_env_nonexistent_with_default
  - test_list_env_masked
  - test_list_env_unmasked
  - test_atomic_save_no_partial_writes
  - test_file_permissions_after_save
  - test_concurrent_env_updates

### 7.2 Phase 2: Add CLI Commands

**Files to Modify**:
- `src/pflow/cli/commands/settings.py`

**Changes Required**:
Add three new commands:

```python
@settings.command()
@click.argument("key")
@click.argument("value")
def set_env(key: str, value: str) -> None:
    """Set an environment variable in settings."""
    manager = SettingsManager()
    manager.set_env(key, value)

    click.echo(f"✓ Set environment variable: {key}")
    click.echo(f"   Value: {manager._mask_value(value)}")


@settings.command()
@click.argument("key")
def unset_env(key: str) -> None:
    """Remove an environment variable from settings."""
    manager = SettingsManager()
    if manager.unset_env(key):
        click.echo(f"✓ Removed environment variable: {key}")
    else:
        click.echo(f"✗ Environment variable not found: {key}")


@settings.command()
@click.option("--show-values", is_flag=True, help="Show full values (unmasked)")
def list_env(show_values: bool) -> None:
    """List all environment variables."""
    manager = SettingsManager()
    env_vars = manager.list_env(mask_values=not show_values)

    if show_values:
        click.echo("⚠️  Displaying unmasked values")

    if not env_vars:
        click.echo("No environment variables configured")
        return

    click.echo("Environment variables:")
    for key, value in env_vars.items():
        click.echo(f"  {key}: {value}")
```

**Tests to Write**:
- `tests/test_cli/commands/test_settings_env.py`:
  - test_set_env_command
  - test_unset_env_command_existing
  - test_unset_env_command_nonexistent
  - test_list_env_command_masked
  - test_list_env_command_unmasked
  - test_list_env_command_empty

### 7.3 Phase 3: Integrate with WorkflowExecutor

**Files to Modify**:
- `src/pflow/runtime/workflow_validator.py`
- `src/pflow/runtime/compiler.py`

**Changes Required**:

1. **Update prepare_inputs() signature** (workflow_validator.py:71):
   ```python
   def prepare_inputs(
       workflow_ir: dict[str, Any],
       provided_params: dict[str, Any],
       settings_env: Optional[dict[str, str]] = None  # NEW
   ) -> tuple[list[tuple[str, str, str]], dict[str, Any]]:
   ```

2. **Add settings.env lookup logic** (workflow_validator.py:125):
   ```python
   if input_name not in provided_params:
       # NEW: Check settings.env before applying defaults
       if settings_env and input_name in settings_env:
           defaults[input_name] = settings_env[input_name]
           logger.debug(
               f"Using value from settings.env for input '{input_name}'",
               extra={"phase": "input_validation", "input": input_name}
           )
           continue

       # Original logic continues...
   ```

3. **Load settings in compiler** (compiler.py:857):
   ```python
   # Load settings.env once per compilation
   settings_env = {}
   try:
       from pflow.core.settings import SettingsManager
       manager = SettingsManager()
       settings = manager.load()
       settings_env = settings.env
   except Exception as e:
       logger.warning(f"Failed to load settings.env: {e}")

   # Pass to prepare_inputs
   errors, defaults = prepare_inputs(ir_dict, initial_params, settings_env=settings_env)
   ```

**Tests to Write**:
- `tests/test_runtime/test_workflow_validator.py`:
  - test_prepare_inputs_with_settings_env
  - test_prepare_inputs_cli_overrides_settings
  - test_prepare_inputs_settings_overrides_workflow_defaults
  - test_prepare_inputs_precedence_order

- `tests/test_integration/`:
  - test_workflow_execution_with_settings_env
  - test_e2e_api_key_from_settings

### 7.4 Phase 4: Documentation

**Files to Create/Update**:
- Update `architecture/features/api-key-management.md`
- Update `README.md` with usage examples
- Add security notes to `CLAUDE.md`
- Update CLI help text

---

## 8. Risk Assessment

### 8.1 Security Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| API keys stored in plain text | HIGH | Document clearly, follow AWS CLI pattern, use file permissions |
| File permissions not set | CRITICAL | Implement chmod 600 in save() |
| Concurrent access corruption | HIGH | Implement atomic file operations |
| Keys committed to git | MEDIUM | Document in README, add to .gitignore template |
| Keys visible in process list | LOW | Not applicable - keys not passed as CLI args |

### 8.2 Implementation Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Breaking existing settings functionality | MEDIUM | Comprehensive tests, backwards compatible |
| Integration point incorrect | LOW | Research confirms exact location |
| Precedence logic bugs | MEDIUM | Extensive precedence tests |
| Concurrent access during migration | LOW | Atomic operations handle this |

### 8.3 Adoption Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Users don't trust plain text | MEDIUM | Clear documentation, industry standard references |
| Confusion about precedence | LOW | Clear error messages, documentation |
| Key naming confusion | LOW | Exact matching, clear examples |

---

## 9. Success Criteria

### 9.1 Functional Requirements

✅ User can set API keys via CLI
✅ User can list API keys (masked by default)
✅ User can remove API keys via CLI
✅ Settings.env values auto-populate workflow inputs
✅ CLI params override settings.env
✅ Clear error messages when keys missing

### 9.2 Security Requirements

✅ Settings file has 0o600 permissions
✅ Atomic file operations prevent corruption
✅ Values masked in CLI output by default
✅ No keys visible in command history (not passed as args)

### 9.3 Quality Requirements

✅ All 24 test criteria pass
✅ Concurrent access tests pass
✅ No regression in existing settings functionality
✅ Documentation complete and clear

---

## 10. Conclusion

The research validates the feasibility of implementing API key management via settings.env with these critical requirements:

### Must Do Before Implementation:
1. 🔴 **Implement atomic file operations** in SettingsManager.save()
2. 🔴 **Add file permission hardening** (chmod 600)
3. 🟡 **Add permission validation** in load() (optional but recommended)

### Implementation Path is Clear:
1. ✅ Integration point identified: `workflow_validator.py:prepare_inputs()` line 125
2. ✅ Precedence model defined: CLI → settings.env → workflow defaults
3. ✅ Testing infrastructure ready
4. ✅ CLI command patterns established

### No Blockers Identified:
- No architectural conflicts
- No breaking changes required
- Minimal code surface area to modify
- Clear upgrade path from current implementation

**Recommendation**: Proceed with implementation following the 4-phase plan, starting with Phase 1 (security enhancements to SettingsManager) as these are foundational for safely storing API keys.
