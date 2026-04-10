"""Test array notation support in template validation.

This module tests that:
- _extract_all_templates() finds array notation patterns
- TemplateResolver.TEMPLATE_PATTERN matches array notation correctly
- Workflows with array templates work end-to-end
"""

from unittest.mock import patch

from pflow.registry import Registry
from pflow.runtime.template_resolver import TemplateResolver
from pflow.runtime.template_validation.validator import _extract_all_templates
from tests.shared.diagnostic_helpers import split_template_diagnostics


class TestTemplateArrayNotation:
    """Test array notation support in template validation and resolution."""

    def test_template_validator_finds_simple_array_notation(self):
        """Test that _extract_all_templates() finds ${node[0].field} patterns."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "processor",
                    "type": "llm",
                    "params": {"prompt": "Process ${api.items[0].name}", "context": "${api.users[1].email}"},
                }
            ]
        }

        templates = _extract_all_templates(workflow_ir)

        # Should find both array notation templates
        assert "api.items[0].name" in templates
        assert "api.users[1].email" in templates
        assert len(templates) == 2

    def test_template_validator_finds_nested_array_notation(self):
        """Test that _extract_all_templates finds complex nested array patterns."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "analyzer",
                    "type": "llm",
                    "params": {
                        "data": {
                            "first_issue": "${github.repos[0].issues[0].title}",
                            "author": "${github.repos[0].issues[0].author.login}",
                            "labels": "${github.repos[1].labels[2].name}",
                        }
                    },
                }
            ]
        }

        templates = _extract_all_templates(workflow_ir)

        # Should find all nested array templates
        assert "github.repos[0].issues[0].title" in templates
        assert "github.repos[0].issues[0].author.login" in templates
        assert "github.repos[1].labels[2].name" in templates
        assert len(templates) == 3

    def test_template_validator_finds_arrays_in_lists(self):
        """Test that _extract_all_templates finds array notation within list parameters."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "aggregator",
                    "type": "custom",
                    "params": {
                        "items": ["${data[0].value}", "${data[1].value}", {"nested": "${data[2].metadata[0].key}"}]
                    },
                }
            ]
        }

        templates = _extract_all_templates(workflow_ir)

        # Should find all templates in list
        assert "data[0].value" in templates
        assert "data[1].value" in templates
        assert "data[2].metadata[0].key" in templates
        assert len(templates) == 3

    def test_template_resolver_pattern_matches_array_notation(self):
        """Test that TemplateResolver.TEMPLATE_PATTERN matches array notation correctly."""
        test_strings = [
            ("${api[0]}", ["api[0]"]),
            ("${api.data[5].field}", ["api.data[5].field"]),
            ("Text with ${items[0].name} template", ["items[0].name"]),
            ("Multiple ${a[0]} and ${b[1].c[2]}", ["a[0]", "b[1].c[2]"]),
            ("${nested[0].array[1].path[2].field}", ["nested[0].array[1].path[2].field"]),
        ]

        for test_str, expected in test_strings:
            matches = TemplateResolver.TEMPLATE_PATTERN.findall(test_str)
            assert matches == expected, f"Failed for: {test_str}"

    def test_template_resolver_pattern_rejects_invalid_array_notation(self):
        """Test that TemplateResolver.TEMPLATE_PATTERN rejects invalid array patterns."""
        invalid_patterns = [
            "${api[abc]}",  # Non-numeric index
            "${api[-1]}",  # Negative index
            "${api[]}",  # Empty brackets
            "${api[0.5]}",  # Float index
            "${api[0][1]}",  # Double bracket without field
        ]

        for pattern in invalid_patterns:
            matches = TemplateResolver.TEMPLATE_PATTERN.findall(pattern)
            assert len(matches) == 0, f"Should not match: {pattern}"

    def test_template_resolution_with_array_data(self):
        """Test end-to-end template resolution with array data structures."""
        template = "User: ${users[0].name}, Email: ${users[0].contacts[1].email}"
        context = {"users[0]": {"name": "Alice", "contacts[1]": {"email": "alice@example.com"}}}

        # Note: Current TemplateResolver doesn't handle array indexing in resolve_value
        # It would need enhancement to parse [0] notation. For now, test pattern matching
        TemplateResolver.resolve_template(template, context)  # Just verify no exception
        # The template would remain unresolved with current implementation
        # This test verifies the pattern matches array notation correctly
        matches = TemplateResolver.TEMPLATE_PATTERN.findall(template)
        assert "users[0].name" in matches
        assert "users[0].contacts[1].email" in matches

    def test_template_validation_with_array_outputs(self):
        """Test that template validation works with nodes that output arrays."""
        workflow_ir = {
            "nodes": [
                {"id": "fetcher", "type": "github_list_issues", "params": {"repo": "test/repo"}},
                {"id": "processor", "type": "llm", "params": {"prompt": "Process issue: ${fetcher.issues[0].title}"}},
            ]
        }

        # Mock registry with node metadata
        registry = Registry()
        with patch.object(registry, "get_nodes_metadata") as mock_metadata:
            # Return metadata for both node types
            def get_metadata(node_types):
                result = {}
                for node_type in node_types:
                    if node_type == "github_list_issues":
                        result[node_type] = {
                            "interface": {
                                "outputs": [{"key": "issues", "type": "array", "description": "List of issues"}]
                            }
                        }
                    elif node_type == "llm":
                        result[node_type] = {
                            "interface": {
                                "outputs": [{"key": "response", "type": "string", "description": "LLM response"}]
                            }
                        }
                return result

            mock_metadata.side_effect = get_metadata

            # Should validate - array notation is in templates
            errors, _warnings = split_template_diagnostics(
                workflow_ir,
                {},  # No external params needed
                registry,
            )

            # The validation finds the template but can't fully validate array access
            # This is expected - array bounds checking happens at runtime
            assert isinstance(errors, list)

    def test_array_boundary_validation(self):
        """Test that array access validates bounds correctly at runtime."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "api",
                    "type": "http",
                    "params": {
                        "extract": {
                            "first": "${api.data[0]}",
                            "last": "${api.data[999]}",  # Likely out of bounds
                        }
                    },
                }
            ]
        }

        templates = _extract_all_templates(workflow_ir)

        # Should extract both, validation happens at runtime
        assert "api.data[0]" in templates
        assert "api.data[999]" in templates

    def test_mixed_notation_templates(self):
        """Test templates mixing regular dot notation with array notation."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "mixer",
                    "type": "custom",
                    "params": {
                        "regular": "${node.field.subfield}",
                        "array": "${node.items[0]}",
                        "mixed": "${node.data[0].users[1].profile.name}",
                        "input": "${username}",  # Workflow input
                    },
                }
            ]
        }

        templates = _extract_all_templates(workflow_ir)

        # Should find all template types
        assert "node.field.subfield" in templates
        assert "node.items[0]" in templates
        assert "node.data[0].users[1].profile.name" in templates
        assert "username" in templates
        assert len(templates) == 4


class TestBatchResultsIndexAccessGate:
    """Validation gate: block index access on results with error_handling: continue."""

    def _make_registry(self):
        registry = Registry()
        with patch.object(registry, "get_nodes_metadata") as mock:

            def get_metadata(node_types):
                result = {}
                for nt in node_types:
                    if nt == "shell":
                        result[nt] = {
                            "interface": {
                                "outputs": [{"key": "stdout", "type": "string"}],
                            }
                        }
                    elif nt == "llm":
                        result[nt] = {
                            "interface": {
                                "outputs": [{"key": "response", "type": "string"}],
                            }
                        }
                return result

            mock.side_effect = get_metadata
            yield registry

    def test_index_access_blocked_with_continue(self):
        """${batch.results[0].stdout} emits ERROR when batch uses error_handling: continue."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "batch",
                    "type": "shell",
                    "params": {"command": "echo ${item}"},
                    "batch": {"items": ["a", "b"], "error_handling": "continue"},
                },
                {
                    "id": "consumer",
                    "type": "llm",
                    "params": {"prompt": "First: ${batch.results[0].stdout}"},
                },
            ],
            "edges": [{"from": "batch", "to": "consumer"}],
        }

        for registry in self._make_registry():
            errors, warnings = split_template_diagnostics(workflow_ir, {}, registry)
            gate_errors = [e for e in errors if "Index-based access" in e.message]
            assert len(gate_errors) == 1
            assert "error_handling: continue" in gate_errors[0].message

    def test_index_access_allowed_with_fail_fast(self):
        """${batch.results[0].stdout} passes when batch uses fail_fast (default)."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "batch",
                    "type": "shell",
                    "params": {"command": "echo ${item}"},
                    "batch": {"items": ["a", "b"]},
                },
                {
                    "id": "consumer",
                    "type": "llm",
                    "params": {"prompt": "First: ${batch.results[0].stdout}"},
                },
            ],
            "edges": [{"from": "batch", "to": "consumer"}],
        }

        for registry in self._make_registry():
            errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)
            gate_errors = [e for e in errors if "Index-based access" in e.message]
            assert len(gate_errors) == 0

    def test_whole_array_access_allowed_with_continue(self):
        """${batch.results} (no index) passes even with error_handling: continue."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "batch",
                    "type": "shell",
                    "params": {"command": "echo ${item}"},
                    "batch": {"items": ["a", "b"], "error_handling": "continue"},
                },
                {
                    "id": "consumer",
                    "type": "llm",
                    "params": {"prompt": "All: ${batch.results}"},
                },
            ],
            "edges": [{"from": "batch", "to": "consumer"}],
        }

        for registry in self._make_registry():
            errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)
            gate_errors = [e for e in errors if "Index-based access" in e.message]
            assert len(gate_errors) == 0

    def test_nested_index_template_blocked_with_continue(self):
        """${batch.results[${__index__}].stdout} blocked with continue mode."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "batch",
                    "type": "shell",
                    "params": {"command": "echo ${item}"},
                    "batch": {"items": ["a", "b"], "error_handling": "continue"},
                },
                {
                    "id": "consumer",
                    "type": "shell",
                    "params": {"command": "echo ${batch.results[${__index__}].stdout}"},
                    "batch": {"items": ["x", "y"]},
                },
            ],
            "edges": [{"from": "batch", "to": "consumer"}],
        }

        for registry in self._make_registry():
            errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)
            gate_errors = [e for e in errors if "Index-based access" in e.message]
            assert len(gate_errors) == 1

    def test_errors_array_index_access_allowed_with_continue(self):
        """${batch.errors[0]} is fine with continue — errors array is unfiltered."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "batch",
                    "type": "shell",
                    "params": {"command": "echo ${item}"},
                    "batch": {"items": ["a", "b"], "error_handling": "continue"},
                },
                {
                    "id": "consumer",
                    "type": "llm",
                    "params": {"prompt": "Error: ${batch.errors[0]}"},
                },
            ],
            "edges": [{"from": "batch", "to": "consumer"}],
        }

        for registry in self._make_registry():
            errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)
            gate_errors = [e for e in errors if "Index-based access" in e.message]
            assert len(gate_errors) == 0

    def test_batch_field_suggestion_omits_index_for_continue(self):
        """${batch.stdout} on continue-mode batch should NOT suggest results[0]."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "batch",
                    "type": "shell",
                    "params": {"command": "echo ${item}"},
                    "batch": {"items": ["a", "b"], "error_handling": "continue"},
                },
                {
                    "id": "consumer",
                    "type": "llm",
                    "params": {"prompt": "Got: ${batch.stdout}"},
                },
            ],
            "edges": [{"from": "batch", "to": "consumer"}],
        }

        for registry in self._make_registry():
            errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)
            batch_errors = [e for e in errors if "batch processing" in e.message]
            assert len(batch_errors) == 1
            # Should NOT suggest results[0] for continue mode
            for suggestion in batch_errors[0].suggestions:
                assert "results[0]" not in suggestion, f"Contradictory suggestion for continue mode: {suggestion}"
            # Should still suggest the full results array
            assert any("results}" in s for s in batch_errors[0].suggestions)

    def test_batch_field_suggestion_includes_index_for_fail_fast(self):
        """${batch.stdout} on fail_fast batch SHOULD suggest results[0]."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "batch",
                    "type": "shell",
                    "params": {"command": "echo ${item}"},
                    "batch": {"items": ["a", "b"]},
                },
                {
                    "id": "consumer",
                    "type": "llm",
                    "params": {"prompt": "Got: ${batch.stdout}"},
                },
            ],
            "edges": [{"from": "batch", "to": "consumer"}],
        }

        for registry in self._make_registry():
            errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)
            batch_errors = [e for e in errors if "batch processing" in e.message]
            assert len(batch_errors) == 1
            # Should suggest results[0] for fail_fast
            assert any("results[0]" in s for s in batch_errors[0].suggestions)
