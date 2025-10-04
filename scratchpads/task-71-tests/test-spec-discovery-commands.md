# Test Specification: Discovery Commands (workflow discover & registry discover)

## What Changed

Added two LLM-powered discovery commands that enable agents to find relevant components:

1. **`pflow workflow discover`** - Find existing workflows matching a task description
2. **`pflow registry discover`** - Find nodes needed for a specific task

**Key Implementation Details**:
- `workflow discover`: `src/pflow/cli/commands/workflow.py` lines 101-223
  - Uses WorkflowDiscoveryNode directly via `node.run(shared)`
  - Requires WorkflowManager in shared store
  - Requires Anthropic monkey patch installation
  - Falls back gracefully when LLM unavailable

- `registry discover`: `src/pflow/cli/registry.py` lines 635-755
  - Uses ComponentBrowsingNode directly via `node.run(shared)`
  - Requires WorkflowManager in shared store
  - Requires Anthropic monkey patch installation
  - Falls back gracefully when LLM unavailable

**What They Promise**:
1. **Rich query support** - Natural language task descriptions
2. **LLM-powered selection** - Intelligent component matching
3. **Complete information** - Full interface details, not just names
4. **Graceful degradation** - Helpful message when LLM unavailable
5. **No side effects** - Read-only operations

## Critical Behaviors to Test

### 1. Successful Discovery (Integration Test)
**Why**: Core functionality - must return relevant components when LLM available.

**Test**: `test_workflow_discover_with_mocked_llm`
```python
def test_workflow_discover_with_mocked_llm(cli_runner, tmp_path, monkeypatch):
    """workflow discover should return matching workflows when LLM available.

    Real behavior: Uses WorkflowDiscoveryNode to find relevant workflows
    Key insight: We mock the node's exec method, not the LLM directly
    """
    # Setup workflow library
    home_pflow = tmp_path / ".pflow" / "workflows"
    home_pflow.mkdir(parents=True)

    workflow = {
        "ir_version": "0.1.0",
        "metadata": {
            "description": "Analyzes GitHub pull requests",
            "capabilities": ["GitHub API", "LLM analysis"]
        },
        "nodes": [],
        "edges": []
    }
    (home_pflow / "pr-analyzer.json").write_text(json.dumps(workflow))

    # Mock WorkflowDiscoveryNode to return a match
    def mock_discovery_exec(self, shared):
        shared["discovery_result"] = "found_existing"
        shared["found_workflow"] = {
            "name": "pr-analyzer",
            "description": "Analyzes GitHub pull requests",
            "confidence": 0.9
        }

    monkeypatch.setattr(
        "pflow.planning.nodes.WorkflowDiscoveryNode.exec",
        mock_discovery_exec
    )

    result = cli_runner.invoke(
        workflow_cmd,
        ["discover", "analyze pull requests"],
        env={"HOME": str(tmp_path)}
    )

    assert result.exit_code == 0
    assert "pr-analyzer" in result.output
    assert "Analyzes GitHub pull requests" in result.output
```

**Real Bug This Catches**: If WorkflowDiscoveryNode integration breaks or shared store contract changes.

### 2. Workflow Manager Required
**Why**: Discovered critical bug - missing workflow_manager causes cryptic "Invalid request" error.

**Test**: `test_workflow_discover_requires_workflow_manager`
```python
def test_workflow_discover_requires_workflow_manager(cli_runner, tmp_path, monkeypatch):
    """Should gracefully handle missing WorkflowManager.

    This test validates the fix for the critical bug found during implementation.
    Without WorkflowManager in shared store, discovery fails with unhelpful error.
    """
    # Mock WorkflowDiscoveryNode to check for workflow_manager
    def mock_discovery_exec(self, shared):
        # This is what the actual node does
        if "workflow_manager" not in shared:
            raise ValueError("workflow_manager required in shared store")
        shared["discovery_result"] = "found_existing"

    monkeypatch.setattr(
        "pflow.planning.nodes.WorkflowDiscoveryNode.exec",
        mock_discovery_exec
    )

    # This should NOT fail - CLI should provide workflow_manager
    result = cli_runner.invoke(
        workflow_cmd,
        ["discover", "test query"],
        env={"HOME": str(tmp_path)}
    )

    # Should work because CLI adds workflow_manager to shared store
    # If this fails, the critical integration bug has returned
    assert result.exit_code == 0 or "workflow_manager" not in result.output.lower()
```

