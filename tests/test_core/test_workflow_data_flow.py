"""Test the data flow validation module."""

import pytest

from pflow.core.workflow_data_flow import CycleError, build_execution_order, validate_data_flow


class TestBuildExecutionOrder:
    """Test the topological sort for execution order."""

    def test_linear_workflow(self):
        """Test simple linear workflow."""
        workflow = {
            "nodes": [
                {"id": "a", "type": "test"},
                {"id": "b", "type": "test"},
                {"id": "c", "type": "test"},
            ],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "b", "to": "c"},
            ],
        }
        order = build_execution_order(workflow)
        assert order == ["a", "b", "c"]

    def test_parallel_branches(self):
        """Test workflow with parallel branches."""
        workflow = {
            "nodes": [
                {"id": "start", "type": "test"},
                {"id": "branch1", "type": "test"},
                {"id": "branch2", "type": "test"},
                {"id": "end", "type": "test"},
            ],
            "edges": [
                {"from": "start", "to": "branch1"},
                {"from": "start", "to": "branch2"},
                {"from": "branch1", "to": "end"},
                {"from": "branch2", "to": "end"},
            ],
        }
        order = build_execution_order(workflow)
        # Start must be first, end must be last
        assert order[0] == "start"
        assert order[-1] == "end"
        # Branches can be in any order
        assert set(order[1:3]) == {"branch1", "branch2"}

    def test_disconnected_nodes(self):
        """Test workflow with disconnected nodes."""
        workflow = {
            "nodes": [
                {"id": "a", "type": "test"},
                {"id": "b", "type": "test"},
                {"id": "orphan", "type": "test"},
            ],
            "edges": [
                {"from": "a", "to": "b"},
            ],
        }
        order = build_execution_order(workflow)
        # All nodes should be included
        assert set(order) == {"a", "b", "orphan"}
        # Connected nodes maintain order
        assert order.index("a") < order.index("b")

    def test_circular_dependency(self):
        """Test detection of circular dependencies."""
        workflow = {
            "nodes": [
                {"id": "a", "type": "test"},
                {"id": "b", "type": "test"},
                {"id": "c", "type": "test"},
            ],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "b", "to": "c"},
                {"from": "c", "to": "a"},  # Creates cycle
            ],
        }
        with pytest.raises(CycleError) as exc_info:
            build_execution_order(workflow)
        assert "Circular dependency" in str(exc_info.value)
        assert "a" in str(exc_info.value)
        assert "b" in str(exc_info.value)
        assert "c" in str(exc_info.value)

    def test_self_loop(self):
        """Test detection of self-referencing node."""
        workflow = {
            "nodes": [
                {"id": "a", "type": "test"},
            ],
            "edges": [
                {"from": "a", "to": "a"},  # Self loop
            ],
        }
        with pytest.raises(CycleError) as exc_info:
            build_execution_order(workflow)
        assert "Circular dependency" in str(exc_info.value)


