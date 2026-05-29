"""Validation tests for Optional A — literal operands in ?? and bare literals.

Covers: valid literal operands no longer trip "malformed template syntax",
literals don't produce false "no valid source" path errors, and malformed
literal operands get a targeted diagnostic.
"""

from unittest.mock import Mock

from pflow.registry import Registry
from tests.shared.diagnostic_helpers import split_template_diagnostics


def create_mock_registry(nodes_metadata):
    registry = Registry()

    def get_nodes_metadata(node_types):
        return {nt: nodes_metadata[nt] for nt in node_types if nt in nodes_metadata}

    registry.get_nodes_metadata = Mock(side_effect=get_nodes_metadata)
    return registry


def _registry():
    return create_mock_registry({
        "shell": {"interface": {"inputs": [], "outputs": [{"key": "stdout", "type": "str"}], "params": []}}
    })


def _ir(command: str) -> dict:
    return {
        "nodes": [
            {"id": "producer", "type": "shell", "params": {"command": "echo hi"}},
            {"id": "consumer", "type": "shell", "params": {"command": command}},
        ],
        "edges": [{"from": "producer", "to": "consumer"}],
        "enable_namespacing": True,
    }


class TestLiteralOperandValidation:
    def test_literal_number_operand_validates_clean(self):
        errors, _ = split_template_diagnostics(_ir("echo ${producer.stdout ?? 0}"), {}, _registry())
        assert errors == [], f"expected no errors, got {[e.message for e in errors]}"

    def test_literal_string_operand_validates_clean(self):
        errors, _ = split_template_diagnostics(_ir('echo ${producer.stdout ?? "fallback"}'), {}, _registry())
        assert errors == [], f"expected no errors, got {[e.message for e in errors]}"

    def test_literal_null_operand_validates_clean(self):
        errors, _ = split_template_diagnostics(_ir("echo ${producer.stdout ?? null}"), {}, _registry())
        assert errors == [], f"expected no errors, got {[e.message for e in errors]}"

    def test_bare_literal_validates_clean(self):
        errors, _ = split_template_diagnostics(_ir("echo ${0}"), {}, _registry())
        assert errors == [], f"expected no errors, got {[e.message for e in errors]}"

    def test_literal_does_not_produce_no_valid_source(self):
        errors, _ = split_template_diagnostics(_ir("echo ${producer.stdout ?? 0}"), {}, _registry())
        assert not any("no valid source" in e.message.lower() for e in errors)
        assert not any("'0'" in e.message for e in errors)


class TestMalformedLiteralOperand:
    def test_composite_array_literal_gets_targeted_message(self):
        errors, _ = split_template_diagnostics(_ir("echo ${producer.stdout ?? [1, 2]}"), {}, _registry())
        assert errors, "expected a malformed-literal error"
        assert any("literal operand" in e.message.lower() for e in errors), [e.message for e in errors]

    def test_unterminated_string_literal_gets_targeted_message(self):
        errors, _ = split_template_diagnostics(_ir('echo ${producer.stdout ?? "abc}'), {}, _registry())
        assert errors, "expected a malformed-literal error"
        assert any("literal operand" in e.message.lower() for e in errors), [e.message for e in errors]

    def test_leading_zero_integer_is_rejected(self):
        # JSON forbids leading zeros; the grammar must reject 007 so it errors at
        # validation instead of silently failing to resolve at runtime.
        for cmd in ("echo ${producer.stdout ?? 007}", "echo ${producer.stdout ?? 01}", "echo ${producer.stdout ?? 00}"):
            errors, _ = split_template_diagnostics(_ir(cmd), {}, _registry())
            assert errors, f"{cmd}: expected a malformed-literal error"
            assert any("literal operand" in e.message.lower() for e in errors), f"{cmd}: {[e.message for e in errors]}"

    def test_string_literal_containing_double_question_is_rejected(self):
        # The operand splitter splits on `??`; a string literal containing `??`
        # would be shredded, so the grammar must reject it loudly.
        errors, _ = split_template_diagnostics(_ir('echo ${producer.stdout ?? "a ?? b"}'), {}, _registry())
        assert errors, "expected a malformed-literal error"
        assert any("literal operand" in e.message.lower() for e in errors), [e.message for e in errors]

    def test_single_question_in_string_literal_is_allowed(self):
        # A lone `?` inside a string is fine — only the `??` sequence is forbidden.
        errors, _ = split_template_diagnostics(_ir('echo ${producer.stdout ?? "why?"}'), {}, _registry())
        assert errors == [], f"expected no errors, got {[e.message for e in errors]}"
