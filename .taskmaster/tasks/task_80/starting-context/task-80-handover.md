# Task 80 Handoff: API Key Management via Settings

## 🎯 Core Context You Need to Know

The user wants to solve a real pain point: having to provide API keys every time they run a workflow. They showed me their `spotify-art-generator.json` workflow that requires `replicate_api_token` and `dropbox_token` as inputs, and they're tired of typing `--replicate_api_token $REPLICATE_API_TOKEN` every single time.

**The chosen solution**: Auto-populate workflow inputs from matching keys in `~/.pflow/settings.json`. If a workflow declares an input named `replicate_api_token` and the user hasn't provided it via CLI, check if `settings.env.replicate_api_token` exists and use that value.

## 🔍 Critical Discoveries from Investigation

### The `env` Field Already Exists!
Look at `/Users/andfal/projects/pflow/src/pflow/core/settings.py:34`:
```python
env: dict[str, str] = Field(default_factory=dict)
```
It's defined in `PflowSettings` but **completely unused**. No code reads from it, no code writes to it. It's just sitting there waiting to be implemented. This is perfect - we don't need to change the schema at all.

### The Real Workflow Pattern
The user's workflow at `.pflow/workflows/spotify-art-generator.json` shows the exact pattern:
- Lines 7-17: Declares `replicate_api_token` as a required input
- Lines 71, 100, 148, 177: Uses it as `${replicate_api_token}` in node params
- This is how ALL workflows handle API keys currently

### Where to Hook In
The integration point is in the workflow executor when it validates and populates inputs. Currently, it only checks CLI params against declared inputs. You need to add a middle layer that checks `settings.env` for any missing required inputs.

## ⚠️ Architectural Insights and Warnings

### The LLM Node Pattern
The LLM node (`src/pflow/nodes/llm/llm.py`) relies on Simon Willison's `llm` library which reads environment variables directly (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`). This works differently from our approach - we're NOT setting environment variables, we're populating workflow inputs. This is intentional to avoid side effects.

### Parameter Fallback Pattern in Nodes
Every node uses this pattern (line 96 in llm.py):
```python
prompt = shared.get("prompt") or self.params.get("prompt")
```
This means values in the shared store can also come from params. Our settings values will end up as workflow input params, which then get passed to nodes. This existing pattern means our approach will "just work" with all nodes.

### Hidden Bug in Shell Integration
While investigating, I found a bug in `src/pflow/core/shell_integration.py`. The `populate_shared_store()` function only accepts strings but the CLI passes `StdinData` objects for binary/large data. This causes data loss. It's unrelated to your task but be aware if you test with stdin data.

## 🚨 Design Decisions and Their Rationale

### Why Option 2 (Auto-populate) Won
We considered three approaches:
1. **Environment injection**: Set actual env vars from settings
2. **Auto-populate inputs**: Match input names to settings keys (CHOSEN)
3. **Explicit mapping**: Workflows declare which env var to read

Option 2 won because:
- Zero changes to existing workflows
- No side effects on the process environment
- Natural naming (input name = settings key)
- CLI args can still override

### Security Stance: Plain Text is Fine
We researched AWS CLI, Docker, and npm - they ALL use plain text config files with file permissions for security. This is standard practice for developer tools. We're following the same pattern:
- Store in plain text in `~/.pflow/settings.json`
- Set file permissions to 600 (owner read/write only)
- Document the security implications clearly

### CLI Override Precedence is Critical
The precedence MUST be:
1. CLI parameter (highest priority)
2. Settings.env value
3. Error if still missing (lowest)

This enables CI/CD systems to override local developer settings.

## 📁 Key Files and Code Locations

### Files You'll Modify:
- **`src/pflow/core/settings.py`**: Add methods for env management (set, get, list, unset)
- **`src/pflow/cli/commands/settings.py`**: Add new subcommands for env operations
- **`src/pflow/runtime/workflow_executor.py`**: Check settings when populating inputs (around the validation logic)
- **`tests/test_core/test_settings.py`**: Add tests for env operations

### Files to Study:
- **`.pflow/workflows/spotify-art-generator.json`**: Real workflow showing the input pattern (lines 7-17 for inputs, 71+ for usage)
- **`src/pflow/core/CLAUDE.md`**: Documents all the core module components and their issues
- **`/Users/andfal/projects/pflow/scratchpads/api-key-management/critical-user-decisions/api-key-implementation-approach.md`**: The full decision rationale

## 🎭 Patterns to Follow / Anti-patterns to Avoid

### Follow:
- **Atomic file operations**: Use `os.replace()` for updates, `os.link()` for creates (see WorkflowManager)
- **Clear error messages**: Use `UserFriendlyError` format (WHAT went wrong, WHY it failed, HOW to fix)
- **The parameter fallback pattern**: Every node already expects this

### Avoid:
- **Don't modify environment variables**: We're not doing env injection, only input population
- **Don't add encryption**: Plain text is intentional for MVP
- **Don't validate API key formats**: Just store and retrieve strings

## 🔮 Edge Cases I've Already Thought Through

1. **Settings file corrupted**: Log warning, use defaults
2. **Wrong file permissions**: Automatically fix to 600
3. **Concurrent access**: Last write wins (acceptable for settings)
4. **Empty string values**: Valid and should be preserved
5. **Unicode in values**: Preserve as-is
6. **Key with whitespace**: Trim it

## 💡 Implementation Strategy Suggestion

Start with the smallest working piece:
1. First, just add the env get/set methods to SettingsManager
2. Test those work with the existing save/load infrastructure
3. Then add the CLI commands
4. Finally, integrate with workflow executor

The workflow executor integration is the trickiest part. Look for where it validates required inputs and add your check there.

## 🧩 What Success Looks Like

The user should be able to:
```bash
# Set once
pflow settings set-env replicate_api_token r8_xxx

# Run without specifying
pflow spotify-art-generator --sheet_id abc123
# The token is automatically populated!
```

## 📋 Testing Considerations

The existing `tests/test_core/test_settings.py` has great patterns for testing the settings manager. Follow those patterns for your env tests. Pay special attention to:
- File permission tests (must be 600)
- Concurrent access tests (use threading like WorkflowManager tests)
- The precedence rules (CLI > settings > error)

## 🎬 Final Note

Remember: We chose the pragmatic approach. This isn't about building the perfect secure key management system. It's about making local development pleasant by following industry-standard patterns (AWS CLI model). Keep it simple, make it work, document the security implications.

**Important**: Before you start implementing, take a moment to read through all the files I've mentioned, especially the settings.py to understand the existing structure. Say "I'm ready to begin implementing Task 80" when you've absorbed this context.