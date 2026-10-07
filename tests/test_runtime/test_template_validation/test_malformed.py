"""Test malformed template syntax detection.

This module tests that the template validator catches malformed template syntax
like unclosed braces, empty templates, etc.
"""

from unittest.mock import Mock

from pflow.registry import Registry
from tests.shared.diagnostic_helpers import split_template_diagnostics


def create_mock_registry(nodes_metadata):
    """Helper to create a properly mocked registry."""
    registry = Registry()

    def get_nodes_metadata(node_types):
        """Mock implementation of get_nodes_metadata."""
        result = {}
        for node_type in node_types:
            if node_type in nodes_metadata:
                result[node_type] = nodes_metadata[node_type]
        return result

    registry.get_nodes_metadata = Mock(side_effect=get_nodes_metadata)
    return registry


class TestMalformedTemplateDetection:
    """Test detection of malformed template syntax."""

    def test_unclosed_template(self):
        """Test that unclosed template ${var is detected."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "test-node",
                    "type": "shell",
                    "params": {"command": "cat", "stdin": "echo ${variable"},
                }
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({"shell": {"interface": {"inputs": [], "outputs": [], "params": []}}})

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        assert len(errors) == 1, f"Expected 1 error but got {len(errors)}: {errors}"
        assert "Malformed template syntax" in errors[0].message
        assert errors[0].node_id == "test-node"
        assert "found 1 '${' but only 0 valid template(s)" in errors[0].message.lower()

    def test_empty_template(self):
        """Test that empty template ${} is detected."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "test-node",
                    "type": "shell",
                    "params": {"command": "cat", "stdin": "echo ${}"},
                }
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({"shell": {"interface": {"inputs": [], "outputs": [], "params": []}}})

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        assert len(errors) == 1
        assert "Malformed template syntax" in errors[0].message
        assert "found 1 '${' but only 0 valid template(s)" in errors[0].message.lower()

    def test_whitespace_only_template(self):
        """Test that whitespace-only template ${ } is detected."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "test-node",
                    "type": "shell",
                    "params": {"command": "cat", "stdin": "echo ${ }"},
                }
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({"shell": {"interface": {"inputs": [], "outputs": [], "params": []}}})

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        assert len(errors) == 1
        assert "Malformed template syntax" in errors[0].message

    def test_multiple_templates_one_malformed(self):
        """Test detection when there are multiple templates and one is malformed."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "shell",
                    "params": {},
                },
                {
                    "id": "node2",
                    "type": "shell",
                    "params": {"command": "cat", "stdin": "echo ${node1.result} and ${unclosed"},
                },
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({
            "shell": {"interface": {"inputs": [], "outputs": [{"key": "result", "type": "str"}], "params": []}}
        })

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        # Should detect the malformed template
        assert any("Malformed template syntax" in err.message for err in errors)
        assert any("found 2 '${' but only 1 valid template(s)" in err.message.lower() for err in errors)

    def test_valid_templates_no_false_positives(self):
        """Test that valid templates don't trigger false positives."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "shell",
                    "params": {},
                },
                {
                    "id": "node2",
                    "type": "shell",
                    "params": {"command": "cat", "stdin": "echo ${node1.result}"},
                },
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({
            "shell": {"interface": {"inputs": [], "outputs": [{"key": "result", "type": "str"}], "params": []}}
        })

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        # Should NOT have malformed template errors
        assert not any("Malformed template syntax" in err.message for err in errors)

    def test_nested_templates_valid(self):
        """Test that nested field access doesn't trigger false positives."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "http",
                    "params": {"url": "https://example.com"},
                },
                {
                    "id": "node2",
                    "type": "shell",
                    "params": {"command": "cat", "stdin": "echo ${node1.response.field.nested}"},
                },
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({
            "http": {"interface": {"inputs": [], "outputs": [{"key": "response", "type": "dict|str"}], "params": []}},
            "shell": {"interface": {"inputs": [], "outputs": [], "params": []}},
        })

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        # Should NOT have malformed template errors
        assert not any("Malformed template syntax" in err.message for err in errors)

    def test_malformed_in_nested_params(self):
        """Test detection of malformed templates in nested parameter structures."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "test-node",
                    "type": "http",
                    "params": {"url": "https://example.com", "headers": {"Authorization": "Bearer ${token"}},
                }
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({"http": {"interface": {"inputs": [], "outputs": [], "params": []}}})

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        assert len(errors) == 1
        assert "Malformed template syntax" in errors[0].message
        # Nested parameter path — path should mention the 'headers' dict key
        assert errors[0].context is not None
        assert "headers" in errors[0].context.get("path", ""), (
            f"Expected 'headers' in context path: {errors[0].context}"
        )

    def test_malformed_in_list_params(self):
        """Test detection of malformed templates in list parameters."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "test-node",
                    "type": "shell",
                    "params": {"commands": ["echo ${valid}", "echo ${invalid"]},
                }
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({"shell": {"interface": {"inputs": [], "outputs": [], "params": []}}})

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        # Should detect malformed template in the list
        malformed_errors = [err for err in errors if "Malformed template syntax" in err.message]
        assert len(malformed_errors) == 1
        # The list-index path is in structured context, not in the message
        assert malformed_errors[0].context is not None
        assert "commands[1]" in malformed_errors[0].context.get("path", ""), (
            f"Expected 'commands[1]' in context path: {malformed_errors[0].context}"
        )

    def test_no_dollar_brace_no_error(self):
        """Test that strings without ${ don't trigger errors."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "test-node",
                    "type": "shell",
                    "params": {"command": "echo hello world"},
                }
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({"shell": {"interface": {"inputs": [], "outputs": [], "params": []}}})

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        # Should have no errors
        assert len(errors) == 0


class TestMalformedTemplateEdgeCases:
    """Test edge cases for malformed template detection."""

    def test_double_dollar_brace(self):
        """Test detection of ${{ which is likely a mistake."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "test-node",
                    "type": "shell",
                    "params": {"command": "cat", "stdin": "echo ${{node.field}}"},
                }
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({"shell": {"interface": {"inputs": [], "outputs": [], "params": []}}})

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        # Double ${{ means 2 ${, but only 1 valid template
        assert any("Malformed template syntax" in err.message for err in errors)

    def test_dollar_escape_of_any_content_is_not_a_template(self):
        """`$${...}` is a literal, whatever its content (issue #620)."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "test-node",
                    "type": "shell",
                    "params": {"command": "cat", "stdin": 'echo "$${NAME:-world} $${#X} $${PRICE}"'},
                }
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({"shell": {"interface": {"inputs": [], "outputs": [], "params": []}}})

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        assert errors == []

    def test_malformed_template_beside_an_escape_is_still_detected(self):
        workflow_ir = {
            "nodes": [
                {
                    "id": "test-node",
                    "type": "shell",
                    "params": {"command": "cat", "stdin": "echo $${NAME:-world} ${unclosed"},
                }
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({"shell": {"interface": {"inputs": [], "outputs": [], "params": []}}})

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        assert len(errors) == 1
        assert "found 1 '${' but only 0 valid template(s)" in errors[0].message

    def test_multiple_malformed_in_same_string(self):
        """Test detection of multiple malformed templates in same string."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "test-node",
                    "type": "shell",
                    "params": {"command": "cat", "stdin": "echo ${first ${second"},
                }
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({"shell": {"interface": {"inputs": [], "outputs": [], "params": []}}})

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        assert len(errors) == 1
        assert "found 2 '${' but only 0 valid template(s)" in errors[0].message.lower()

    def test_coalesce_with_nested_indices_not_malformed(self):
        """Coalesce with multiple nested bracket indices is not malformed.

        ${a[${i}] ?? b[${i}]} has 3 '${' but is 1 valid template with 2
        nested bracket indices. The nested_count must count occurrences,
        not just boolean presence per match.
        """
        workflow_ir = {
            "nodes": [
                {
                    "id": "node1",
                    "type": "shell",
                    "params": {"command": "cat", "stdin": "echo ${a[${i}] ?? b[${i}]}"},
                }
            ],
            "enable_namespacing": True,
        }

        registry = create_mock_registry({"shell": {"interface": {"inputs": [], "outputs": [], "params": []}}})

        errors, _warnings = split_template_diagnostics(workflow_ir, {}, registry)

        # Should NOT flag as malformed — it's a valid coalesce with nested indices
        assert not any("Malformed template syntax" in err.message for err in errors)


