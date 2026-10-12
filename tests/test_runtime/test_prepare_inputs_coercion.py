"""prepare_inputs() — the workflow input boundary: resolution order, typing by declared
type with the value's source, and one Diagnostic per problem.

Related bug: numeric strings (e.g. Discord snowflake IDs) typed to int before the
workflow's declared ``type: string`` was consulted.
"""

from typing import Any, ClassVar

import pytest

from pflow.core import llm_config
from pflow.core.diagnostic import Diagnostic
from pflow.core.exceptions import WorkflowValidationError
from pflow.registry import Registry
from pflow.runtime.compilation import compile_workflow
from pflow.runtime.compilation.ir_preparation import prepare_inputs


class TestPrepareInputsTypeCoercion:
    """Test that prepare_inputs() coerces values to declared types."""

    def test_int_coerced_to_string_when_declared(self):
        """THE BUG FIX: Int value coerced to string when type: string declared."""
        workflow_ir = {
            "inputs": {
                "channel_id": {
                    "type": "string",
                    "description": "Discord channel ID",
                    "required": True,
                }
            }
        }
        # An int from a typed source (an MCP call, a parent step) for a declared string
        provided_params = {"channel_id": 1458059302022549698}

        errors, defaults, _env_params = prepare_inputs(workflow_ir, provided_params)

        assert errors == []
        # Coerced value should be in defaults
        assert "channel_id" in defaults
        assert isinstance(defaults["channel_id"], str)
        assert defaults["channel_id"] == "1458059302022549698"

    def test_no_coercion_when_type_matches(self):
        """No coercion needed when value already matches declared type."""
        workflow_ir = {
            "inputs": {
                "channel_id": {
                    "type": "string",
                    "description": "Channel ID",
                    "required": True,
                }
            }
        }
        provided_params = {"channel_id": "already-a-string"}

        errors, defaults, _env_params = prepare_inputs(workflow_ir, provided_params)

        assert errors == []
        # No coercion needed, so not in defaults
        assert "channel_id" not in defaults

    def test_no_coercion_when_no_type_declared(self):
        """No coercion when input has no type declaration."""
        workflow_ir = {
            "inputs": {
                "value": {
                    "description": "Some value with no type",
                    "required": True,
                }
            }
        }
        provided_params = {"value": 123}  # Stays as int

        errors, defaults, _env_params = prepare_inputs(workflow_ir, provided_params)

        assert errors == []
        # No coercion, not in defaults
        assert "value" not in defaults

    def test_multiple_inputs_coerced_correctly(self):
        """Multiple inputs should each be coerced according to their types."""
        workflow_ir = {
            "inputs": {
                "channel_id": {"type": "string", "required": True},
                "count": {"type": "integer", "required": True},
                "enabled": {"type": "boolean", "required": True},
            }
        }
        provided_params = {
            "channel_id": 123456789,  # int → string
            "count": "50",  # string → int
            "enabled": "yes",  # string → bool
        }

        errors, defaults, _env_params = prepare_inputs(workflow_ir, provided_params)

        assert errors == []
        assert defaults["channel_id"] == "123456789"
        assert defaults["count"] == 50
        assert defaults["enabled"] is True

    def test_coercion_with_optional_input(self):
        """Coercion should work for optional inputs too."""
        workflow_ir = {
            "inputs": {
                "limit": {
                    "type": "integer",
                    "description": "Optional limit",
                    "required": False,
                }
            }
        }
        provided_params = {"limit": "100"}

        errors, defaults, _env_params = prepare_inputs(workflow_ir, provided_params)

        assert errors == []
        assert defaults["limit"] == 100


class TestPrepareInputsCoercionEdgeCases:
    """Edge cases for input type coercion."""

    def test_large_int_to_string_preserves_precision(self):
        """Large integers should not lose precision when converted to string."""
        workflow_ir = {
            "inputs": {
                "snowflake": {
                    "type": "string",
                    "description": "Discord snowflake ID",
                    "required": True,
                }
            }
        }
        # This is a real Discord snowflake ID
        large_int = 1458059302022549698
        provided_params = {"snowflake": large_int}

        errors, defaults, _env_params = prepare_inputs(workflow_ir, provided_params)

        assert errors == []
        # Verify exact string representation (no precision loss)
        assert defaults["snowflake"] == "1458059302022549698"

    def test_float_to_string_preserves_value(self):
        """Float to string should preserve reasonable precision."""
        workflow_ir = {"inputs": {"value": {"type": "string", "required": True}}}
        provided_params = {"value": 3.14159265359}

        errors, defaults, _env_params = prepare_inputs(workflow_ir, provided_params)

        assert errors == []
        # Should convert cleanly
        assert "3.14159265359" in defaults["value"]

    def test_bool_to_string_gives_python_repr(self):
        """Bool to string gives Python representation (True/False)."""
        workflow_ir = {"inputs": {"flag": {"type": "string", "required": True}}}
        provided_params = {"flag": True}

        errors, defaults, _env_params = prepare_inputs(workflow_ir, provided_params)

        assert errors == []
        assert defaults["flag"] == "True"

    def test_invalid_value_is_a_diagnostic_not_a_pass_through(self):
        """A value its declared type cannot read is an error at the boundary (decision (a))."""
        workflow_ir = {"inputs": {"count": {"type": "integer", "description": "Count", "required": True}}}

        errors, defaults, _env_params = prepare_inputs(workflow_ir, {"count": "not-a-number"})

        assert [e.title for e in errors] == ["Invalid input value"]
        assert errors[0].context is not None
        assert errors[0].context["path"] == "inputs.count"
        assert errors[0].context["received"] == "not-a-number"
        assert "count" not in defaults


