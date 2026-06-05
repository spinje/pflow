"""Tests for top-level per-node retry IR schema."""

from __future__ import annotations

import pytest

from pflow.core import validate_ir
from pflow.core.exceptions import SchemaValidationError


def _workflow_with_retry(retry: dict[str, object]) -> dict[str, object]:
    return {
        "ir_version": "0.1.0",
        "nodes": [
            {
                "id": "step",
                "type": "shell",
                "params": {"command": "echo hi"},
                "retry": retry,
            }
        ],
    }


def test_retry_config_accepts_max_wait_and_backoff() -> None:
    validate_ir(_workflow_with_retry({"max": 3, "wait": 0.25, "backoff": "exponential"}))


@pytest.mark.parametrize("wait", [float("inf"), float("nan")])
def test_retry_wait_must_be_finite(wait: float) -> None:
    with pytest.raises(SchemaValidationError, match="finite"):
        validate_ir(_workflow_with_retry({"wait": wait}))


@pytest.mark.parametrize("max_attempts", [0, 11])
def test_retry_max_range_rejected(max_attempts: int) -> None:
    with pytest.raises(SchemaValidationError):
        validate_ir(_workflow_with_retry({"max": max_attempts}))


def test_retry_backoff_enum_rejected() -> None:
    with pytest.raises(SchemaValidationError):
        validate_ir(_workflow_with_retry({"backoff": "linear"}))


def test_retry_unknown_key_rejected() -> None:
    with pytest.raises(SchemaValidationError):
        validate_ir(_workflow_with_retry({"max": 2, "jitter": True}))
