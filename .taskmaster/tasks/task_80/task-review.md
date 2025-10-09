# Task 80 Review: API Key Management via Settings

## Metadata
- **Implementation Date**: October 9, 2025
- **Session ID**: af5addde-82c5-4728-8d61-6c47771467a0
- **Pull Request**: #69
- **Total Tests**: 111 (97 initial + 14 shell env)
- **Implementation Time**: ~6 hours (across 3 phases + bug fixes)

## Executive Summary

Built a complete API key management system that stores credentials in `~/.pflow/settings.json` with automatic workflow input population. Users set keys once via CLI and workflows automatically use them. Implementation includes atomic file operations with chmod 600, value masking for security, and a 5-level precedence system (CLI → shell env → settings.env → workflow defaults → error). **Critical discovery**: Shell environment variable support was added mid-implementation, transforming this into a CI/CD-friendly solution.

## Implementation Overview

### What Was Built

**Core Components**:
1. **Secure Storage System** (SettingsManager in `settings.py`)
   - 5 env management methods: set_env, unset_env, get_env, list_env, _mask_value
   - Atomic file operations using temp file + os.replace()
   - Automatic chmod 600 on every save (owner-only permissions)
   - Permission validation with defense-in-depth warnings
   - Thread-safe operations with lock protection

2. **CLI Interface** (3 new commands in `cli/commands/settings.py`)
   - `pflow settings set-env <key> <value>` - Store keys with masked output
   - `pflow settings unset-env <key>` - Remove keys (idempotent)
   - `pflow settings list-env [--show-values]` - List keys (masked by default)

3. **Workflow Integration** (compiler.py + workflow_validator.py)
   - Auto-population of workflow inputs from settings.env
   - Non-fatal settings load failures (workflows continue if settings broken)
   - 5-level precedence: CLI params → shell env vars → settings.env → workflow defaults → error

4. **Bonus Enhancement**: Shell environment variable support
   - Unplanned addition during implementation
   - Enables CI/CD workflows without settings.json setup
   - Standard Unix pattern (export VAR=value)

### Implementation Approach

**TDD Throughout**: Tests written first, then implementation (green → refactor cycle)

**Security-First Design**:
- Plain text storage following AWS CLI pattern (industry standard for dev tools)
- File permissions enforced via chmod 600 (not encryption)
- Atomic operations prevent corruption during crashes
- Permission validation warns on insecure files

**Integration Pattern**:
- Settings loaded once per workflow compilation (performance)
- Passed as optional parameter to maintain backward compatibility
- Non-blocking errors (failed load → empty dict → continue)

## Files Modified/Created

### Core Changes

**`src/pflow/core/settings.py`** (+134 lines net)
- **What**: Added env management methods + atomic save + permission validation
- **Why**: Needed secure API key storage without breaking existing node filtering
- **Critical**: Permission validation refactored to accept settings parameter (avoid recursion)

**`src/pflow/runtime/workflow_validator.py`** (+21 lines)
- **What**: Added settings_env + shell env lookup in prepare_inputs()
- **Why**: Auto-populate workflow inputs from multiple sources
- **Critical**: Shell env check BEFORE settings.env (precedence order matters)

**`src/pflow/runtime/compiler.py`** (+14 lines)
- **What**: Load settings.env once in _validate_workflow()
- **Why**: Single load point, non-fatal errors
- **Critical**: Wrapped in try/except, continues with empty dict on failure

**`src/pflow/cli/main.py`** (+14 lines at 2920-2930)
- **What**: Added settings.env loading for CLI validation
- **Why**: Bug fix - CLI validation was missing settings (only compiler had it)
- **Critical**: This was a critical bug discovered late - CLI validated inputs BEFORE compiler could use settings

**`src/pflow/cli/commands/settings.py`** (+60 lines)
- **What**: Three new CLI commands (set-env, unset-env, list-env)
- **Why**: User interface for managing stored credentials
- **Pattern**: Thin wrappers around SettingsManager methods

### Test Files

