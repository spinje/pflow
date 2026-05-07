"""Tests for unified output auto-detection.

These tests guard the single find_auto_output implementation used by
both CLI text and JSON/MCP paths. A regression here silently changes
what users and agents see — no error, just different data.
"""

from pflow.execution.formatters.output_utils import (
    _find_in_namespaces,
    _is_valid_output_value,
    find_auto_output,
    find_only_output,
)


class TestIsValidOutputValue:
    """Tests for output value validity checking."""

    def test_none_is_invalid(self):
        assert _is_valid_output_value(None) is False

    def test_empty_string_is_invalid(self):
        assert _is_valid_output_value("") is False

    def test_whitespace_string_is_invalid(self):
        assert _is_valid_output_value("   ") is False

    def test_non_empty_string_is_valid(self):
        assert _is_valid_output_value("hello") is True

    def test_zero_is_valid(self):
        """Zero is a meaningful value, not absence."""
        assert _is_valid_output_value(0) is True

    def test_false_is_valid(self):
        """False is a meaningful value, not absence."""
        assert _is_valid_output_value(False) is True

    def test_empty_dict_is_valid(self):
        """Empty dict is a valid structured result."""
        assert _is_valid_output_value({}) is True

    def test_empty_list_is_valid(self):
        """Empty list is a valid structured result."""
        assert _is_valid_output_value([]) is True


class TestFindInNamespaces:
    """Tests for namespace traversal."""

    def test_basic_find(self):
        shared = {"node-a": {"stdout": "hello"}}
        assert _find_in_namespaces(shared, "stdout") == "hello"

    def test_last_wins(self):
        """Most downstream node's value should be returned."""
        shared = {
            "node-a": {"stdout": "first"},
            "node-b": {"stdout": "second"},
        }
        assert _find_in_namespaces(shared, "stdout") == "second"

    def test_underscore_prefix_skip(self):
        """Single-underscore prefixed keys are internal, skip them."""
        shared = {"_internal": {"stdout": "hidden"}}
        assert _find_in_namespaces(shared, "stdout") is None

    def test_double_underscore_prefix_skip(self):
        """Double-underscore prefixed keys are internal, skip them."""
        shared = {"__execution__": {"stdout": "hidden"}}
        assert _find_in_namespaces(shared, "stdout") is None

    def test_validity_filtering(self):
        """None and empty strings inside namespaces are skipped."""
        shared = {
            "node-a": {"result": None},
            "node-b": {"result": ""},
            "node-c": {"result": "   "},
        }
        assert _find_in_namespaces(shared, "result") is None

    def test_non_dict_values_skipped(self):
        """Non-dict values at root level are not namespaces."""
        shared = {"plain_string": "not a namespace", "node": {"result": "found"}}
        assert _find_in_namespaces(shared, "result") == "found"


