"""Tests for WorkflowExecutorService, especially parameter sanitization."""

import pytest
import yaml

from pflow.core.workflow_manager import WorkflowManager
from pflow.execution.executor_service import WorkflowExecutorService
from tests.shared.markdown_utils import ir_to_markdown


def _read_frontmatter(workflow_file):
    """Read and parse YAML frontmatter from a .pflow.md file."""
    content = workflow_file.read_text()
    parts = content.split("---", 2)
    assert len(parts) >= 3, f"Expected frontmatter in {workflow_file}"
    return yaml.safe_load(parts[1])


@pytest.fixture
def temp_workflow_dir(tmp_path):
    """Create temporary workflow directory."""
    workflow_dir = tmp_path / "workflows"
    workflow_dir.mkdir()
    return workflow_dir


@pytest.fixture
def workflow_manager(temp_workflow_dir):
    """Create WorkflowManager with temporary directory."""
    return WorkflowManager(workflows_dir=temp_workflow_dir)


@pytest.fixture
def executor_service(workflow_manager):
    """Create WorkflowExecutorService."""
    return WorkflowExecutorService(
        workflow_manager=workflow_manager,
    )


# Shared IR dict for tests — a minimal valid workflow
_TEST_WORKFLOW_IR = {
    "inputs": {},
    "nodes": [{"id": "test", "type": "shell", "params": {"command": "echo hi"}}],
    "edges": [],
    "outputs": {},
}


def _save_test_workflow(workflow_manager, name):
    """Save a test workflow using the new markdown API."""
    markdown_content = ir_to_markdown(_TEST_WORKFLOW_IR)
    workflow_manager.save(name, markdown_content)


