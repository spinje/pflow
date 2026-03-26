"""Tests for _compute_node_config() and _compute_config_hash() on InstrumentedNodeWrapper.

These tests verify that the configuration hash used for workflow iteration cache
correctly captures all semantically relevant configuration (node type, static params,
template params, batch config) while excluding noise (e.g., _source_line metadata).
"""

from typing import Any

from pflow.pocketflow import Node
from pflow.runtime.wrappers.instrumented_wrapper import InstrumentedNodeWrapper
from pflow.runtime.wrappers.namespaced_wrapper import NamespacedNodeWrapper
from pflow.runtime.wrappers.template_wrapper import TemplateAwareNodeWrapper


class DummyNode(Node):
    """Minimal node for wrapper chain construction."""

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return shared

    def exec(self, prep_res: Any) -> str:
        return "ok"

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        return "default"


class PflowBatchNode:
    """Fake batch node with the correct class name for type-based detection.

    _find_batch_or_workflow_node() checks type(current).__name__ == "PflowBatchNode",
    so the class name itself is what matters, not inheritance.
    """

    def __init__(
        self,
        inner_node: Any,
        items_template: str,
        item_alias: str = "item",
        error_handling: str = "fail_fast",
        max_retries: int = 1,
        parallel: bool = False,
        max_concurrent: int = 4,
        retry_wait: float = 1.0,
    ):
        self.inner_node = inner_node
        self.items_template = items_template
        self.item_alias = item_alias
        self.error_handling = error_handling
        self.max_retries = max_retries
        # Operational fields -- should NOT appear in config hash
        self.parallel = parallel
        self.max_concurrent = max_concurrent
        self.retry_wait = retry_wait


# ---------------------------------------------------------------------------
# Helper: build wrapper chains
# ---------------------------------------------------------------------------


def _build_plain_wrapper(params: dict[str, Any] | None = None) -> InstrumentedNodeWrapper:
    """InstrumentedNodeWrapper around a bare DummyNode (no template/batch)."""
    node = DummyNode()
    if params:
        node.set_params(params)
    return InstrumentedNodeWrapper(node, "plain-node")


def _build_template_wrapper(
    params: dict[str, Any],
    node_id: str = "tpl-node",
) -> InstrumentedNodeWrapper:
    """InstrumentedNodeWrapper -> TemplateAwareNodeWrapper -> DummyNode."""
    node = DummyNode()
    tw = TemplateAwareNodeWrapper(node, node_id)
    tw.set_params(params)
    return InstrumentedNodeWrapper(tw, node_id)


def _build_batch_wrapper(
    params: dict[str, Any] | None = None,
    items_template: str = "${data.items}",
    item_alias: str = "item",
    error_handling: str = "fail_fast",
    max_retries: int = 1,
    parallel: bool = False,
    max_concurrent: int = 4,
    retry_wait: float = 1.0,
    node_id: str = "batch-node",
) -> InstrumentedNodeWrapper:
    """InstrumentedNodeWrapper -> PflowBatchNode -> NamespacedNodeWrapper -> TemplateAwareNodeWrapper -> DummyNode.

    Mirrors the real wrapper chain assembled by the compiler.
    """
    node = DummyNode()
    tw = TemplateAwareNodeWrapper(node, node_id)
    if params:
        tw.set_params(params)
    nw = NamespacedNodeWrapper(tw, node_id)
    bn = PflowBatchNode(
        nw,
        items_template=items_template,
        item_alias=item_alias,
        error_handling=error_handling,
        max_retries=max_retries,
        parallel=parallel,
        max_concurrent=max_concurrent,
        retry_wait=retry_wait,
    )
    return InstrumentedNodeWrapper(bn, node_id)


# ===========================================================================
# Tests
# ===========================================================================