class TestValidateDataFlow:
    """Test data flow validation logic."""

    def test_valid_linear_flow(self):
        """Test that valid linear workflow passes."""
        workflow = {
            "nodes": [
                {"id": "read", "type": "read-file", "params": {"file": "${input_file}"}},
                {"id": "process", "type": "llm", "params": {"prompt": "Process: ${read.content}"}},
                {"id": "write", "type": "write-file", "params": {"content": "${process.response}"}},
            ],
            "edges": [
                {"from": "read", "to": "process"},
                {"from": "process", "to": "write"},
            ],
            "inputs": {"input_file": {"type": "string"}},
        }
        errors = validate_data_flow(workflow)
        assert errors == []

    def test_forward_reference_detection(self):
        """Test detection of forward references."""
        workflow = {
            "nodes": [
                {"id": "node2", "type": "llm", "params": {"data": "${node1.output}"}},
                {"id": "node1", "type": "read-file", "params": {"file": "test.txt"}},
            ],
            "edges": [
                {"from": "node2", "to": "node1"},  # Wrong order!
            ],
            "inputs": {},
        }
        errors = validate_data_flow(workflow)
        assert len(errors) > 0
        assert "node2" in errors[0]
        assert "node1" in errors[0]
        assert "after" in errors[0]

    def test_non_existent_node_reference(self):
        """Test detection of references to non-existent nodes."""
        workflow = {
            "nodes": [
                {"id": "node1", "type": "read-file", "params": {"file": "test.txt"}},
                {"id": "node2", "type": "llm", "params": {"prompt": "Process: ${nonexistent.output}"}},
            ],
            "edges": [
                {"from": "node1", "to": "node2"},
            ],
            "inputs": {},
        }
        errors = validate_data_flow(workflow)
        assert len(errors) > 0
        assert "non-existent node 'nonexistent'" in errors[0]
        assert "node2" in errors[0]

    def test_undefined_input_parameter(self):
        """Test detection of undefined input parameters."""
        workflow = {
            "nodes": [
                {
                    "id": "fetch",
                    "type": "github-list-issues",
                    "params": {
                        "repo_owner": "${owner}",  # Not in inputs!
                        "repo_name": "${repo_name}",
                    },
                },
            ],
            "edges": [],
            "inputs": {
                "repo_name": {"type": "string"}  # Missing 'owner'
            },
        }
        errors = validate_data_flow(workflow)
        assert len(errors) > 0
        assert "undefined input '${owner}'" in errors[0]
        assert "fetch" in errors[0]

    def test_typo_suggestion(self):
        """Test that typos in input names are suggested."""
        workflow = {
            "nodes": [
                {"id": "node", "type": "test", "params": {"data": "${RepoName}"}},  # Wrong case
            ],
            "edges": [],
            "inputs": {"reponame": {"type": "string"}},
        }
        errors = validate_data_flow(workflow)
        assert len(errors) > 0
        assert "did you mean '${reponame}'?" in errors[0]

    def test_circular_dependency_detection(self):
        """Test that circular dependencies are caught."""
        workflow = {
            "nodes": [
                {"id": "a", "type": "llm", "params": {"data": "${b.output}"}},
                {"id": "b", "type": "llm", "params": {"data": "${c.output}"}},
                {"id": "c", "type": "llm", "params": {"data": "${a.output}"}},
            ],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "b", "to": "c"},
                {"from": "c", "to": "a"},  # Creates cycle
            ],
            "inputs": {},
        }
        errors = validate_data_flow(workflow)
        assert len(errors) > 0
        assert "Circular dependency" in errors[0]

    def test_parallel_execution_valid(self):
        """Test workflows with valid parallel branches."""
        workflow = {
            "nodes": [
                {"id": "input", "type": "read-file", "params": {"file": "data.txt"}},
                {"id": "branch1", "type": "llm", "params": {"data": "${input.content}"}},
                {"id": "branch2", "type": "llm", "params": {"data": "${input.content}"}},
                {"id": "merge", "type": "write-file", "params": {"content": "${branch1.output} + ${branch2.output}"}},
            ],
            "edges": [
                {"from": "input", "to": "branch1"},
                {"from": "input", "to": "branch2"},
                {"from": "branch1", "to": "merge"},
                {"from": "branch2", "to": "merge"},
            ],
            "inputs": {},
        }
        errors = validate_data_flow(workflow)
        assert errors == []

    def test_complex_valid_workflow(self):
        """Test a complex but valid workflow."""
        workflow = {
            "nodes": [
                {
                    "id": "fetch_issues",
                    "type": "github-list-issues",
                    "params": {
                        "repo_owner": "${repo_owner}",
                        "repo_name": "${repo_name}",
                    },
                },
                {"id": "categorize", "type": "llm", "params": {"prompt": "Categorize: ${fetch_issues.issues}"}},
                {
                    "id": "generate_changelog",
                    "type": "llm",
                    "params": {"prompt": "Create changelog from ${categorize.response}"},
                },
                {
                    "id": "write",
                    "type": "write-file",
                    "params": {
                        "content": "${generate_changelog.response}",
                        "file_path": "${output_file}",
                    },
                },
            ],
            "edges": [
                {"from": "fetch_issues", "to": "categorize"},
                {"from": "categorize", "to": "generate_changelog"},
                {"from": "generate_changelog", "to": "write"},
            ],
            "inputs": {
                "repo_owner": {"type": "string"},
                "repo_name": {"type": "string"},
                "output_file": {"type": "string"},
            },
        }
        errors = validate_data_flow(workflow)
        assert errors == []

    def test_shell_command_with_mixed_syntax(self):
        """Test shell commands with both pflow templates and bash-specific syntax.

        Critical test: Ensures pflow templates are validated even in shell commands
        that also contain bash-specific patterns. This prevents false positives where
        valid pflow templates would be incorrectly skipped.
        """
        workflow = {
            "nodes": [
                {
                    "id": "fetch",
                    "type": "shell",
                    "params": {
                        # Mix of pflow templates and bash syntax:
                        # - ${api_url}, ${limit}: pflow templates (MUST validate)
                        # - ${array[@]}: bash syntax (skip validation)
                        # - ${#count}: bash length operator (skip validation)
                        "command": "curl ${api_url} | head -n ${limit}; echo ${array[@]} ${#count}"
                    },
                },
            ],
            "edges": [],
            "inputs": {
                "api_url": {"type": "string"},
                "limit": {"type": "number"},
            },
        }
        errors = validate_data_flow(workflow)
        # Should pass: pflow templates are valid, bash syntax is ignored
        assert errors == []

    def test_shell_command_with_invalid_pflow_template(self):
        """Test that invalid pflow templates in shell commands are still caught.

        Ensures the bash syntax detection doesn't create a loophole where
        invalid pflow templates could slip through validation.
        """
        workflow = {
            "nodes": [
                {
                    "id": "fetch",
                    "type": "shell",
                    "params": {
                        # ${undefined_input}: Invalid pflow template (should error)
                        # ${array[@]}: Valid bash syntax (should be ignored)
                        "command": "curl ${undefined_input} && echo ${array[@]}"
                    },
                },
            ],
            "edges": [],
            "inputs": {},
        }
        errors = validate_data_flow(workflow)
        # Should fail: undefined_input is not declared
        assert len(errors) == 1
        assert "undefined_input" in errors[0]
        assert "fetch" in errors[0]