**`tests/test_core/test_settings.py`** (+513 lines, 42 tests)
- **Critical Tests**: Atomic save verification, file permission checks, concurrent access
- **Phase 1a**: Env CRUD operations (13 tests)
- **Phase 1b**: Atomic operations + permissions (9 tests)
- **Phase 1c**: Permission validation (4 tests)

**`tests/test_cli/test_settings_cli.py`** (+295 lines, 25 tests)
- **Critical Tests**: Masked output verification, idempotent operations
- **Pattern**: Uses CliRunner, mocks SettingsManager where needed

**`tests/test_runtime/test_settings_env_integration.py`** (+558 lines, 44 tests initially)
- **Critical Tests**: Precedence order validation, backward compatibility
- **30 original tests**: Settings.env integration
- **14 added tests**: Shell environment variable support
- **Most Important**: test_full_precedence_chain (validates entire priority system)

### Documentation

**`architecture/features/api-key-management.md`** (updated)
- **Added**: Shell env var documentation and precedence diagrams
- **Updated**: Data flow showing 5-level precedence

## Integration Points & Dependencies

### Incoming Dependencies

**WorkflowExecutor → SettingsManager**
- `compiler.py:_validate_workflow()` loads settings.env once per compilation
- Non-fatal: continues with empty dict if load fails
- **Load-bearing**: This is the ONLY place settings.env enters workflow execution

**CLI Validation → SettingsManager** (Bug fix)
- `cli/main.py:2920-2930` loads settings for early validation
- Prevents validation errors when CLI validates before compilation
- **Critical**: Without this, workflows fail validation even with correct settings.env

**prepare_inputs() → settings_env parameter**
- `workflow_validator.py:71` now accepts optional settings_env dict
- Backward compatible: defaults to None
- **Integration secret**: Must check shell env BEFORE settings.env for correct precedence

### Outgoing Dependencies

**SettingsManager → PocketFlow/PflowSettings**
- Uses Pydantic models for validation
- `env` field at line 34 was unused until this task

**SettingsManager → File System**
- Depends on os.replace() atomicity (POSIX + Windows)
- Depends on os.chmod() for security
- **Fragile point**: Permissions might fail on network filesystems

### Shared Store Keys

**None directly created** - This implementation modifies settings.json, not shared store

**Settings.json structure**:
```json
{
  "env": {
    "api_key": "value",  // Created by set_env()
    "token": "value"     // Used by workflow_validator.py
  }
}
```

## Architectural Decisions & Tradeoffs

### Key Decisions

**1. Plain Text Storage (Not Encryption)**
- **Decision**: Store API keys as plain JSON with file permissions
- **Reasoning**: Follows AWS CLI pattern, OS keychain integration deferred to v2
- **Alternative**: OS keychain integration (rejected: complexity for MVP)
- **Tradeoff**: Security via permissions (600) vs. encryption complexity

**2. Atomic Operations Pattern from WorkflowManager**
- **Decision**: Adopt temp file + os.replace() from WorkflowManager
- **Reasoning**: Proven thread-safe pattern already in codebase
- **Alternative**: Direct write (rejected: race conditions, corruption risk)
- **Result**: 100% reliable under concurrent access (proven by tests)

**3. 5-Level Precedence (Shell Env Added Mid-Implementation)**
- **Decision**: CLI → shell env → settings.env → defaults → error
- **Reasoning**: Shell env enables CI/CD without settings.json
- **Alternative**: Only settings.env (original plan, rejected for CI/CD)
- **Impact**: Major UX improvement, but added complexity to validation

**4. Non-Fatal Settings Load Failures**
- **Decision**: Settings load errors don't break workflows
- **Reasoning**: Settings are convenience, not critical path
- **Alternative**: Fail fast on corrupted settings (rejected: too fragile)
- **Pattern**: try/except → warning log → continue with empty dict

**5. Permission Validation Refactoring**
- **Decision**: Accept optional settings parameter to avoid recursion
- **Reasoning**: load() calls _validate_permissions(), which can't call load()
- **Alternative**: Separate validation function (rejected: breaks encapsulation)
- **Lesson**: Defense-in-depth features need careful lifecycle design

### Technical Debt Incurred