class TestParameterSanitization:
    """Tests for parameter sanitization in metadata storage."""

    def test_sensitive_params_sanitized_in_metadata(self, executor_service, workflow_manager, temp_workflow_dir):
        """Verify API keys/tokens are sanitized in last_execution_params."""
        workflow_name = "test-workflow"
        _save_test_workflow(workflow_manager, workflow_name)

        # Execution params with sensitive values
        execution_params = {
            "api_key": "secret-key-12345",
            "replicate_api_token": "r8_bpXbpAbR1wAjL1VqN96qbws5zhtcnDc1FoUAq",
            "password": "my-password",
            "auth_token": "bearer-token-abc",
            "normal_param": "visible-value",
            "channel": "C09C16NAU5B",
        }

        # Update metadata via executor service
        executor_service._update_workflow_metadata(
            success=True,
            workflow_name=workflow_name,
            execution_params=execution_params,
        )

        # Load workflow frontmatter and verify sanitization
        workflow_file = temp_workflow_dir / f"{workflow_name}.pflow.md"
        frontmatter = _read_frontmatter(workflow_file)

        last_params = frontmatter["last_execution_params"]

        # Verify sensitive params are redacted
        assert last_params["api_key"] == "<REDACTED>"
        assert last_params["replicate_api_token"] == "<REDACTED>"  # noqa: S105
        assert last_params["password"] == "<REDACTED>"  # noqa: S105
        assert last_params["auth_token"] == "<REDACTED>"  # noqa: S105

        # Verify non-sensitive params are preserved
        assert last_params["normal_param"] == "visible-value"
        assert last_params["channel"] == "C09C16NAU5B"

    def test_nested_sensitive_params_sanitized(self, executor_service, workflow_manager, temp_workflow_dir):
        """Verify nested sensitive params are sanitized."""
        workflow_name = "nested-test"
        _save_test_workflow(workflow_manager, workflow_name)

        # Nested structure with sensitive values
        execution_params = {
            "config": {
                "api_key": "secret-key",
                "timeout": 30,
                "nested_config": {
                    "token": "bearer-token",
                    "username": "user",
                },
            },
            "items": [
                {"name": "item1", "secret_key": "secret1"},
                {"name": "item2", "password": "secret2"},
            ],
        }

        # Update metadata
        executor_service._update_workflow_metadata(
            success=True,
            workflow_name=workflow_name,
            execution_params=execution_params,
        )

        # Load and verify
        workflow_file = temp_workflow_dir / f"{workflow_name}.pflow.md"
        frontmatter = _read_frontmatter(workflow_file)

        last_params = frontmatter["last_execution_params"]

        # Check nested sanitization
        assert last_params["config"]["api_key"] == "<REDACTED>"
        assert last_params["config"]["timeout"] == 30
        assert last_params["config"]["nested_config"]["token"] == "<REDACTED>"  # noqa: S105
        assert last_params["config"]["nested_config"]["username"] == "user"
        assert last_params["items"][0]["secret_key"] == "<REDACTED>"  # noqa: S105
        assert last_params["items"][0]["name"] == "item1"
        assert last_params["items"][1]["password"] == "<REDACTED>"  # noqa: S105

    def test_no_params_works(self, executor_service, workflow_manager, temp_workflow_dir):
        """Verify empty params don't cause errors."""
        workflow_name = "empty-params"
        _save_test_workflow(workflow_manager, workflow_name)

        # Update with empty params
        executor_service._update_workflow_metadata(
            success=True,
            workflow_name=workflow_name,
            execution_params={},
        )

        # Load and verify
        workflow_file = temp_workflow_dir / f"{workflow_name}.pflow.md"
        frontmatter = _read_frontmatter(workflow_file)

        assert frontmatter["last_execution_params"] == {}

    def test_all_sensitive_params_patterns(self, executor_service, workflow_manager, temp_workflow_dir):
        """Verify all 19 sensitive parameter patterns are sanitized."""
        workflow_name = "all-patterns"
        _save_test_workflow(workflow_manager, workflow_name)

        # All sensitive patterns from SENSITIVE_KEYS
        execution_params = {
            "password": "secret1",
            "passwd": "secret2",
            "pwd": "secret3",
            "token": "secret4",
            "api_token": "secret5",
            "access_token": "secret6",
            "auth_token": "secret7",
            "api_key": "secret8",
            "apikey": "secret9",
            "api-key": "secret10",
            "secret": "secret11",
            "client_secret": "secret12",
            "private_key": "secret13",
            "ssh_key": "secret14",
            "secret_key": "secret15",
            "credential": "secret16",
            "credentials": "secret17",
            "authorization": "secret18",
            "auth": "secret19",
            "safe_param": "visible",
        }

        # Update metadata
        executor_service._update_workflow_metadata(
            success=True,
            workflow_name=workflow_name,
            execution_params=execution_params,
        )

        # Load and verify
        workflow_file = temp_workflow_dir / f"{workflow_name}.pflow.md"
        frontmatter = _read_frontmatter(workflow_file)

        last_params = frontmatter["last_execution_params"]

        # All sensitive params should be redacted
        for key in execution_params:
            if key != "safe_param":
                assert last_params[key] == "<REDACTED>"

        # Non-sensitive param should be visible
        assert last_params["safe_param"] == "visible"

    def test_case_insensitive_detection(self, executor_service, workflow_manager, temp_workflow_dir):
        """Verify sensitive param detection is case-insensitive."""
        workflow_name = "case-test"
        _save_test_workflow(workflow_manager, workflow_name)

        # Various cases
        execution_params = {
            "API_KEY": "secret1",
            "Api_Key": "secret2",
            "api_key": "secret3",
            "PASSWORD": "secret4",
            "Password": "secret5",
            "MyApiToken": "secret6",
            "user_password_hash": "secret7",
            "NORMAL_PARAM": "visible",
        }

        # Update metadata
        executor_service._update_workflow_metadata(
            success=True,
            workflow_name=workflow_name,
            execution_params=execution_params,
        )

        # Load and verify
        workflow_file = temp_workflow_dir / f"{workflow_name}.pflow.md"
        frontmatter = _read_frontmatter(workflow_file)

        last_params = frontmatter["last_execution_params"]

        # All variations should be redacted
        assert last_params["API_KEY"] == "<REDACTED>"
        assert last_params["Api_Key"] == "<REDACTED>"
        assert last_params["api_key"] == "<REDACTED>"
        assert last_params["PASSWORD"] == "<REDACTED>"  # noqa: S105
        assert last_params["Password"] == "<REDACTED>"  # noqa: S105
        assert last_params["MyApiToken"] == "<REDACTED>"
        assert last_params["user_password_hash"] == "<REDACTED>"  # noqa: S105

        # Non-sensitive param should be visible
        assert last_params["NORMAL_PARAM"] == "visible"

    def test_metadata_not_updated_on_failure(self, executor_service, workflow_manager, temp_workflow_dir):
        """Verify metadata is not updated when success=False."""
        workflow_name = "failure-test"
        _save_test_workflow(workflow_manager, workflow_name)

        # Get initial frontmatter — freshly saved file has no execution fields
        workflow_file = temp_workflow_dir / f"{workflow_name}.pflow.md"
        initial_frontmatter = _read_frontmatter(workflow_file)

        # Verify no execution fields exist yet
        assert "last_execution_params" not in initial_frontmatter
        assert "last_execution_success" not in initial_frontmatter

        # Try to update with failure
        executor_service._update_workflow_metadata(
            success=False,  # Failure - should not update
            workflow_name=workflow_name,
            execution_params={"param": "value"},
        )

        # Verify execution metadata was NOT added
        after_frontmatter = _read_frontmatter(workflow_file)
        assert "last_execution_params" not in after_frontmatter
        assert "last_execution_success" not in after_frontmatter

    def test_execution_count_increments(self, executor_service, workflow_manager, temp_workflow_dir):
        """Verify execution_count increments with each successful run."""
        workflow_name = "count-test"
        _save_test_workflow(workflow_manager, workflow_name)

        workflow_file = temp_workflow_dir / f"{workflow_name}.pflow.md"

        # First execution
        executor_service._update_workflow_metadata(
            success=True,
            workflow_name=workflow_name,
            execution_params={"run": "1"},
        )

        frontmatter1 = _read_frontmatter(workflow_file)
        assert frontmatter1["execution_count"] == 1

        # Second execution
        executor_service._update_workflow_metadata(
            success=True,
            workflow_name=workflow_name,
            execution_params={"run": "2"},
        )

        frontmatter2 = _read_frontmatter(workflow_file)
        assert frontmatter2["execution_count"] == 2

        # Third execution
        executor_service._update_workflow_metadata(
            success=True,
            workflow_name=workflow_name,
            execution_params={"run": "3"},
        )

        frontmatter3 = _read_frontmatter(workflow_file)
        assert frontmatter3["execution_count"] == 3


