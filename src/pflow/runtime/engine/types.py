"""Type definitions for the execution engine.

These dataclasses represent the compiled workflow structure. They are built
at compile time and are immutable after compilation. Runtime data flows
through the shared store, not through these types.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from pflow.core.prompt_cache import CacheBlockIR


@dataclass
class TemplateConfig:
    """Per-node template configuration, built at compile time."""

    template_params: dict[str, Any]  # Params containing ${...} (raw template strings)
    static_params: dict[str, Any]  # Params without templates (already type-coerced)
    expected_types: dict[str, str]  # param_key -> declared type (from registry interface)
    resolution_mode: str  # "strict" or "permissive"
    optional_input_keys: set[str] = field(default_factory=set)  # For branch convergence


@dataclass
class BatchConfig:
    """Per-node batch configuration, built at compile time."""

    items_template: Any  # Template string "${node.list}" or inline list
    item_alias: str = "item"  # Variable name for current item
    error_handling: str = "fail_fast"  # "fail_fast" or "continue"
    parallel: bool = False
    max_concurrent: int = 10
    max_retries: int = 1
    retry_wait: float = 0.0


@dataclass
class LoopConfig:
    """Per-node loop configuration, built at compile time (issue #445).

    Drives engine re-entry: after the node runs, the engine evaluates ``while_template``
    against the node's fresh typed output. Truthy + under cap → re-run the same node
    (do-while); falsy → advance to the successor. Mutually exclusive with batch.
    """

    while_template: Optional[str] = None  # Condition source, raw "${node.output}" template string
    # Iteration cap. Either a pre-validated positive int (literal branch) OR a raw
    # "${template}" string resolved + validated at loop entry. None → MAX_NODE_VISITS.
    max_iterations: Optional[int] = None
    max_iterations_template: Optional[str] = None
    until_template: Optional[str] = None
    carry: dict[str, str] = field(default_factory=dict)


@dataclass
class NodeConfig:
    """Per-node metadata extracted at compile time. Immutable after compilation."""

    node_id: str
    node_type_name: str  # Actual node class name (e.g., "ShellNode")
    template_config: Optional[TemplateConfig]  # None if no templates in params
    batch_config: Optional[BatchConfig]  # None if not a batch node
    namespaced: bool  # Whether node outputs are namespaced
    interface_metadata: Optional[dict[str, Any]]  # Registry interface for type validation
    cache_enabled: bool = False  # Whether to use memoization cache. Default `False` because most node types side-effect or read external state; compiler sets `True` for `llm`.
    # Task 159: per-node prompt-cache subset (declaration order, frozen tuple).
    # Empty tuple = no opt-in (DD#19, byte-identical to absent).
    prompt_cache_items: tuple[str, ...] = ()
    prewarm: bool = False  # Task 159: per-node serialize-first-then-fan-out opt-in.
    loop_config: Optional["LoopConfig"] = None  # issue #445: None if not a loop node.
    approval: bool = False  # Task 125: pause for human approval before exec.


@dataclass
class CompiledWorkflow:
    """Structural compilation result. Reusable across sequential batch items
    within one execution. NOT safe for concurrent engine.run() calls
    (node.params is mutated during execution)."""

    start_node: Any  # First bare node (BaseNode/Node instance)
    node_configs: dict[str, NodeConfig]  # node_id -> config
    outputs: dict[str, Any] = field(default_factory=dict)  # IR outputs section
    resolved_defaults: dict[str, Any] = field(default_factory=dict)  # From prepare_inputs
    env_param_names: set[str] = field(default_factory=set)
    template_resolution_mode: str = "strict"
    # Task 159: workflow-level ## Cache IR. Frozen + tuple items so it is safe
    # to share across parallel sub-workflow invocations via _compiled_workflow_cache.
    cache_block: Optional[CacheBlockIR] = None