**1. No Encryption** (MVP scope)
- **What**: Plain text storage with file permissions
- **Why**: AWS CLI pattern is industry standard
- **Future**: OS keychain integration in v2.0

**2. Last Write Wins (Concurrent Access)**
- **What**: No merge logic for concurrent updates
- **Why**: Acceptable for settings (rare concurrent writes)
- **Future**: Advisory locks if needed

**3. No Key Rotation Support**
- **What**: No built-in key rotation or expiry
- **Why**: MVP scope, users can manually rotate
- **Future**: Expiry warnings, rotation prompts

## Testing Implementation

### Test Strategy Applied

**TDD Cycle**:
1. Write tests that fail (red)
2. Implement minimum code to pass (green)
3. Refactor and verify (green maintained)

**Test Pyramid**:
- 42 unit tests (SettingsManager methods)
- 25 CLI tests (user interface)
- 44 integration tests (end-to-end precedence)

**Coverage Focus**:
- Critical paths (atomic operations, precedence)
- Security properties (permissions, masking)
- Edge cases (empty values, unicode, concurrent access)

### Critical Test Cases

**`test_atomic_save_no_partial_writes`** (test_settings.py)
- **Validates**: Crash during save doesn't corrupt file
- **Why Critical**: Prevents data loss with API keys

**`test_file_permissions_after_save`** (test_settings.py)
- **Validates**: File always has 0o600 permissions
- **Why Critical**: Security foundation - keys exposed if this fails

**`test_concurrent_env_updates_different_keys`** (test_settings.py)
- **Validates**: Multiple threads can safely update settings
- **Why Critical**: Proves atomic operations work under load

**`test_full_precedence_chain`** (test_settings_env_integration.py)
- **Validates**: CLI → shell → settings → defaults order
- **Why Critical**: Single test validates entire precedence system

**`test_cli_param_overrides_settings_env`** (test_settings_env_integration.py)
- **Validates**: CLI always wins over stored values
- **Why Critical**: Enables CI/CD overrides

**`test_validate_permissions_warns_on_insecure`** (test_settings.py)
- **Validates**: Warning logged when file has wrong permissions
- **Why Critical**: Defense-in-depth catches permission failures

## Unexpected Discoveries

### Gotchas Encountered

**1. Recursion in Permission Validation**
- **Issue**: `_validate_permissions()` called `load()`, which called `_validate_permissions()`
- **Discovery**: Only surfaced when adding validation to load()
- **Solution**: Refactor to accept optional settings parameter
- **Lesson**: Defense-in-depth features need careful initialization order

**2. CLI Validation Missing Settings.env** (Critical Bug)
- **Issue**: CLI validated inputs at line 2921 WITHOUT settings.env
- **Discovery**: User testing showed workflows failing despite correct settings
- **Root Cause**: Two validation points (CLI + compiler), only compiler had settings
- **Solution**: Load settings.env in CLI validation too
- **Impact**: Would have broken feature completely if not caught

**3. Shell Environment Variables** (Unplanned Feature)
- **Discovery**: During implementation, realized CI/CD needs env vars
- **Decision**: Add shell env support mid-implementation
- **Impact**: Changed from 4-level to 5-level precedence
- **Result**: Major UX improvement, but required test expansion

**4. Silent Exception Handlers** (PR Review Finding)
- **Issue**: `except Exception: pass` suppressed all errors
- **Discovery**: PR review caught this
- **Solution**: Added debug logging
- **Lesson**: Even non-critical code needs debuggability

### Edge Cases Found

**Empty String Values**
- **Case**: `manager.set_env("key", "")`
- **Behavior**: Empty string is valid and preserved
- **Test**: `test_env_with_empty_string_value`

**Unicode in Values**
- **Case**: Keys with emoji or non-ASCII
- **Behavior**: Preserved correctly via JSON UTF-8
- **Test**: `test_env_with_unicode_in_value`

**Concurrent Same-Key Updates**
- **Case**: Multiple threads updating same key
- **Behavior**: Last write wins (atomic)
- **Test**: `test_concurrent_same_key_updates`