class TestEnvParameterSanitization:
    """Tests for environment parameter sanitization."""

    def test_env_params_always_redacted_regardless_of_name(self, executor_service, workflow_manager, temp_workflow_dir):
        """Verify params from env are always redacted, even with safe names."""
        workflow_name = "env-test"
        _save_test_workflow(workflow_manager, workflow_name)

        # Simulate execution with params from env
        execution_params = {
            "safe_name": "value1",  # Would normally NOT be redacted
            "another_param": "value2",  # Would normally NOT be redacted
            "channel": "C09",  # Would normally NOT be redacted
            "__env_param_names__": ["safe_name", "another_param", "channel"],  # Mark as from env
        }

        executor_service._update_workflow_metadata(
            success=True,
            workflow_name=workflow_name,
            execution_params=execution_params,
        )

        # Load and verify ALL env params are redacted
        workflow_file = temp_workflow_dir / f"{workflow_name}.pflow.md"
        frontmatter = _read_frontmatter(workflow_file)

        last_params = frontmatter["last_execution_params"]
        assert last_params["safe_name"] == "<REDACTED>"  # Redacted despite safe name!
        assert last_params["another_param"] == "<REDACTED>"  # Redacted despite safe name!
        assert last_params["channel"] == "<REDACTED>"  # Redacted despite safe name!
        assert "__env_param_names__" not in last_params  # Internal param filtered out

    def test_non_env_params_with_safe_names_preserved(self, executor_service, workflow_manager, temp_workflow_dir):
        """Verify non-env params with safe names are NOT redacted."""
        workflow_name = "non-env-test"
        _save_test_workflow(workflow_manager, workflow_name)

        execution_params = {
            "region": "us-west-2",  # Safe name, not from env
            "limit": 100,  # Safe name, not from env
            "channel": "C09",  # Safe name, not from env
            # No __env_param_names__ key - nothing from env
        }

        executor_service._update_workflow_metadata(
            success=True,
            workflow_name=workflow_name,
            execution_params=execution_params,
        )

        workflow_file = temp_workflow_dir / f"{workflow_name}.pflow.md"
        frontmatter = _read_frontmatter(workflow_file)

        last_params = frontmatter["last_execution_params"]
        assert last_params["region"] == "us-west-2"  # NOT redacted
        assert last_params["limit"] == 100  # NOT redacted
        assert last_params["channel"] == "C09"  # NOT redacted

    def test_pattern_based_sanitization_still_works(self, executor_service, workflow_manager, temp_workflow_dir):
        """Verify pattern matching still catches sensitive names."""
        workflow_name = "pattern-test"
        _save_test_workflow(workflow_manager, workflow_name)

        execution_params = {
            "api_key": "secret123",  # Caught by pattern
            "safe_param": "value",  # Not caught, not from env
            "__env_param_names__": [],  # Empty - nothing from env
        }

        executor_service._update_workflow_metadata(
            success=True,
            workflow_name=workflow_name,
            execution_params=execution_params,
        )

        workflow_file = temp_workflow_dir / f"{workflow_name}.pflow.md"
        frontmatter = _read_frontmatter(workflow_file)

        last_params = frontmatter["last_execution_params"]
        assert last_params["api_key"] == "<REDACTED>"  # Pattern match
        assert last_params["safe_param"] == "value"  # Preserved

    def test_env_and_pattern_both_redact(self, executor_service, workflow_manager, temp_workflow_dir):
        """Verify both env source AND pattern matching cause redaction."""
        workflow_name = "both-test"
        _save_test_workflow(workflow_manager, workflow_name)

        execution_params = {
            "api_key": "secret123",  # Caught by BOTH pattern AND env
            "safe_from_env": "value",  # Caught by env source only
            "token": "bearer123",  # Caught by pattern only (not in env list)
            "normal_param": "visible",  # Not caught by either
            "__env_param_names__": ["api_key", "safe_from_env"],  # From env
        }

        executor_service._update_workflow_metadata(
            success=True,
            workflow_name=workflow_name,
            execution_params=execution_params,
        )

        workflow_file = temp_workflow_dir / f"{workflow_name}.pflow.md"
        frontmatter = _read_frontmatter(workflow_file)

        last_params = frontmatter["last_execution_params"]
        assert last_params["api_key"] == "<REDACTED>"  # Caught by both
        assert last_params["safe_from_env"] == "<REDACTED>"  # Caught by env
        assert last_params["token"] == "<REDACTED>"  # noqa: S105  # Caught by pattern
        assert last_params["normal_param"] == "visible"  # Not caught

    def test_empty_env_param_names_works(self, executor_service, workflow_manager, temp_workflow_dir):
        """Verify empty env_param_names doesn't cause errors."""
        workflow_name = "empty-env-test"
        _save_test_workflow(workflow_manager, workflow_name)

        execution_params = {
            "param": "value",
            "__env_param_names__": [],  # Explicitly empty
        }

        executor_service._update_workflow_metadata(
            success=True,
            workflow_name=workflow_name,
            execution_params=execution_params,
        )

        workflow_file = temp_workflow_dir / f"{workflow_name}.pflow.md"
        frontmatter = _read_frontmatter(workflow_file)

        last_params = frontmatter["last_execution_params"]
        assert last_params["param"] == "value"  # Preserved