class TestFindAutoOutput:
    """Tests for the unified auto-detection function."""

    def test_result_beats_response(self):
        shared = {"result": "R", "response": "S"}
        key, value = find_auto_output(shared)
        assert key == "result"
        assert value == "R"

    def test_response_beats_output(self):
        shared = {"response": "S", "output": "O"}
        key, value = find_auto_output(shared)
        assert key == "response"
        assert value == "S"

    def test_output_beats_text(self):
        shared = {"output": "O", "text": "T"}
        key, value = find_auto_output(shared)
        assert key == "output"
        assert value == "O"

    def test_text_beats_data(self):
        shared = {"text": "T", "data": "D"}
        key, value = find_auto_output(shared)
        assert key == "text"
        assert value == "T"

    def test_data_beats_stdout(self):
        shared = {"data": "D", "stdout": "S"}
        key, value = find_auto_output(shared)
        assert key == "data"
        assert value == "D"

    def test_root_before_namespace(self):
        """Same key at root and namespace — root wins."""
        shared = {
            "result": "root value",
            "node-a": {"result": "namespace value"},
        }
        key, value = find_auto_output(shared)
        assert key == "result"
        assert value == "root value"

    def test_namespace_search_when_not_at_root(self):
        """Priority key found inside namespace when not at root."""
        shared = {
            "__execution__": {},
            "node-a": {"stdout": "found in namespace"},
        }
        key, value = find_auto_output(shared)
        assert key == "stdout"
        assert value == "found in namespace"

    def test_validity_filtering_root(self):
        """None/empty at root are skipped, falls through to next key."""
        shared = {"result": None, "response": "", "output": "valid"}
        key, value = find_auto_output(shared)
        assert key == "output"
        assert value == "valid"

    def test_validity_filtering_falls_to_namespace(self):
        """Invalid root value, valid namespace value for same key."""
        shared = {
            "result": None,
            "node-a": {"result": "namespace result"},
        }
        key, value = find_auto_output(shared)
        assert key == "result"
        assert value == "namespace result"

    def test_underscore_key_ignored(self):
        """Single-underscore prefixed keys are filtered out."""
        shared = {"_internal": "hidden"}
        key, value = find_auto_output(shared)
        assert key is None
        assert value is None

    def test_double_underscore_key_ignored(self):
        """Double-underscore prefixed keys are filtered out."""
        shared = {"__execution__": {"data": "hidden"}}
        key, value = find_auto_output(shared)
        assert key is None
        assert value is None

    def test_last_key_fallback(self):
        """Non-standard key found when no priority key matches."""
        shared = {"custom_key": "custom value"}
        key, value = find_auto_output(shared)
        assert key == "custom_key"
        assert value == "custom value"

    def test_last_key_fallback_skips_invalid(self):
        """Last-key fallback skips None/empty values."""
        shared = {
            "first": "valid",
            "second": None,
            "third": "",
        }
        key, value = find_auto_output(shared)
        # "third" and "second" are invalid; falls back to "first"
        assert key == "first"
        assert value == "valid"

    def test_empty_store_returns_none(self):
        key, value = find_auto_output({})
        assert key is None
        assert value is None

    def test_all_invalid_values_returns_none(self):
        shared = {"a": None, "b": "", "c": "   "}
        key, value = find_auto_output(shared)
        assert key is None
        assert value is None

    def test_all_internal_keys_returns_none(self):
        """Store with only internal keys returns nothing."""
        shared = {"_a": "one", "__b__": "two"}
        key, value = find_auto_output(shared)
        assert key is None
        assert value is None

    def test_full_priority_order(self):
        """Verify complete priority chain: result > response > output > text > data > stdout."""
        all_keys = {
            "stdout": "S",
            "data": "D",
            "text": "T",
            "output": "O",
            "response": "R",
            "result": "X",
        }
        key, value = find_auto_output(all_keys)
        assert key == "result"
        assert value == "X"

    def test_zero_value_is_returned(self):
        """Zero is a valid output value."""
        shared = {"result": 0}
        key, value = find_auto_output(shared)
        assert key == "result"
        assert value == 0

    def test_false_value_is_returned(self):
        """False is a valid output value."""
        shared = {"result": False}
        key, value = find_auto_output(shared)
        assert key == "result"
        assert value is False

    def test_dict_value_at_root_is_returned(self):
        """Dict values at root level are valid outputs (not just namespaces)."""
        shared = {"result": {"key": "value"}}
        key, value = find_auto_output(shared)
        assert key == "result"
        assert value == {"key": "value"}


class TestFindOnlyOutput:
    """Tests for target-scoped --only output selection."""

    def test_flat_target_unwraps_stdout(self):
        shared = {"fetch": {"stdout": "target stdout", "exit_code": 0}}
        key, value = find_only_output(shared, "fetch")
        assert key == "stdout"
        assert value == "target stdout"

    def test_flat_target_with_no_priority_key_returns_full_namespace(self):
        namespace = {"items": [1, 2, 3], "count": 3}
        shared = {"fetch": namespace}
        key, value = find_only_output(shared, "fetch")
        assert key == "fetch"
        assert value == namespace

    def test_dotted_target_returns_root_namespace(self):
        namespace = {"results": [{"result": "hello"}], "count": 1}
        shared = {"child": namespace, "result": "unrelated declared output"}
        key, value = find_only_output(shared, "child.fetch")
        assert key == "child"
        assert value == namespace

    def test_unrelated_root_result_does_not_shadow_target(self):
        shared = {
            "result": "root result should not win",
            "fetch": {"stdout": "target stdout"},
        }
        key, value = find_only_output(shared, "fetch")
        assert key == "stdout"
        assert value == "target stdout"

    def test_missing_target_returns_none(self):
        shared = {"result": "root result should not win"}
        key, value = find_only_output(shared, "fetch")
        assert key is None
        assert value is None


