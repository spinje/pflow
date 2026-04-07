"""Test the data flow validation module."""

import pytest

from pflow.core.diagnostic import format_diagnostic
from pflow.core.workflow.data_flow import CycleError, build_execution_order, validate_data_flow


def _data_flow_error_messages(workflow_ir: dict) -> list[str]:
    return [format_diagnostic(diagnostic) for diagnostic in validate_data_flow(workflow_ir)]


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
        errors = _data_flow_error_messages(workflow)
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
        errors = _data_flow_error_messages(workflow)
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
        errors = _data_flow_error_messages(workflow)
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
        errors = _data_flow_error_messages(workflow)
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
        errors = _data_flow_error_messages(workflow)
        assert len(errors) > 0
        assert "did you mean '${reponame}'?" in errors[0].lower()

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
        errors = _data_flow_error_messages(workflow)
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
        errors = _data_flow_error_messages(workflow)
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
        errors = _data_flow_error_messages(workflow)
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
        errors = _data_flow_error_messages(workflow)
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
        errors = _data_flow_error_messages(workflow)
        # Should fail: undefined_input is not declared
        assert len(errors) == 1
        assert "undefined_input" in errors[0]
        assert "fetch" in errors[0]


class TestArrayAccessValidation:
    """Test that pflow array access templates are validated (not skipped as bash).

    These tests verify the fix where _is_bash_syntax() was replaced with positive
    pflow pattern matching. Previously, ALL bracket-containing templates were
    skipped as bash syntax, meaning ${results[0].field} got zero validation.
    """

    def test_array_access_with_nonexistent_node_fails(self):
        """${nonexistent_node[0].field} should produce 'non-existent node' error."""
        workflow = {
            "nodes": [
                {"id": "process", "type": "shell", "params": {"command": "echo ${nonexistent_node[0].field}"}},
            ],
            "edges": [],
            "inputs": {},
        }
        errors = _data_flow_error_messages(workflow)
        assert len(errors) == 1
        assert "non-existent node 'nonexistent_node'" in errors[0]

    def test_array_access_with_forward_reference_fails(self):
        """${future_node[0].field} where future_node comes after should produce forward ref error."""
        workflow = {
            "nodes": [
                {"id": "early", "type": "shell", "params": {"command": "echo ${late[0].field}"}},
                {"id": "late", "type": "shell", "params": {"command": "echo data"}},
            ],
            "edges": [{"from": "early", "to": "late"}],
            "inputs": {},
        }
        errors = _data_flow_error_messages(workflow)
        assert len(errors) == 1
        assert "'late'" in errors[0]
        assert "after" in errors[0]

    def test_undefined_input_with_array_access_fails(self):
        """${undefined_input[0]} should produce 'non-existent node' error (array access routes through node-ref path)."""
        workflow = {
            "nodes": [
                {"id": "process", "type": "shell", "params": {"command": "echo ${undefined_input[0]}"}},
            ],
            "edges": [],
            "inputs": {},
        }
        errors = _data_flow_error_messages(workflow)
        assert len(errors) == 1
        assert "non-existent node 'undefined_input'" in errors[0]

    def test_valid_array_access_passes(self):
        """${data[0]} where data is a previous node should pass validation."""
        workflow = {
            "nodes": [
                {"id": "data", "type": "shell", "params": {"command": "echo '[1,2,3]'"}},
                {"id": "process", "type": "shell", "params": {"command": "echo ${data[0]}"}},
            ],
            "edges": [{"from": "data", "to": "process"}],
            "inputs": {},
        }
        errors = _data_flow_error_messages(workflow)
        assert errors == []

    def test_valid_dotted_array_access_passes(self):
        """${node.items[0].field} where node is a previous node should pass."""
        workflow = {
            "nodes": [
                {"id": "fetch", "type": "shell", "params": {"command": "echo data"}},
                {"id": "process", "type": "shell", "params": {"command": "echo ${fetch.items[0].field}"}},
            ],
            "edges": [{"from": "fetch", "to": "process"}],
            "inputs": {},
        }
        errors = _data_flow_error_messages(workflow)
        assert errors == []


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
        errors = _data_flow_error_messages(workflow)
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
        errors = _data_flow_error_messages(workflow)
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
        errors = _data_flow_error_messages(workflow)
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
        errors = _data_flow_error_messages(workflow)
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
        errors = _data_flow_error_messages(workflow)
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
        errors = _data_flow_error_messages(workflow)
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
        errors = _data_flow_error_messages(workflow)
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
        errors = _data_flow_error_messages(workflow)
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
        errors = _data_flow_error_messages(workflow)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_batch_dunder_index_valid(self):
        """${__index__} should be valid in batch contexts."""
        workflow = {
            "nodes": [
                {
                    "id": "process",
                    "type": "shell",
                    "batch": {"items": ["a", "b", "c"]},
                    "params": {"command": "echo 'Item ${__index__}: ${item}'"},
                },
            ],
            "edges": [],
        }
        errors = _data_flow_error_messages(workflow)
        assert errors == [], f"__index__ should be valid in batch context: {errors}"

    def test_batch_dunder_index_with_nested_template(self):
        """${results[${__index__}]} nested template should be valid."""
        workflow = {
            "nodes": [
                {
                    "id": "first",
                    "type": "shell",
                    "batch": {"items": ["a", "b", "c"]},
                    "params": {"command": "echo ${item}"},
                },
                {
                    "id": "second",
                    "type": "shell",
                    "batch": {"items": ["x", "y", "z"]},
                    "params": {"command": "echo ${first.results[${__index__}].stdout}"},
                },
            ],
            "edges": [{"from": "first", "to": "second"}],
        }
        errors = _data_flow_error_messages(workflow)
        assert errors == [], f"Nested __index__ template should be valid: {errors}"

    def test_dunder_index_invalid_without_batch(self):
        """${__index__} should be invalid outside batch contexts."""
        workflow = {
            "nodes": [
                {
                    "id": "process",
                    "type": "shell",
                    # No batch config - __index__ is invalid here
                    "params": {"command": "echo ${__index__}"},
                },
            ],
            "edges": [],
        }
        errors = _data_flow_error_messages(workflow)
        assert len(errors) == 1, f"Expected error for __index__ without batch: {errors}"
        assert "__index__" in errors[0]


