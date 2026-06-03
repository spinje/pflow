"""Integration tests for claude-code schema retry (Task #465).

Tests the end-to-end behavior of:
- Schema coercion + retry recovery
- Cost accounting across retries (synthetic item pattern)
- Trace event aggregation
- --report rendering with retry metadata
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pflow.core.trace_report import generate_report
from pflow.runtime import compile_workflow
from pflow.runtime.engine import WorkflowEngine
from tests.shared.registry_utils import ensure_test_registry


@pytest.fixture
def mock_claude_sdk():
    """Mock claude_agent_sdk to avoid subprocess calls."""
    with (
        patch("pflow.nodes.claude.claude_code.ClaudeAgentOptions") as mock_options,
        patch("pflow.nodes.claude.claude_code.run_agent") as mock_run,
    ):
        # Mock options class
        mock_options.return_value = MagicMock()

        # Default mock response: first call returns prose, second returns valid JSON
        def side_effect_prose_then_json(*args, **kwargs):
            """First call returns prose (soft-fail), second call returns valid JSON."""
            if not hasattr(side_effect_prose_then_json, "call_count"):
                side_effect_prose_then_json.call_count = 0
            side_effect_prose_then_json.call_count += 1

            if side_effect_prose_then_json.call_count == 1:
                # First call: prose only (no structured output)
                return {
                    "result_text": "Let me check that for you. The value is false.",
                    "structured_output": None,
                    "metadata": {
                        "usage": {
                            "input_tokens": 100,
                            "output_tokens": 50,
                            "cache_creation_input_tokens": 0,
                            "cache_read_input_tokens": 0,
                        },
                        "total_cost_usd": 0.001,
                        "duration_ms": 1000,
                        "num_turns": 1,
                        "session_id": "session-123",
                        "model": "claude-sonnet-4-5",
                    },
                }
            else:
                # Second call: valid JSON (retry succeeds)
                return {
                    "result_text": '{"continue": false}',
                    "structured_output": {"continue": False},
                    "metadata": {
                        "usage": {
                            "input_tokens": 80,
                            "output_tokens": 20,
                            "cache_creation_input_tokens": 0,
                            "cache_read_input_tokens": 50,
                        },
                        "total_cost_usd": 0.0005,
                        "duration_ms": 500,
                        "num_turns": 1,
                        "session_id": "session-123",
                        "model": "claude-sonnet-4-5",
                    },
                }

        mock_run.side_effect = side_effect_prose_then_json
        yield mock_run


def test_schema_retry_recovery(mock_claude_sdk, isolate_pflow_config):
    """Test that schema retry recovers from soft-fail and aggregates costs."""
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "check",
                "type": "claude-code",
                "params": {
                    "prompt": "Should we continue?",
                    "output_schema": {
                        "type": "object",
                        "properties": {"continue": {"type": "boolean"}},
                        "required": ["continue"],
                    },
                    "schema_retries": 1,
                },
            }
        ],
    }

    # Compile and run
    registry = ensure_test_registry()
    workflow = compile_workflow(ir, registry, workflow_path="test.pflow.md")
    shared = {}
    shared.update(workflow.resolved_defaults)
    engine = WorkflowEngine()
    engine.run(workflow, shared)

    # Assert successful recovery
    assert shared["check"]["result"] == {"continue": False}

    # Assert retry metadata
    assert "llm_usage" in shared["check"]
    llm_usage = shared["check"]["llm_usage"]
    assert "retries" in llm_usage
    assert len(llm_usage["retries"]) == 1

    # Assert cost aggregation (main + retry)
    # Main: 100 input, 50 output, $0.001
    # Retry: 80 input, 20 output, 50 cache_read, $0.0005
    # Total: 180 input, 70 output, 50 cache_read, $0.0015
    assert llm_usage["input_tokens"] == 180
    assert llm_usage["output_tokens"] == 70
    assert llm_usage["cache_read_input_tokens"] == 50
    assert llm_usage["cost_usd"] == 0.0015

    # Assert SDK was called twice (initial + retry)
    assert mock_claude_sdk.call_count == 2


def test_schema_retry_disabled(isolate_pflow_config):
    """Test that schema_retries=0 disables retry (byte-for-byte preservation)."""
    with (
        patch("pflow.nodes.claude.claude_code.ClaudeAgentOptions") as mock_options,
        patch("pflow.nodes.claude.claude_code.run_agent") as mock_run,
    ):
        mock_options.return_value = MagicMock()

        # Mock response: prose only (no structured output)
        mock_run.return_value = {
            "result_text": "Let me check that for you. The value is false.",
            "structured_output": None,
            "metadata": {
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
                "total_cost_usd": 0.001,
                "duration_ms": 1000,
                "num_turns": 1,
                "session_id": "session-123",
                "model": "claude-sonnet-4-5",
            },
        }

        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "check",
                    "type": "claude-code",
                    "params": {
                        "prompt": "Should we continue?",
                        "output_schema": {
                            "type": "object",
                            "properties": {"continue": {"type": "boolean"}},
                            "required": ["continue"],
                        },
                        "schema_retries": 0,  # Disable retry
                    },
                }
            ],
        }

        registry = ensure_test_registry()
        workflow = compile_workflow(ir, registry, workflow_path="test.pflow.md")
        shared = {}
        shared.update(workflow.resolved_defaults)
        engine = WorkflowEngine()
        engine.run(workflow, shared)

        # Assert soft-fail: raw text stored, warning present
        assert shared["check"]["result"] == "Let me check that for you. The value is false."
        assert "_schema_error" in shared["check"]
        assert shared["__warnings__"]  # DEGRADED status via warnings

        # Assert no retry
        assert mock_run.call_count == 1
        llm_usage = shared["check"]["llm_usage"]
        assert "retries" not in llm_usage or len(llm_usage.get("retries", [])) == 0


def test_schema_retry_exhausted(isolate_pflow_config):
    """Test that retry exhaustion preserves soft-fail behavior."""
    with (
        patch("pflow.nodes.claude.claude_code.ClaudeAgentOptions") as mock_options,
        patch("pflow.nodes.claude.claude_code.run_agent") as mock_run,
    ):
        mock_options.return_value = MagicMock()

        # Mock response: always prose (retry never succeeds)
        def always_prose(*args, **kwargs):
            """Always return prose (no structured output)."""
            if not hasattr(always_prose, "call_count"):
                always_prose.call_count = 0
            always_prose.call_count += 1

            return {
                "result_text": f"Prose response {always_prose.call_count}",
                "structured_output": None,
                "metadata": {
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                    "total_cost_usd": 0.001,
                    "duration_ms": 1000,
                    "num_turns": 1,
                    "session_id": "session-123",
                    "model": "claude-sonnet-4-5",
                },
            }

        mock_run.side_effect = always_prose

        ir = {
            "ir_version": "0.1.0",
            "nodes": [
                {
                    "id": "check",
                    "type": "claude-code",
                    "params": {
                        "prompt": "Should we continue?",
                        "output_schema": {
                            "type": "object",
                            "properties": {"continue": {"type": "boolean"}},
                            "required": ["continue"],
                        },
                        "schema_retries": 1,
                    },
                }
            ],
        }

        registry = ensure_test_registry()
        workflow = compile_workflow(ir, registry, workflow_path="test.pflow.md")
        shared = {}
        shared.update(workflow.resolved_defaults)
        engine = WorkflowEngine()
        engine.run(workflow, shared)

        # Assert soft-fail after retries exhausted
        assert shared["check"]["result"] == "Prose response 2"  # Last retry result
        assert "_schema_error" in shared["check"]
        assert shared["__warnings__"]  # DEGRADED status via warnings

        # Assert retry was attempted
        assert mock_run.call_count == 2  # Initial + 1 retry
        llm_usage = shared["check"]["llm_usage"]
        assert "retries" in llm_usage
        assert len(llm_usage["retries"]) == 1


@pytest.mark.trace_files
def test_trace_report_retry_rendering(mock_claude_sdk, isolate_pflow_config, tmp_path):
    """Test that --report rendering includes retry metadata."""
    ir = {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "check",
                "type": "claude-code",
                "params": {
                    "prompt": "Should we continue?",
                    "output_schema": {
                        "type": "object",
                        "properties": {"continue": {"type": "boolean"}},
                        "required": ["continue"],
                    },
                    "schema_retries": 1,
                },
            }
        ],
    }

    # Compile and run with trace collection
    registry = ensure_test_registry()
    workflow = compile_workflow(ir, registry, workflow_path="test.pflow.md")
    shared = {}
    shared.update(workflow.resolved_defaults)

    from pflow.runtime.workflow_trace import WorkflowTraceCollector

    trace = WorkflowTraceCollector(
        workflow_name="test",
        workflow_path="test.pflow.md",
        start_time="2024-01-01T00:00:00Z",
    )
    shared["__trace_collector__"] = trace

    engine = WorkflowEngine(trace=trace)
    engine.run(workflow, shared)

    # Save trace to file
    trace_file = tmp_path / "trace.json"
    trace.save_to_file(str(trace_file))

    # Generate report
    report_dir = tmp_path / "report"
    generated_report_dir = generate_report(str(trace_file), str(report_dir))
    assert generated_report_dir is not None

    # Check node report file includes retry metadata
    node_report = Path(report_dir) / "01-check.md"
    assert node_report.exists()
    content = node_report.read_text()

    # Assert retry metadata is rendered
    assert "Schema retries: 1" in content

    # Assert aggregated tokens are shown (100+80 = 180 input, 50+20 = 70 output)
    assert "180" in content or "Tokens: 180 / 70" in content