class TestPrepareInputsIntegrationWithDefaults:
    """Test coercion interacts correctly with default values."""

    def test_coercion_and_defaults_both_in_result(self):
        """Coerced values and defaults should both be in defaults dict."""
        workflow_ir = {
            "inputs": {
                "channel_id": {"type": "string", "required": True},
                "limit": {"type": "integer", "required": False, "default": 10},
            }
        }
        provided_params = {"channel_id": 123456}  # Needs coercion

        errors, defaults, _env_params = prepare_inputs(workflow_ir, provided_params)

        assert errors == []
        # Coerced value
        assert defaults["channel_id"] == "123456"
        # Default value
        assert defaults["limit"] == 10

    def test_provided_value_not_overridden_by_default(self):
        """Provided value (even after coercion) should not be overridden by default."""
        workflow_ir = {
            "inputs": {
                "limit": {"type": "integer", "required": False, "default": 10},
            }
        }
        provided_params = {"limit": "50"}  # User provided, needs coercion

        errors, defaults, _env_params = prepare_inputs(workflow_ir, provided_params)

        assert errors == []
        # Coerced user value, not default
        assert defaults["limit"] == 50


class TestPrepareInputsEnvSettingsCoercion:
    """Test that env and settings values are also coerced to declared types."""

    def test_settings_env_string_coerced_to_integer(self):
        """Settings env value should be coerced to declared type."""
        workflow_ir = {
            "inputs": {
                "limit": {"type": "integer", "required": True},
            }
        }
        provided_params = {}  # Not provided via CLI
        settings_env = {"limit": "42"}  # String from settings

        errors, defaults, env_params = prepare_inputs(workflow_ir, provided_params, settings_env=settings_env)

        assert errors == []
        assert defaults["limit"] == 42  # Coerced to int
        assert isinstance(defaults["limit"], int)
        assert "limit" in env_params  # Tracked as env param

    def test_settings_env_string_coerced_to_boolean(self):
        """Settings env boolean string should be coerced."""
        workflow_ir = {
            "inputs": {
                "enabled": {"type": "boolean", "required": True},
            }
        }
        provided_params = {}
        settings_env = {"enabled": "true"}

        errors, defaults, _env_params = prepare_inputs(workflow_ir, provided_params, settings_env=settings_env)

        assert errors == []
        assert defaults["enabled"] is True
        assert isinstance(defaults["enabled"], bool)

    def test_workflow_default_coerced_to_declared_type(self):
        """Workflow default values should be coerced to declared type."""
        workflow_ir = {
            "inputs": {
                "count": {
                    "type": "integer",
                    "required": False,
                    "default": "100",  # String default in workflow
                },
            }
        }
        provided_params = {}

        errors, defaults, _env_params = prepare_inputs(workflow_ir, provided_params)

        assert errors == []
        assert defaults["count"] == 100  # Coerced to int
        assert isinstance(defaults["count"], int)

    def test_none_default_not_coerced(self):
        """None values should not be coerced (preserved as None)."""
        workflow_ir = {
            "inputs": {
                "optional": {
                    "type": "string",
                    "required": False,
                    # No default - resolves to None
                },
            }
        }
        provided_params = {}

        errors, defaults, _env_params = prepare_inputs(workflow_ir, provided_params)

        assert errors == []
        assert defaults["optional"] is None  # Not "None" string


def _context(diagnostic: Diagnostic) -> dict[str, Any]:
    assert diagnostic.context is not None
    return diagnostic.context


