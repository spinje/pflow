"""Node lifecycle primitives for pflow workflows.

BaseNode + Node provide the lifecycle (prep -> exec -> post) and graph wiring (>> and -).
WorkflowEngine (in pflow.runtime.engine) handles graph traversal and all runtime
concerns (template resolution, batching, instrumentation, caching).

Originally derived from PocketFlow (github.com/The-Pocket/PocketFlow, MIT license).
Rewritten from scratch in Task 135 (Execution Core Redesign, 2026-03-31).
"""

import time
import warnings
from typing import Any

_MAX_RETRY_BACKOFF_SECONDS: float = 60.0


class BaseNode:
    def __init__(self) -> None:
        self.params: dict[str, Any] = {}
        self.successors: dict[str, BaseNode] = {}

    def set_params(self, params: dict[str, Any]) -> None:
        self.params = params

    def next(self, node: "BaseNode", action: str = "default") -> "BaseNode":
        if action in self.successors:
            warnings.warn(f"Overwriting successor for action '{action}'", stacklevel=2)
        self.successors[action] = node
        return node

    def prep(self, shared: dict[str, Any]) -> Any:
        pass

    def exec(self, prep_res: Any) -> Any:
        pass

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str | None:
        pass

    def _exec(self, prep_res: Any) -> Any:
        return self.exec(prep_res)

    def _run(self, shared: dict[str, Any]) -> str | None:
        p = self.prep(shared)
        e = self._exec(p)
        return self.post(shared, p, e)

    def run(self, shared: dict[str, Any]) -> str | None:
        if self.successors:
            warnings.warn("Node won't run successors. Use WorkflowEngine.", stacklevel=2)
        return self._run(shared)

    def __rshift__(self, other: "BaseNode") -> "BaseNode":
        return self.next(other)

    def __sub__(self, action: str) -> "_ConditionalTransition":
        if isinstance(action, str):
            return _ConditionalTransition(self, action)
        raise TypeError("Action must be a string")


class _ConditionalTransition:
    def __init__(self, src: BaseNode, action: str) -> None:
        self.src, self.action = src, action

    def __rshift__(self, tgt: BaseNode) -> BaseNode:
        return self.src.next(tgt, self.action)


class Node(BaseNode):
    """BaseNode with retry. self.cur_retry is instance state and NOT thread-safe.

    Safe only because: (1) sequential batch does not parallelize,
    (2) parallel batch deep-copies the node per thread.
    """

    def __init__(self, max_retries: int = 1, wait: float = 0, backoff: str = "fixed") -> None:
        super().__init__()
        self.max_retries: int = max_retries
        self.wait: float = wait
        self.backoff: str = backoff

    def exec_fallback(self, prep_res: Any, exc: Exception) -> Any:
        raise exc

    def _retry_delay(self) -> float:
        wait = float(self.wait)
        if self.backoff == "exponential":
            retry_index = int(getattr(self, "cur_retry", 0))
            delay: float = wait * (2**retry_index)
            return min(delay, _MAX_RETRY_BACKOFF_SECONDS)
        return wait

    def _exec(self, prep_res: Any) -> Any:
        for self.cur_retry in range(self.max_retries):  # noqa: B020
            try:
                return self.exec(prep_res)
            except Exception as e:
                if not getattr(e, "retriable", True) or self.cur_retry == self.max_retries - 1:
                    return self.exec_fallback(prep_res, e)
                delay = self._retry_delay()
                if delay > 0:
                    time.sleep(delay)