_SHELL = {"shell": {"interface": {"inputs": [], "outputs": [{"key": "stdout", "type": "str"}], "params": []}}}


class TestIssuePassCoversEverySurface:
    """Task 170: the ONE Issue pass reports an Issue on every template-bearing surface,
    one diagnostic per value, at the value's authoring path."""

    def _malformed_paths(self, workflow_ir):
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, create_mock_registry(_SHELL))
        return sorted(e.context["path"] for e in errors if "Malformed template syntax" in e.message)

    def test_every_surface_reports_at_its_path(self):
        workflow_ir = {
            "nodes": [
                {
                    "id": "a",
                    "type": "shell",
                    "params": {"command": "cat", "stdin": "echo ${a.b.0}", "env": {"X": ["${}"]}},
                    "batch": {"items": ["${unclosed", "ok"]},
                },
                {
                    "id": "loop",
                    "type": "shell",
                    "params": {"command": "echo hi"},
                    "loop": {"while": "${loop.stdout.0}", "max_iterations": "${x..y}", "carry": {"c": "${loop.s.0}"}},
                },
            ],
            "edges": [{"from": "a", "to": "loop"}],
            "outputs": {"o": {"source": "${a.stdout.}"}},
            "cache": {"items": [{"name": "p.x.0", "var": "p.x.0", "prose_before": "Empty ${} here"}]},
        }
        assert self._malformed_paths(workflow_ir) == sorted([
            "nodes[id=a].params.stdin",
            "nodes[id=a].params.env.X[0]",
            "nodes[id=a].batch.items[0]",
            "nodes[id=loop].loop.while",
            "nodes[id=loop].loop.max_iterations",
            "nodes[id=loop].loop.carry.c",
            "outputs.o.source",
            "cache.items[name=p.x.0].var",
            "cache.items[name=p.x.0].prose_before",
        ])

    def test_well_formed_surfaces_are_clean(self):
        """Partner: the same surfaces holding valid text, an escape, or a literal-only
        expression report nothing."""
        workflow_ir = {
            "nodes": [
                {
                    "id": "a",
                    "type": "shell",
                    "params": {"command": "cat", "stdin": "echo $${HOME} ${a.stdout}", "env": {"X": ['${"v"}']}},
                    "batch": {"items": ["${a.stdout}", "ok"]},
                },
            ],
            "edges": [],
            "outputs": {"o": {"source": "${a.stdout}"}},
            "cache": {"items": [{"name": "a.stdout", "var": "a.stdout", "prose_before": "Cost $${x}: "}]},
        }
        assert self._malformed_paths(workflow_ir) == []

    def test_a_reference_in_cache_prose_is_an_error(self):
        """Dict IR only (the ## Cache chunker turns every markdown reference into a
        chunk): the prose is sent verbatim, so its reference would reach the model."""
        workflow_ir = {
            "nodes": [{"id": "a", "type": "shell", "params": {"command": "echo hi"}}],
            "edges": [],
            "cache": {"items": [{"name": "a.stdout", "var": "a.stdout", "prose_before": "Base ${a.stdout}: "}]},
        }
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, create_mock_registry(_SHELL))
        assert len(errors) == 1
        assert "cache prose may not contain template references (found ${a.stdout})" in errors[0].message
        assert errors[0].context["path"] == "cache.items[name=a.stdout].prose_before"

    def test_malformed_literal_operand_gets_targeted_guidance(self):
        workflow_ir = {
            "nodes": [{"id": "a", "type": "shell", "params": {"command": "cat", "stdin": "echo ${x ?? [1,2]}"}}]
        }
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, create_mock_registry(_SHELL))
        assert len(errors) == 1
        assert errors[0].message.startswith("Malformed literal operand in '${x ?? [1,2]}'")

    def test_malformed_template_suggestion_names_the_issue_and_the_fixes(self):
        """A digit segment is the strict-grammar shape an agent most often writes; the
        suggestion names the offending text and the bracket-index repair."""
        workflow_ir = {
            "nodes": [{"id": "a", "type": "shell", "params": {"command": "cat", "stdin": "echo ${c.stdout.0}"}}]
        }
        errors, _warnings = split_template_diagnostics(workflow_ir, {}, create_mock_registry(_SHELL))
        assert [e.suggestions for e in errors] == [
            [
                "'${c.stdout.0}' is not a valid template. A reference is ${node.field}: index a list as "
                "items[0] (not items.0), close every '${' with '}', and write '$${' for a literal '${'."
            ]
        ]