class TestComputeNodeConfig:
    """Tests for _compute_node_config() output structure."""

    def test_template_params_included_in_config(self) -> None:
        """When a TemplateAwareNodeWrapper exists in the chain, its template_params
        dict should appear in the config under the 'template_params' key."""
        iw = _build_template_wrapper(
            params={"prompt": "${input.text}", "model": "gpt-4"},
        )

        config = iw._compute_node_config()

        # "prompt" contains a template -> template_params
        # "model" is static -> params on the inner node
        assert "template_params" in config
        assert config["template_params"] == {"prompt": "${input.text}"}
        # Static params should be in the regular params
        assert config["params"].get("model") == "gpt-4"

    def test_batch_semantic_config_included(self) -> None:
        """Batch items_template, item_alias, error_handling, and max_retries
        should all appear under config['batch']."""
        iw = _build_batch_wrapper(
            items_template="${results.urls}",
            item_alias="url",
            error_handling="continue",
            max_retries=3,
        )

        config = iw._compute_node_config()

        assert "batch" in config
        assert config["batch"] == {
            "items_template": "${results.urls}",
            "item_alias": "url",
            "error_handling": "continue",
            "max_retries": 3,
        }

    def test_source_line_keys_excluded(self) -> None:
        """Params ending with '_source_line' (markdown parser noise) should be
        filtered from the config so they don't affect the hash."""
        iw = _build_plain_wrapper(
            params={
                "command": "echo hello",
                "command_source_line": 42,
                "_source_line": 10,
                "file_path": "output.txt",
                "file_path_source_line": 43,
            },
        )

        config = iw._compute_node_config()

        param_keys = set(config["params"].keys())
        assert "command" in param_keys
        assert "file_path" in param_keys
        # All _source_line keys should be gone
        assert "command_source_line" not in param_keys
        assert "_source_line" not in param_keys
        assert "file_path_source_line" not in param_keys

    def test_batch_operational_config_excluded(self) -> None:
        """Operational batch settings (parallel, max_concurrent, retry_wait) must
        NOT appear in the config because they don't affect node output."""
        iw = _build_batch_wrapper(
            items_template="${data.items}",
            parallel=True,
            max_concurrent=8,
            retry_wait=2.5,
        )

        config = iw._compute_node_config()

        assert "batch" in config
        batch_keys = set(config["batch"].keys())
        # Only semantic keys should be present
        assert batch_keys == {"items_template", "item_alias", "error_handling", "max_retries"}
        # Operational keys must NOT leak into the config
        assert "parallel" not in batch_keys
        assert "max_concurrent" not in batch_keys
        assert "retry_wait" not in batch_keys

    def test_config_without_wrappers(self) -> None:
        """A basic node without template or batch wrappers should still produce
        a valid config with type and params."""
        iw = _build_plain_wrapper(params={"command": "ls -la"})

        config = iw._compute_node_config()

        assert config["type"] == "DummyNode"
        assert config["params"] == {"command": "ls -la"}
        # No template_params or batch keys when wrappers are absent
        assert "template_params" not in config
        assert "batch" not in config


class TestConfigHash:
    """Tests for _compute_config_hash() determinism and sensitivity."""

    def test_changing_template_param_changes_hash(self) -> None:
        """Two configs differing only in a template param value must produce
        different hashes -- this is the core cache invalidation signal."""
        iw_a = _build_template_wrapper(
            params={"prompt": "${input.text}", "model": "gpt-4"},
        )
        iw_b = _build_template_wrapper(
            params={"prompt": "${input.summary}", "model": "gpt-4"},
        )

        config_a = iw_a._compute_node_config()
        config_b = iw_b._compute_node_config()

        hash_a = iw_a._compute_config_hash(config_a)
        hash_b = iw_b._compute_config_hash(config_b)

        assert hash_a != hash_b, "Different template params must produce different hashes"

    def test_source_line_change_does_not_change_hash(self) -> None:
        """Changing _source_line values (line numbers shift when editing the
        .pflow.md file) must NOT change the hash, because node behavior is
        unchanged."""
        iw_before = _build_plain_wrapper(
            params={
                "command": "echo hello",
                "command_source_line": 10,
            },
        )
        iw_after = _build_plain_wrapper(
            params={
                "command": "echo hello",
                "command_source_line": 25,
            },
        )

        config_before = iw_before._compute_node_config()
        config_after = iw_after._compute_node_config()

        hash_before = iw_before._compute_config_hash(config_before)
        hash_after = iw_after._compute_config_hash(config_after)

        assert hash_before == hash_after, "_source_line metadata must be excluded from the hash"

    def test_hash_is_deterministic(self) -> None:
        """Calling _compute_config_hash twice on identical config produces the
        same result (no randomness)."""
        iw = _build_template_wrapper(
            params={"prompt": "${input.text}", "model": "gpt-4"},
        )

        config = iw._compute_node_config()

        assert iw._compute_config_hash(config) == iw._compute_config_hash(config)

    def test_changing_static_param_changes_hash(self) -> None:
        """Changing a static (non-template) parameter must also change the hash."""
        iw_a = _build_plain_wrapper(params={"command": "echo hello"})
        iw_b = _build_plain_wrapper(params={"command": "echo goodbye"})

        hash_a = iw_a._compute_config_hash(iw_a._compute_node_config())
        hash_b = iw_b._compute_config_hash(iw_b._compute_node_config())

        assert hash_a != hash_b

    def test_changing_batch_semantic_config_changes_hash(self) -> None:
        """Changing batch error_handling (semantic) must change the hash."""
        iw_a = _build_batch_wrapper(
            items_template="${data.items}",
            error_handling="fail_fast",
        )
        iw_b = _build_batch_wrapper(
            items_template="${data.items}",
            error_handling="continue",
        )

        hash_a = iw_a._compute_config_hash(iw_a._compute_node_config())
        hash_b = iw_b._compute_config_hash(iw_b._compute_node_config())

        assert hash_a != hash_b

    def test_changing_batch_operational_config_does_not_change_hash(self) -> None:
        """Changing parallel or max_concurrent (operational) must NOT change
        the hash since they don't affect the computed result."""
        iw_a = _build_batch_wrapper(
            items_template="${data.items}",
            parallel=False,
            max_concurrent=4,
        )
        iw_b = _build_batch_wrapper(
            items_template="${data.items}",
            parallel=True,
            max_concurrent=16,
        )

        hash_a = iw_a._compute_config_hash(iw_a._compute_node_config())
        hash_b = iw_b._compute_config_hash(iw_b._compute_node_config())

        assert hash_a == hash_b, "Operational batch config (parallel, max_concurrent) should be excluded from hash"