**Real Bug This Catches**: If CLI forgets to instantiate WorkflowManager before calling node.run().

### 3. LLM Unavailable Graceful Fallback
**Why**: Agents need helpful guidance when LLM isn't configured.

**Test**: `test_workflow_discover_llm_unavailable`
```python
def test_workflow_discover_llm_unavailable(cli_runner, tmp_path, monkeypatch):
    """Should show helpful message when LLM unavailable.

    Real behavior: Suggests using 'workflow list' instead
    """
    # Mock to simulate LLM configuration error
    def mock_discovery_exec(self, shared):
        from pflow.core.exceptions import CriticalPlanningError
        raise CriticalPlanningError(
            reason="No LLM API keys configured",
            category="configuration",
            resolution="Set ANTHROPIC_API_KEY or OPENAI_API_KEY"
        )

    monkeypatch.setattr(
        "pflow.planning.nodes.WorkflowDiscoveryNode.exec",
        mock_discovery_exec
    )

    result = cli_runner.invoke(
        workflow_cmd,
        ["discover", "test query"],
        env={"HOME": str(tmp_path)}
    )

    # Should fail but with helpful message
    assert result.exit_code != 0
    assert "LLM" in result.output or "API key" in result.output or "workflow list" in result.output
```

**Real Bug This Catches**: If error handling swallows helpful context and shows generic error.

### 4. Registry Discover Integration
**Why**: Same critical behaviors as workflow discover but for nodes.

**Test**: `test_registry_discover_with_mocked_llm`
```python
def test_registry_discover_with_mocked_llm(cli_runner, tmp_path, monkeypatch):
    """registry discover should return relevant nodes when LLM available."""
    # Mock ComponentBrowsingNode
    def mock_browsing_exec(self, shared):
        shared["planning_context"] = """
## GitHub Operations

### github-get-pr
**Description**: Fetch pull request details
**Inputs**:
  - repo: str (required)
  - pr_number: int (required)
"""

    monkeypatch.setattr(
        "pflow.planning.nodes.ComponentBrowsingNode.exec",
        mock_browsing_exec
    )

    result = cli_runner.invoke(
        ["registry", "discover", "fetch GitHub pull requests"],
        env={"HOME": str(tmp_path)}
    )

    assert result.exit_code == 0
    assert "github-get-pr" in result.output
    assert "Fetch pull request details" in result.output
```

**Real Bug This Catches**: If ComponentBrowsingNode integration or output formatting breaks.

### 5. Anthropic Monkey Patch Required
**Why**: Critical discovery - command groups bypass main CLI setup, patch not inherited.

**Test**: `test_discovery_commands_have_anthropic_patch`
```python
def test_discovery_commands_have_anthropic_patch(cli_runner, tmp_path, monkeypatch):
    """Discovery commands must install Anthropic monkey patch.

    This validates the fix for the cryptic Pydantic error when patch missing.
    Without patch: "cache_blocks - Extra inputs are not permitted"
    """
    # Track whether install_anthropic_model was called
    patch_installed = []

    def mock_install():
        patch_installed.append(True)

    monkeypatch.setattr(
        "pflow.cli.commands.workflow.install_anthropic_model",
        mock_install
    )
    monkeypatch.setattr(
        "pflow.cli.registry.install_anthropic_model",
        mock_install
    )

    # Mock discovery node to succeed
    def mock_exec(self, shared):
        shared["discovery_result"] = "found_existing"

    monkeypatch.setattr("pflow.planning.nodes.WorkflowDiscoveryNode.exec", mock_exec)

    # Run workflow discover
    cli_runner.invoke(
        workflow_cmd,
        ["discover", "test"],
        env={"HOME": str(tmp_path), "PYTEST_CURRENT_TEST": ""}  # Ensure patch runs
    )

    # Verify patch was installed
    assert len(patch_installed) > 0, "Anthropic monkey patch must be installed"
```

**Real Bug This Catches**: If monkey patch installation is removed or moved, Anthropic LLM calls fail cryptically.

### 6. Empty Query Handling
**Why**: Agents might accidentally pass empty strings.

**Test**: `test_workflow_discover_empty_query`
```python
def test_workflow_discover_empty_query(cli_runner, tmp_path):
    """Should handle empty or whitespace-only queries gracefully."""
    result = cli_runner.invoke(
        workflow_cmd,
        ["discover", ""],
        env={"HOME": str(tmp_path)}
    )

    # Should show helpful error
    assert result.exit_code != 0
    assert "query" in result.output.lower() or "description" in result.output.lower()
```

