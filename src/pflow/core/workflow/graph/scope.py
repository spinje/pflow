"""Template-reference extraction helpers for graph construction."""

import re
from typing import Optional

# Extract refs from INSIDE ``${...}`` blocks only, so literal text (validator-rejected
# but defensively handled) never produces false positives.  Two-stage scan: find each
# ``${...}`` block, then within each block capture every ``root`` (optionally
# ``.field``).  Handles coalesce (``${a.x ?? b.y}`` — two refs per block) in any
# template context (bindings and output sources alike — ``??`` is a general-purpose
# template operator, not output-only).  Handles bare refs (``${data}`` — no field).
_BRACE_BLOCK_RE = re.compile(r"\$\{([^}]*)\}")
_REF_IN_BLOCK_RE = re.compile(r"(?:^|[\s?])([a-zA-Z0-9_-]+)(?:\.([a-zA-Z0-9_-]+))?")


def refs_in(value: str) -> list[tuple[str, Optional[str]]]:
    """Extract ``(root, field)`` pairs from every template ref in ``value``."""
    return source_refs_in(value)


def source_refs_in(source: str) -> list[tuple[str, Optional[str]]]:
    """Extract ``(root, field)`` pairs from a template expression."""
    from pflow.runtime.template_resolver import TemplateResolver

    refs: list[tuple[str, Optional[str]]] = []
    for block in _BRACE_BLOCK_RE.finditer(source):
        # Split coalesce operands and skip JSON literals (Optional A) — a
        # literal like ${missing ?? "x"} must not surface "x" as a data-flow
        # ref (it would draw a spurious edge from a node coincidentally named x).
        for operand in TemplateResolver.split_coalesce_operands(block.group(1)):
            if TemplateResolver.is_literal_operand(operand.strip()):
                continue
            for m in _REF_IN_BLOCK_RE.finditer(operand):
                refs.append((m.group(1), m.group(2)))
    return refs