class TestResolutionOrder:
    """Supplied → shell environment → settings.env → declared default → required? error : None."""

    IR: ClassVar[dict[str, Any]] = {"inputs": {"port": {"type": "integer", "description": "Port", "default": 8080}}}

    def test_a_default_satisfies_a_required_input(self):
        """``required`` defaults to true; a declared default is a value, not "missing"."""
        errors, updates, _ = prepare_inputs(self.IR, {})
        assert errors == []
        assert updates == {"port": 8080}

    def test_environment_beats_the_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("port", "9090")
        errors, updates, _ = prepare_inputs(self.IR, {})
        assert errors == []
        assert updates == {"port": 9090}

    def test_settings_beat_the_default(self):
        errors, updates, settings_names = prepare_inputs(self.IR, {}, {"port": "7070"})
        assert errors == []
        assert updates == {"port": 7070}
        assert settings_names == {"port"}

    def test_environment_beats_settings(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("port", "9090")
        _, updates, settings_names = prepare_inputs(self.IR, {}, {"port": "7070"})
        assert updates == {"port": 9090}
        assert settings_names == set()

    def test_a_settings_value_copied_into_the_environment_is_still_a_settings_name(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Startup copies settings.env into ``os.environ`` (``inject_settings_env_vars``); the copy is still a
        settings value, so it joins the always-redact names like one read from settings directly (#833)."""
        monkeypatch.setenv("port", "7070")
        monkeypatch.setattr(llm_config, "_settings_injected_env_vars", {"port"})
        _, updates, settings_names = prepare_inputs(self.IR, {}, {"port": "7070"})
        assert updates == {"port": 7070}
        assert settings_names == {"port"}

    def test_supplied_beats_environment(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("port", "9090")
        _, updates, _ = prepare_inputs(self.IR, {"port": "1"})
        assert updates == {"port": 1}

    def test_supplied_none_is_no_value_and_falls_back(self, monkeypatch: pytest.MonkeyPatch):
        _, updates, _ = prepare_inputs(self.IR, {"port": None})
        assert updates == {"port": 8080}
        monkeypatch.setenv("port", "9090")
        _, updates, _ = prepare_inputs(self.IR, {"port": None})
        assert updates == {"port": 9090}

    def test_supplied_none_for_a_required_input_with_nothing_else_is_missing(self):
        ir = {"inputs": {"q": {"type": "string", "description": "Query"}}}
        errors, _, _ = prepare_inputs(ir, {"q": None})
        assert [e.message for e in errors] == ["Workflow requires input 'q': Query"]

    def test_null_default_is_no_value(self):
        required = {"inputs": {"q": {"type": "string", "description": "Query", "default": None}}}
        assert [e.message for e in prepare_inputs(required, {})[0]] == ["Workflow requires input 'q': Query"]
        optional = {"inputs": {"q": {"type": "string", "required": False, "default": None}}}
        assert prepare_inputs(optional, {}) == ([], {"q": None}, set())


class TestEverySourceIsLabelled:
    """The error names where the bad value came from — the default pre-fill used to erase it."""

    IR: ClassVar[dict[str, Any]] = {"inputs": {"n": {"type": "integer", "default": "abc"}}}

    @pytest.mark.parametrize("source", ["argument", "stdin", "recorded", "call", "parent"])
    def test_supplied_values_carry_their_label(self, source):
        (error,) = prepare_inputs(self.IR, {"n": "x"}, input_sources={"n": source})[0]
        assert _context(error)["source"] == source
        assert _context(error)["path"] == "inputs.n"

    def test_unlabelled_supplied_value_is_an_argument(self):
        (error,) = prepare_inputs(self.IR, {"n": "x"})[0]
        assert _context(error)["source"] == "argument"

    def test_environment_value(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("n", "x")
        (error,) = prepare_inputs(self.IR, {})[0]
        assert _context(error)["source"] == "env"
        assert error.message.endswith("from the environment variable n.")

    def test_settings_value(self):
        (error,) = prepare_inputs(self.IR, {}, {"n": "x"})[0]
        assert _context(error)["source"] == "settings"

    def test_declared_default(self):
        (error,) = prepare_inputs(self.IR, {})[0]
        assert _context(error)["source"] == "default"
        assert _context(error)["path"] == "inputs.n.default"


class TestEachProblemIsItsOwnDiagnostic:
    IR: ClassVar[dict[str, Any]] = {
        "inputs": {
            "count": {"type": "integer", "required": True},
            "flag": {"type": "boolean", "required": True},
        },
        "nodes": [{"id": "show", "type": "shell", "params": {"command": "true"}}],
        "edges": [],
    }

    def test_two_bad_inputs_two_diagnostics_each_with_its_own_path_and_fix(self):
        errors, _, _ = prepare_inputs(self.IR, {"count": "abc", "flag": "maybe"})
        assert [_context(e)["path"] for e in errors] == ["inputs.count", "inputs.flag"]
        assert [e.suggestions for e in errors] == [
            ["Pass a whole number (e.g. 3): count=3"],
            ["Pass true or false (also yes/no, 1/0): flag=true"],
        ]

    def test_compile_raises_one_validation_error_carrying_both(self):
        with pytest.raises(WorkflowValidationError) as exc_info:
            compile_workflow(self.IR, Registry(), {"count": "abc", "flag": "maybe"})
        assert [_context(d)["input"] for d in exc_info.value.to_diagnostics()] == ["count", "flag"]

    def test_compile_types_supplied_values_in_place(self):
        params: dict[str, Any] = {"count": "3", "flag": "yes"}
        compiled = compile_workflow(self.IR, Registry(), params)
        assert params["count"] == 3
        assert params["flag"] is True
        assert compiled.resolved_defaults == {"count": 3, "flag": True}