class TestNestedParamValidation:
    """Test that data flow validation recurses into nested dict/list params.

    Covers the fix for GitHub issue #108: _validate_node_params now recurses
    into dict and list values using _check_param_value(), rather than only
    checking top-level string params.
    """

    def test_forward_reference_inside_dict_param_is_caught(self):
        """Template inside a dict param value referencing a later node should error."""
        workflow_ir = {
            "nodes": [
                {"id": "merge", "type": "code", "params": {"inputs": {"x": "${later-node.stdout}"}, "code": "x"}},
                {"id": "later-node", "type": "shell", "params": {"command": "echo hello"}},
            ],
            "edges": [
                {"from": "merge", "to": "later-node"},  # merge runs first, but refs later-node
            ],
        }
        errors = _data_flow_error_messages(workflow_ir)
        assert len(errors) == 1
        assert "later-node" in errors[0]
        assert "merge" in errors[0]

    def test_non_existent_node_reference_inside_dict_param_is_caught(self):
        """Template inside a dict param value referencing a non-existent node should error."""
        workflow_ir = {
            "nodes": [
                {"id": "merge", "type": "code", "params": {"inputs": {"x": "${no-such-node.stdout}"}, "code": "x"}},
            ],
        }
        errors = _data_flow_error_messages(workflow_ir)
        assert len(errors) == 1
        assert "non-existent" in errors[0].lower() or "no-such-node" in errors[0]

    def test_template_inside_list_param_is_caught(self):
        """Template inside a list param referencing a later node should error."""
        workflow_ir = {
            "nodes": [
                {"id": "process", "type": "code", "params": {"items": ["${future.stdout}"], "code": "x"}},
                {"id": "future", "type": "shell", "params": {"command": "echo hi"}},
            ],
            "edges": [
                {"from": "process", "to": "future"},  # process runs first, but refs future
            ],
        }
        errors = _data_flow_error_messages(workflow_ir)
        assert len(errors) == 1
        assert "future" in errors[0]

    def test_deeply_nested_template_is_caught(self):
        """Template buried in dict-inside-list-inside-dict should still be found."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "deep",
                    "type": "code",
                    "params": {"config": {"nested": [{"val": "${ghost.stdout}"}]}, "code": "x"},
                },
            ],
        }
        errors = _data_flow_error_messages(workflow_ir)
        assert len(errors) == 1
        assert "ghost" in errors[0]

    def test_valid_backward_reference_inside_dict_param_passes(self):
        """Template inside a dict param referencing an earlier node should pass."""
        workflow_ir = {
            "nodes": [
                {"id": "first", "type": "shell", "params": {"command": "echo hello"}},
                {"id": "merge", "type": "code", "params": {"inputs": {"x": "${first.stdout}"}, "code": "x"}},
            ],
            "edges": [
                {"from": "first", "to": "merge"},
            ],
        }
        errors = _data_flow_error_messages(workflow_ir)
        assert errors == []

    def test_coalesce_expression_inside_dict_param_is_validated(self):
        """Coalesce expression inside a dict param should validate all operands."""
        workflow_ir = {
            "nodes": [
                {"id": "merge", "type": "code", "params": {"inputs": {"x": "${a.stdout ?? b.stdout}"}, "code": "x"}},
                {"id": "a", "type": "shell", "params": {"command": "echo a"}},
                {"id": "b", "type": "shell", "params": {"command": "echo b"}},
            ],
            "edges": [
                {"from": "merge", "to": "a"},
                {"from": "a", "to": "b"},
            ],
        }
        errors = _data_flow_error_messages(workflow_ir)
        # Both a and b come after merge — should get errors for both
        assert len(errors) == 2
        assert any("'a'" in e for e in errors)
        assert any("'b'" in e for e in errors)


class TestImprovedErrorMessages:
    """Test improved error messages for undefined input references."""

    def test_undefined_ref_no_inputs_declared(self):
        """When zero inputs are declared, error says 'no inputs are declared'."""
        workflow = {
            "nodes": [
                {
                    "id": "echo",
                    "type": "shell",
                    "params": {"command": "echo ${message}"},
                },
            ],
            "edges": [],
            "inputs": {},
        }
        errors = _data_flow_error_messages(workflow)
        assert len(errors) == 1
        assert "no inputs are declared" in errors[0]
        assert "echo" in errors[0]
        assert "message" in errors[0]

    def test_undefined_ref_lists_declared_inputs(self):
        """When inputs exist but name doesn't match, error lists declared inputs."""
        workflow = {
            "nodes": [
                {
                    "id": "fetch",
                    "type": "shell",
                    "params": {"command": "curl ${urll}"},
                },
            ],
            "edges": [],
            "inputs": {
                "url": {"type": "string"},
                "method": {"type": "string"},
            },
        }
        errors = _data_flow_error_messages(workflow)
        assert len(errors) == 1
        assert "Available fields" in errors[0]
        assert "method" in errors[0]
        assert "url" in errors[0]

    def test_batch_aliases_listed_as_declared_inputs(self):
        """Batch aliases are included in declared inputs when listing valid references."""
        workflow = {
            "nodes": [
                {
                    "id": "process",
                    "type": "shell",
                    "params": {"command": "echo ${unknown_var}"},
                    "batch": {"over": "items", "as": "item"},
                },
            ],
            "edges": [],
            "inputs": {},
        }
        errors = _data_flow_error_messages(workflow)
        assert len(errors) == 1
        assert "Available fields" in errors[0]
        assert "item" in errors[0]

    def test_node_level_inputs_listed_in_error(self):
        """Node-level params.inputs keys appear in declared inputs, not 'no inputs declared'."""
        workflow = {
            "nodes": [
                {
                    "id": "source",
                    "type": "shell",
                    "params": {"command": "echo hello"},
                },
                {
                    "id": "process",
                    "type": "llm",
                    "params": {
                        "inputs": {"brief": "${source.stdout}"},
                        "prompt": "Write about ${brief} for ${audience}",
                    },
                },
            ],
            "edges": [{"from": "source", "to": "process"}],
            "inputs": {},
        }
        errors = _data_flow_error_messages(workflow)
        assert len(errors) == 1
        assert "audience" in errors[0]
        # Should list node-level input 'brief', not say "no inputs are declared"
        assert "Available fields" in errors[0]
        assert "brief" in errors[0]
        assert "no inputs are declared" not in errors[0]

    def test_no_inputs_message_when_truly_empty(self):
        """'No inputs declared' only fires when no valid references exist at all."""
        workflow = {
            "nodes": [
                {
                    "id": "echo",
                    "type": "shell",
                    "params": {"command": "echo ${message}"},
                },
            ],
            "edges": [],
            "inputs": {},
        }
        errors = _data_flow_error_messages(workflow)
        assert len(errors) == 1
        assert "no inputs are declared" in errors[0]
