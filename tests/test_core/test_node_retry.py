"""Tests for core node retry semantics."""

from unittest.mock import patch

from pflow.core.exceptions import LLMTransientError
from pflow.core.node import Node


class _AlwaysFailNode(Node):
    def __init__(self, exc: Exception, *, max_retries: int = 3, wait: float = 0.0, backoff: str = "fixed") -> None:
        super().__init__(max_retries=max_retries, wait=wait, backoff=backoff)
        self.exc = exc
        self.attempts = 0
        self.fallback_exc: Exception | None = None

    def exec(self, prep_res: object) -> object:
        self.attempts += 1
        raise self.exc

    def exec_fallback(self, prep_res: object, exc: Exception) -> str:
        self.fallback_exc = exc
        return "fallback"


class _DeterministicError(Exception):
    retriable = False


def test_plain_exception_retries_to_max_retries() -> None:
    exc = Exception("temporary")
    node = _AlwaysFailNode(exc, max_retries=3, wait=0)

    assert node._exec(None) == "fallback"

    assert node.attempts == 3
    assert node.fallback_exc is exc


def test_llm_transient_error_retries_to_max_retries() -> None:
    exc = LLMTransientError("rate limit", model="openai/gpt-4o-mini", kind="rate_limit")
    node = _AlwaysFailNode(exc, max_retries=3, wait=0)

    assert node._exec(None) == "fallback"

    assert node.attempts == 3
    assert node.fallback_exc is exc


def test_retriable_false_short_circuits_without_sleeping() -> None:
    exc = _DeterministicError("bad config")
    node = _AlwaysFailNode(exc, max_retries=3, wait=10)

    with patch("pflow.core.node.time.sleep") as sleep:
        assert node._exec(None) == "fallback"

    assert node.attempts == 1
    assert node.fallback_exc is exc
    sleep.assert_not_called()


def test_retry_delay_fixed_backoff_returns_wait() -> None:
    node = _AlwaysFailNode(Exception("temporary"), wait=2.5, backoff="fixed")
    node.cur_retry = 3

    assert node._retry_delay() == 2.5


def test_retry_delay_exponential_backoff_uses_current_retry() -> None:
    node = _AlwaysFailNode(Exception("temporary"), wait=0.5, backoff="exponential")
    node.cur_retry = 3

    assert node._retry_delay() == 4.0


def test_retry_delay_exponential_backoff_clamps_at_sixty_seconds() -> None:
    node = _AlwaysFailNode(Exception("temporary"), wait=10.0, backoff="exponential")
    node.cur_retry = 10

    assert node._retry_delay() == 60.0


def test_exponential_backoff_sleeps_between_attempts_only() -> None:
    exc = Exception("temporary")
    node = _AlwaysFailNode(exc, max_retries=3, wait=0.5, backoff="exponential")

    with patch("pflow.core.node.time.sleep") as sleep:
        assert node._exec(None) == "fallback"

    assert node.attempts == 3
    assert node.fallback_exc is exc
    assert [call.args[0] for call in sleep.call_args_list] == [0.5, 1.0]


def test_final_attempt_does_not_sleep() -> None:
    exc = Exception("temporary")
    node = _AlwaysFailNode(exc, max_retries=1, wait=10)

    with patch("pflow.core.node.time.sleep") as sleep:
        assert node._exec(None) == "fallback"

    assert node.attempts == 1
    sleep.assert_not_called()
