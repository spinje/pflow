"""Reference resolution for mermaid generation.

Consolidates "given a ``${x.y}`` template ref, what mermaid ID does it resolve to?"
into a single primitive. Three resolution cases, exhaustive:

1. ``${item}`` / ``${item.field}`` — batch item source.
2. ``${node}`` / ``${node.field}`` — sibling node, optionally routed through an
   output in ``ctx.outgoing_routes``.
3. ``${input_name}`` / ``${input_name.field}`` — declared input at this scope.

``Scope`` holds a reference to the live ``MermaidContext`` — it does NOT
snapshot. Sibling ``outgoing_routes`` are populated incrementally during
``_render_workflow`` (as each node is rendered), so resolution must read ctx
state at call time.
"""

import re
from dataclasses import dataclass
from typing import Optional

from pflow.core.workflow.mermaid._context import (
    MermaidContext,
    _to_mermaid_id,
)

# Data-flow bindings: each template is one ref.  "${producer.response}" → (producer, response).
# Matches ``${root}`` (no field group) or ``${root.field}`` (field group captured).
# Deeper refs like ``${a.b.c}`` capture only the first field segment (a, b) — matches
# pre-consolidation semantics, which only used the root + first field.
_DATA_FLOW_REF_PATTERN = re.compile(r"\$\{([a-zA-Z0-9_-]+)(?:\.([a-zA-Z0-9_-]+))?")

# Output sources: extract refs from INSIDE ``${...}`` blocks only, so literal text
# (validator-rejected but defensively handled) never produces false positives.
# Two-stage scan: find each ``${...}`` block, then within each block capture every
# ``root`` (optionally ``.field``).  Handles coalesce (``${a.x ?? b.y}`` — two refs
# per block) and bare input refs (``${data}`` — no field).
_BRACE_BLOCK_RE = re.compile(r"\$\{([^}]*)\}")
_REF_IN_BLOCK_RE = re.compile(r"(?:^|[\s?])([a-zA-Z0-9_-]+)(?:\.([a-zA-Z0-9_-]+))?")


@dataclass
class Scope:
    """Per-level reference resolver over live :class:`MermaidContext` state.

    Attributes:
        ctx: Live context reference.  Scope reads ``sibling_node_ids``,
            ``outgoing_routes``, and ``has_expanded_outputs`` at resolve-time.
        input_ids: Name → mermaid ID for declared inputs at this scope.
            Top-level convention: ``input_{name}``.  Sub-workflow convention:
            ``{prefix}in_{name}``.  Build via :meth:`for_level` or pass directly.
        batch_source: Sibling node ID that produces the batch items list, or
            ``None`` if the current edge-generation pass is not inside a batch.
    """

    ctx: MermaidContext
    input_ids: dict[str, str]
    batch_source: Optional[str] = None

    def resolve(self, root: str, field: Optional[str]) -> Optional[str]:
        """Resolve a template ref root (and optional field) to a mermaid ID.

        Returns ``None`` when the root is not a recognized name in this scope,
        or when a recognized source intentionally suppresses its edge (batch
        item whose source has expanded outputs — the structural edge routes
        through the outputs instead).
        """
        # Batch item
        if root == "item":
            if not self.batch_source:
                return None
            src_mid = _to_mermaid_id(self.ctx.prefix + self.batch_source)
            if src_mid in self.ctx.has_expanded_outputs:
                return None
            return src_mid

        # Sibling node (with optional output-field routing)
        if root in self.ctx.sibling_node_ids:
            mermaid_id = _to_mermaid_id(self.ctx.prefix + root)
            out_dict = self.ctx.outgoing_routes.get(mermaid_id)
            if out_dict:
                if field and field in out_dict:
                    return out_dict[field]
                if len(out_dict) == 1:
                    return next(iter(out_dict.values()))
            return mermaid_id

        # Declared input at this scope
        if root in self.input_ids:
            return self.input_ids[root]

        return None

    @classmethod
    def for_level(cls, ctx: MermaidContext, batch_source: Optional[str] = None) -> "Scope":
        """Build a Scope for the current workflow level using the ID convention.

        - Top level (depth 0): inputs at ``input_{name}``.
        - Sub-workflow (depth > 0): inputs at ``{prefix}in_{name}``.
        """
        if ctx.current_depth == 0:
            input_ids = {name: _to_mermaid_id(f"input_{name}") for name in ctx.parent_inputs}
        else:
            input_ids = {name: _to_mermaid_id(f"{ctx.prefix}in_{name}") for name in ctx.parent_inputs}
        return cls(ctx=ctx, input_ids=input_ids, batch_source=batch_source)

    @staticmethod
    def refs_in(value: str) -> list[tuple[str, Optional[str]]]:
        """Extract ``(root, field)`` pairs from template refs in a binding.

        Use for data-flow bindings where each template expression is one ref
        (e.g. ``"${producer.response}"``).  Returns ``field=None`` for bare
        refs like ``"${data}"``.
        """
        return [(m.group(1), m.group(2)) for m in _DATA_FLOW_REF_PATTERN.finditer(value)]

    @staticmethod
    def source_refs_in(source: str) -> list[tuple[str, Optional[str]]]:
        """Extract ``(root, field)`` pairs from output source expressions.

        Two-stage: find each ``${...}`` block, then capture every ref inside
        it.  Handles coalesce (``${a.x ?? b.y}`` — two refs in one block) and
        bare refs (``${data}`` — no field).  Literal text outside ``${...}``
        never produces matches.
        """
        refs: list[tuple[str, Optional[str]]] = []
        for block in _BRACE_BLOCK_RE.finditer(source):
            for m in _REF_IN_BLOCK_RE.finditer(block.group(1)):
                refs.append((m.group(1), m.group(2)))
        return refs