class TestBatchDataFlowValidation:
    """Test batch-specific data flow validation."""

    def test_batch_item_alias_default_valid(self):
        """${item} should be valid when node has batch config."""
        workflow = {
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${items}"},
                    "params": {"prompt": "Process: ${item}"},
                }
            ],
            "edges": [],
            "inputs": {"items": {"type": "array"}},
        }
        errors = validate_data_flow(workflow)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_batch_item_alias_custom_valid(self):
        """Custom alias via batch.as should be valid."""
        workflow = {
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${records}", "as": "record"},
                    "params": {"prompt": "Process: ${record}"},
                }
            ],
            "edges": [],
            "inputs": {"records": {"type": "array"}},
        }
        errors = validate_data_flow(workflow)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_batch_item_alias_wrong_name_fails(self):
        """Using wrong alias name should fail validation."""
        workflow = {
            "nodes": [
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${items}", "as": "record"},
                    # Using ${item} when alias is "record" - should fail
                    "params": {"prompt": "Process: ${item}"},
                }
            ],
            "edges": [],
            "inputs": {"items": {"type": "array"}},
        }
        errors = validate_data_flow(workflow)
        assert len(errors) > 0
        assert any("item" in e for e in errors)

    def test_multiple_batch_nodes_different_aliases(self):
        """Multiple batch nodes with different aliases should all be valid."""
        workflow = {
            "nodes": [
                {
                    "id": "process-a",
                    "type": "llm",
                    "batch": {"items": "${items_a}", "as": "item_a"},
                    "params": {"prompt": "A: ${item_a}"},
                },
                {
                    "id": "process-b",
                    "type": "llm",
                    "batch": {"items": "${items_b}", "as": "item_b"},
                    "params": {"prompt": "B: ${item_b}"},
                },
            ],
            "edges": [{"from": "process-a", "to": "process-b"}],
            "inputs": {
                "items_a": {"type": "array"},
                "items_b": {"type": "array"},
            },
        }
        errors = validate_data_flow(workflow)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_batch_with_node_output_reference(self):
        """Batch nodes should allow referencing previous node outputs."""
        workflow = {
            "nodes": [
                {
                    "id": "fetch",
                    "type": "http",
                    "params": {"url": "${api_url}"},
                },
                {
                    "id": "process",
                    "type": "llm",
                    "batch": {"items": "${items}"},
                    "params": {"prompt": "Process ${item} from ${fetch.response}"},
                },
            ],
            "edges": [{"from": "fetch", "to": "process"}],
            "inputs": {
                "api_url": {"type": "string"},
                "items": {"type": "array"},
            },
        }
        errors = validate_data_flow(workflow)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_batch_item_dotted_reference_valid(self):
        """Dotted batch item references like ${item.field} should be valid.

        This is a regression test for the bug where batch aliases were checked
        for simple refs but not for dotted refs, causing workflows with
        ${item.name} or ${item.nested.path} to fail validation incorrectly.
        """
        workflow = {
            "ir_version": "1.0.0",
            "nodes": [
                {"id": "source", "type": "shell", "params": {"command": 'echo \'[{"name":"test"}]\''}},
                {
                    "id": "process",
                    "type": "shell",
                    "batch": {"items": "${source.stdout}"},
                    "params": {"command": "echo ${item.name}"},
                },
            ],
            "edges": [{"from": "source", "to": "process"}],
        }
        errors = validate_data_flow(workflow)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_batch_item_deeply_nested_dotted_reference(self):
        """Deeply nested dotted refs like ${item.a.b.c} should be valid."""
        workflow = {
            "nodes": [
                {"id": "source", "type": "shell", "params": {"command": 'echo \'[{"a":{"b":{"c":1}}}]\''}},
                {
                    "id": "process",
                    "type": "shell",
                    "batch": {"items": "${source.stdout}"},
                    "params": {"command": "echo ${item.a.b.c}"},
                },
            ],
            "edges": [{"from": "source", "to": "process"}],
        }
        errors = validate_data_flow(workflow)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_batch_custom_alias_dotted_reference(self):
        """Custom alias with dotted ref like ${record.field} should be valid."""
        workflow = {
            "nodes": [
                {"id": "source", "type": "shell", "params": {"command": "echo '[{\"x\":1}]'"}},
                {
                    "id": "process",
                    "type": "shell",
                    "batch": {"items": "${source.stdout}", "as": "record"},
                    "params": {"command": "echo ${record.x}"},
                },
            ],
            "edges": [{"from": "source", "to": "process"}],
        }
        errors = validate_data_flow(workflow)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_batch_multiple_dotted_references_in_command(self):
        """Multiple dotted refs in same command should all be valid."""
        workflow = {
            "nodes": [
                {"id": "source", "type": "shell", "params": {"command": "echo data"}},
                {
                    "id": "process",
                    "type": "shell",
                    "batch": {"items": "${source.stdout}"},
                    "params": {"command": "process ${item.original_url} ${item.filename} ${item.description}"},
                },
            ],
            "edges": [{"from": "source", "to": "process"}],
        }
        errors = validate_data_flow(workflow)
        assert errors == [], f"Unexpected errors: {errors}"