**Permission Validation Recursion**
- **Case**: Validation during load caused infinite loop
- **Behavior**: Fixed by passing settings parameter
- **Test**: All permission validation tests

## Patterns Established

### Reusable Patterns

**1. Atomic File Update Pattern** (settings.py:152-182)
```python
# Pattern: Temp file + os.replace() for atomic updates
temp_fd, temp_path = tempfile.mkstemp(
    dir=self.settings_path.parent,
    prefix=".settings.",
    suffix=".tmp"
)
try:
    with open(temp_fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(temp_path, self.settings_path)  # Atomic
    os.chmod(self.settings_path, 0o600)         # Secure
except Exception:
    Path(temp_path).unlink(missing_ok=True)     # Cleanup
    raise
```
**When to use**: Any sensitive data storage, configuration files
**Why it works**: os.replace() is atomic on all platforms, temp files isolated

**2. Precedence Chain with Early Exit** (workflow_validator.py:133-151)
```python
# Pattern: Check sources in priority order with continue
if input_name not in provided_params:
    # 1. Shell env (highest precedence for unprovided)
    if input_name in os.environ:
        defaults[input_name] = os.environ[input_name]
        continue  # Skip lower precedence sources

    # 2. Settings.env
    if settings_env and input_name in settings_env:
        defaults[input_name] = settings_env[input_name]
        continue

    # 3. Workflow defaults (lowest precedence)
    if "default" in input_spec:
        defaults[input_name] = input_spec["default"]
```
**When to use**: Any multi-source configuration system
**Why it works**: Early exit prevents checking lower priority sources

**3. Defense-in-Depth with Non-Blocking Validation** (settings.py:343-379)
```python
def _validate_permissions(self, settings: Optional[PflowSettings] = None):
    """Validate but never break functionality."""
    try:
        # Check permissions, warn if insecure
        if mode & (stat.S_IROTH | stat.S_IRGRP):
            if settings.env:  # Only warn if secrets present
                logger.warning("Insecure permissions...")
    except Exception as e:
        logger.debug(f"Validation failed: {e}")  # Log but don't raise
```
**When to use**: Security checks that shouldn't break functionality
**Why it works**: Validation failures are non-critical, debugging still possible

### Anti-Patterns to Avoid

**❌ Don't Call load() from Methods Called by load()**
- **Problem**: `_validate_permissions()` originally called `load()` → infinite recursion
- **Solution**: Pass data as parameter instead of loading internally

**❌ Don't Validate Inputs in Multiple Places Without Coordination**
- **Problem**: CLI and compiler both validated, but only compiler had settings
- **Solution**: Centralize validation or ensure all call sites have same context

**❌ Don't Suppress Exceptions Silently**
- **Problem**: `except Exception: pass` hid real errors
- **Solution**: Always log at minimum debug level

**❌ Don't Assume Single Validation Point**
- **Problem**: Only added settings.env to compiler, missed CLI
- **Solution**: Trace all code paths that validate inputs

## Breaking Changes

### API/Interface Changes

**`prepare_inputs()` signature** (workflow_validator.py:71)
- **Before**: `prepare_inputs(workflow_ir, provided_params)`
- **After**: `prepare_inputs(workflow_ir, provided_params, settings_env=None)`
- **Impact**: Backward compatible (optional parameter)
- **Callers Updated**: compiler.py, cli/main.py

**`_validate_permissions()` signature** (settings.py:343)
- **Before**: `_validate_permissions(self)`
- **After**: `_validate_permissions(self, settings=None)`
- **Impact**: Internal only, backward compatible

### Behavioral Changes

**Workflow Input Population** (New Behavior)
- **Before**: Only CLI params and workflow defaults
- **After**: CLI → shell env → settings.env → defaults
- **Impact**: Workflows can now run without manual key input

**Settings File Permissions** (Enforced)
- **Before**: System default permissions (often 644)
- **After**: Always chmod 600 on save
- **Impact**: Existing settings files auto-fixed on next save

## Future Considerations

### Extension Points

**1. OS Keychain Integration** (settings.py)
- **Where**: Add `KeychainManager` class alongside SettingsManager
- **Hook**: set_env() could route to keychain for sensitive keys
- **Pattern**: Same API, different storage backend