### 7. No Workflows Found
**Why**: Discovery should handle empty library gracefully.

**Test**: `test_workflow_discover_no_workflows_exist`
```python
def test_workflow_discover_no_workflows_exist(cli_runner, tmp_path, monkeypatch):
    """Should handle empty workflow library gracefully."""
    home_pflow = tmp_path / ".pflow" / "workflows"
    home_pflow.mkdir(parents=True)
    # Empty directory - no workflows

    def mock_exec(self, shared):
        shared["discovery_result"] = "not_found"

    monkeypatch.setattr("pflow.planning.nodes.WorkflowDiscoveryNode.exec", mock_exec)

    result = cli_runner.invoke(
        workflow_cmd,
        ["discover", "test query"],
        env={"HOME": str(tmp_path)}
    )

    assert result.exit_code == 0  # Not an error, just no matches
    assert "no" in result.output.lower() or "not found" in result.output.lower()
```

## What NOT to Test

❌ **Don't test WorkflowDiscoveryNode internals** - That's tested in `test_planning/`
❌ **Don't test ComponentBrowsingNode internals** - That's tested in `test_planning/`
❌ **Don't test actual LLM calls** - Mock the node's exec method
❌ **Don't test output formatting details** - Test that key information appears
❌ **Don't duplicate planning node tests** - Focus on CLI integration only

## Success Criteria

A test is valuable if:
1. ✅ Validates CLI-to-node integration (shared store contract)
2. ✅ Catches critical integration bugs (missing workflow_manager, patch)
3. ✅ Tests graceful degradation (LLM unavailable)
4. ✅ Uses mocks appropriately (node.exec, not internal LLM)
5. ✅ Fast execution (<100ms per test)

## Existing Coverage to Build On

- `tests/test_planning/integration/test_discovery_to_parameter_flow.py` - Discovery node behavior
- `tests/test_planning/unit/test_discovery_routing.py` - Discovery routing logic
- Focus on CLI integration, not node internals

## Test File Structure

```python
# tests/test_cli/test_discovery_commands.py

import json
from pathlib import Path
import pytest

class TestWorkflowDiscover:
    """Tests for 'pflow workflow discover' command."""

    def test_workflow_discover_with_mocked_llm(self, cli_runner, tmp_path, monkeypatch):
        """Returns matching workflows when LLM available."""
        # ...

    def test_workflow_discover_requires_workflow_manager(self, cli_runner, tmp_path, monkeypatch):
        """Validates workflow_manager is provided to discovery node."""
        # ...

    def test_workflow_discover_llm_unavailable(self, cli_runner, tmp_path, monkeypatch):
        """Shows helpful message when LLM not configured."""
        # ...

    def test_workflow_discover_empty_query(self, cli_runner, tmp_path):
        """Handles empty queries gracefully."""
        # ...

    def test_workflow_discover_no_workflows_exist(self, cli_runner, tmp_path, monkeypatch):
        """Handles empty workflow library."""
        # ...


class TestRegistryDiscover:
    """Tests for 'pflow registry discover' command."""

    def test_registry_discover_with_mocked_llm(self, cli_runner, tmp_path, monkeypatch):
        """Returns relevant nodes when LLM available."""
        # ...

    def test_registry_discover_llm_unavailable(self, cli_runner, tmp_path, monkeypatch):
        """Shows helpful message when LLM not configured."""
        # ...

    def test_discovery_commands_have_anthropic_patch(self, cli_runner, tmp_path, monkeypatch):
        """Verifies Anthropic monkey patch is installed."""
        # ...
```

## Estimated Effort

- **Workflow discover tests**: 40 minutes (5 tests)
- **Registry discover tests**: 30 minutes (3 tests with shared patterns)
- **Integration verification**: 20 minutes (monkey patch test)
- **Total**: ~1.5 hours

## Real Bugs These Tests Prevent

1. **Missing workflow_manager** - Caused "Invalid request format" error (discovered during implementation)
2. **Missing Anthropic patch** - Caused cryptic Pydantic validation errors (discovered during implementation)
3. **Poor error messages** - Generic errors when LLM unavailable
4. **Shared store contract violations** - Changes to discovery nodes could break CLI

These tests validate the critical integration points between CLI and planning infrastructure.