class TestAutoDetectionWarning:
    """Tests for the CLI warning messages when auto-detection is used."""

    def test_no_declared_outputs_warning(self, capsys):
        """CORRECTNESS: Warning says 'No outputs declared' when workflow has no outputs."""
        from pflow.cli.workflow_output import _handle_text_output

        shared = {"result": "some value"}
        _handle_text_output(shared, output_key=None, workflow_ir=None, verbose=False)

        captured = capsys.readouterr()
        assert "No outputs declared" in captured.err
        assert "auto-detected key 'result'" in captured.err

    def test_only_node_falls_through_to_auto_detect_when_declared_outputs_unresolvable(self, capsys):
        """REGRESSION GUARD: --only on a node whose output isn't referenced by any
        declared output must still emit the targeted node's output to stdout.

        Before target-scoped --only routing, the CLI's declared-output branch
        could return False silently and never reach a useful target output,
        leaving stdout empty.
        """
        from pflow.cli.workflow_output import _handle_text_output

        # --only targeted "upstream" whose stdout is in shared, but the only
        # declared output sources from "downstream" which didn't execute.
        shared = {
            "__execution__": {"only_node": "upstream"},
            "upstream": {"stdout": "target-node-value"},
        }
        workflow_ir = {"outputs": {"final": {"source": "${downstream.stdout}"}}}
        _handle_text_output(shared, output_key=None, workflow_ir=workflow_ir, verbose=False)

        captured = capsys.readouterr()
        # Auto-detected value MUST reach stdout — this is the silent regression we fix
        assert "target-node-value" in captured.out
        assert (
            "cli: --only active — streaming auto-detected key 'stdout' from target 'upstream' to stdout."
            in captured.err
        )
        assert "Declared outputs unresolvable" not in captured.err
        assert "No outputs declared" not in captured.err

    def test_dotted_only_prefers_target_namespace_over_shadowing_declared_output(self, capsys):
        """GH #344 regression guard: dotted --only on a batch sub-workflow must
        emit the target's namespace, even when a parent-level declared output
        resolved to a priority-key name at root.

        Setup mirrors the real lyrics-generator case: the parent has two
        declared outputs. The first (becomes stdout target) references a
        downstream node and fails to resolve under --only. The second is
        named 'result' and references an upstream node that DID run, so it
        resolves at root. The dedicated --only selector must ignore that
        unrelated root value and return the target batch namespace.
        """
        from pflow.cli.workflow_output import _handle_text_output

        shared = {
            "__execution__": {"only_node": "process-all.echo"},
            # Unrelated upstream declared output that resolved at root (shadowing)
            "result": ["upstream", "data", "NOT", "what", "user", "wants"],
            # Target: the batch node's namespace — what the user actually wants to see
            "process-all": {
                "results": [
                    {"result": "hello", "item": "hello"},
                    {"result": "world", "item": "world"},
                ],
                "count": 2,
            },
        }
        workflow_ir = {
            "outputs": {
                # First = stdout target, references downstream → won't resolve
                "downstream_summary": {"source": "${count.stdout}"},
                # Second = resolves, shadows batch namespace in priority search
                "result": {"source": "${upstream.stdout}"},
            }
        }
        _handle_text_output(shared, output_key=None, workflow_ir=workflow_ir, verbose=False)

        captured = capsys.readouterr()
        # Target namespace MUST reach stdout — the batch namespace, not the shadowing value
        assert '"count": 2' in captured.out  # batch namespace structure
        # Critically: the shadowing value MUST NOT reach stdout
        assert "NOT" not in captured.out
        assert (
            "cli: --only active — streaming auto-detected key 'process-all' from target 'process-all.echo' to stdout."
        ) in captured.err
        assert "Declared outputs unresolvable" not in captured.err

    def test_only_node_without_target_output_warns_with_target_context(self, capsys):
        """CORRECTNESS: --only never lets unrelated root values shadow the target."""
        from pflow.cli.workflow_output import _handle_text_output

        shared = {
            "__execution__": {"only_node": "fetch"},
            "result": "some value",
        }
        # No outputs declared in workflow_ir
        _handle_text_output(shared, output_key=None, workflow_ir={"nodes": []}, verbose=False)

        captured = capsys.readouterr()
        assert captured.out == ""
        assert (
            "cli: --only target 'fetch' produced no output. Pass -o <key> to select a specific shared-store key."
        ) in captured.err
        assert "No outputs declared" not in captured.err
        assert "Declared outputs skipped" not in captured.err

    def test_print_mode_suppresses_warning(self, capsys):
        """CORRECTNESS: --print mode shows no warning (clean for piping)."""
        from pflow.cli.workflow_output import _handle_text_output

        shared = {"result": "some value"}
        _handle_text_output(shared, output_key=None, workflow_ir=None, verbose=False, print_flag=True)

        captured = capsys.readouterr()
        assert "No outputs declared" not in captured.err
        assert "auto-detected" not in captured.err