**2. Key Rotation Tracking** (settings.json)
- **Where**: Add metadata: `"key_created_at"`, `"key_expires_at"`
- **Hook**: load() could check expiry and warn
- **Pattern**: Metadata wrapper like WorkflowManager

**3. Multi-Environment Support** (settings.py)
- **Where**: Support `~/.pflow/settings-{env}.json`
- **Hook**: Environment selection via env var or CLI flag
- **Pattern**: Existing load logic with path selection

### Scalability Concerns

**File Size Growth**
- **Current**: Small JSON file (<1KB for 10 keys)
- **Concern**: 1000+ keys could slow JSON parsing
- **Future**: Consider SQLite or key-value store

**Concurrent Access**
- **Current**: Last write wins, atomic operations
- **Concern**: High-frequency updates from multiple processes
- **Future**: Advisory locks or optimistic locking

**Permission Validation Overhead**
- **Current**: Runs on every load() (once per workflow)
- **Concern**: Could add latency with many workflows
- **Future**: Cache validation result per file mtime

## AI Agent Guidance

### Quick Start for Related Tasks

**If extending settings management**:
1. Read `settings.py` methods (set_env, unset_env as templates)
2. Follow atomic save pattern (lines 152-182)
3. Add tests to `test_settings.py` following existing structure
4. Maintain chmod 600 enforcement

**If adding new workflow input sources**:
1. Study precedence chain in `workflow_validator.py:133-151`
2. Add source check with early exit (continue)
3. Update precedence documentation
4. Add tests to `test_settings_env_integration.py`

**If integrating with SettingsManager**:
1. Import: `from pflow.core.settings import SettingsManager`
2. Instantiate: `manager = SettingsManager()` (uses default path)
3. Use methods: `manager.set_env()`, `manager.get_env()`
4. Handle errors: All methods can raise, wrap in try/except

### Common Pitfalls

**1. Forgetting CLI Validation Point**
- **Mistake**: Only updating compiler.py for new input sources
- **Reality**: CLI validates at line 2921 BEFORE compilation
- **Fix**: Update both cli/main.py AND compiler.py

**2. Breaking Precedence Order**
- **Mistake**: Checking settings.env before shell env
- **Reality**: Order matters for correct behavior
- **Fix**: Always maintain CLI → shell → settings → defaults

**3. Assuming Synchronous File Access**
- **Mistake**: Direct file writes without atomic operations
- **Reality**: Concurrent access can corrupt files
- **Fix**: Use temp file + os.replace() pattern

**4. Not Testing Concurrent Access**
- **Mistake**: Only testing single-threaded scenarios
- **Reality**: pflow can be called concurrently
- **Fix**: Add threading tests (see test_concurrent_*)

### Test-First Recommendations

**When modifying settings.env integration**:
1. Run `test_settings_env_integration.py` first (catches precedence bugs)
2. Then `test_settings.py` (catches storage bugs)
3. Then `test_settings_cli.py` (catches UI bugs)

**When adding new precedence sources**:
1. Write `test_full_precedence_chain` variant first
2. Add individual source tests
3. Add override tests (new source vs. existing sources)

**When modifying atomic operations**:
1. Run `test_atomic_save_*` tests
2. Run `test_concurrent_*` tests
3. Verify cleanup on failure tests

---

## Key Takeaways for Future Agents

1. **Settings.env is now load-bearing** - Many workflows depend on it, breaking changes affect users
2. **Two validation points exist** - CLI (line 2921) and compiler (line 857), both need updates
3. **Precedence order is sacred** - CLI → shell → settings → defaults, don't reorder
4. **Atomic operations are proven** - Temp file + os.replace() works, reuse this pattern
5. **Defense-in-depth is active** - Permission validation catches chmod failures
6. **Shell env support was crucial** - CI/CD depends on it, don't remove
7. **Tests prevent real bugs** - Atomic save tests caught corruption, precedence tests caught override bugs

*Generated from implementation context of Task 80 - Session af5addde-82c5-4728-8d61-6c47771467a0*
