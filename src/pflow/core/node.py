"""Node lifecycle primitives for pflow workflows.

BaseNode + Node provide the lifecycle (prep -> exec -> post) and graph wiring (>> and -).
WorkflowEngine (in pflow.runtime.engine) handles graph traversal and all runtime
concerns (template resolution, batching, instrumentation, caching).

Originally derived from PocketFlow (github.com/The-Pocket/PocketFlow, MIT license).
Rewritten from scratch in Task 135 (Execution Core Redesign, 2026-03-31).
"""

import time
import warnings


class BaseNode:
    def __init__(self):
        self.params, self.successors = {}, {}

    def set_params(self, params):
        self.params = params

    def next(self, node, action="default"):
        if action in self.successors:
            warnings.warn(f"Overwriting successor for action '{action}'", stacklevel=2)
        self.successors[action] = node
        return node

    def prep(self, shared):
        pass

    def exec(self, prep_res):
        pass

    def post(self, shared, prep_res, exec_res):
        pass

    def _exec(self, prep_res):
        return self.exec(prep_res)

    def _run(self, shared):
        p = self.prep(shared)
        e = self._exec(p)
        return self.post(shared, p, e)

    def run(self, shared):
        if self.successors:
            warnings.warn("Node won't run successors. Use WorkflowEngine.", stacklevel=2)
        return self._run(shared)

    def __rshift__(self, other):
        return self.next(other)

    def __sub__(self, action):
        if isinstance(action, str):
            return _ConditionalTransition(self, action)
        raise TypeError("Action must be a string")


class _ConditionalTransition:
    def __init__(self, src, action):
        self.src, self.action = src, action

    def __rshift__(self, tgt):
        return self.src.next(tgt, self.action)


class Node(BaseNode):
    """BaseNode with retry. self.cur_retry is instance state and NOT thread-safe.

    Safe only because: (1) sequential batch does not parallelize,
    (2) parallel batch deep-copies the node per thread.
    """

    def __init__(self, max_retries=1, wait=0):
        super().__init__()
        self.max_retries, self.wait = max_retries, wait

    def exec_fallback(self, prep_res, exc):
        raise exc

    def _exec(self, prep_res):
        for self.cur_retry in range(self.max_retries):  # noqa: B020
            try:
                return self.exec(prep_res)
            except Exception as e:
                if self.cur_retry == self.max_retries - 1:
                    return self.exec_fallback(prep_res, e)
                if self.wait > 0:
                    time.sleep(self.wait)
