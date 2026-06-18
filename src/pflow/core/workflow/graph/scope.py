"""Template-reference extraction helpers for graph construction."""

import re

# Extract refs from INSIDE ``${...}`` blocks only, so literal text (validator-rejected
# but defensively handled) never produces false positives.  Two-stage scan: find each
# ``${...}`` block, then within each block capture every ``root`` plus its full dotted
# tail (``.field.sub.deeper`` — zero or more segments).  Handles coalesce
# (``${a.x ?? b.y}`` — two refs per block) in any template context (bindings and
# output sources alike — ``??`` is a general-purpose template operator, not
# output-only).  Handles bare refs (``${data}`` — no field).  The ``(?<!\$)``
# lookbehind skips escaped templates (``$${x}`` resolves to literal ``${x}``).
_BRACE_BLOCK_RE = re.compile(r"(?<!\$)\$\{([^}]*)\}")
_REF_IN_BLOCK_RE = re.compile(r"(?:^|[\s?])([a-zA-Z0-9_-]+)((?:\.[a-zA-Z0-9_-]+)*)")


def refs_in(value: str) -> list[tuple[str, str | None]]:
    """Extract ``(root, field)`` pairs from every template ref in ``value``.

    Intentionally an alias of :func:`source_refs_in` — ``??`` is a general template
    operator, so binding refs and output-source refs extract identically. The two names
    are kept only for call-site readability (``refs_in`` at param bindings,
    ``source_refs_in`` at output ``source:`` expressions).
    """
    return source_refs_in(value)


def source_refs_in(source: str) -> list[tuple[str, str | None]]:
    """Extract ``(root, field)`` pairs from a template expression."""
    return [(root, field) for root, field, _ in refs_with_path_in(source)]


def refs_with_path_in(value: str) -> list[tuple[str, str | None, tuple[str, ...]]]:
    """Extract ``(root, first_segment, remaining_segments)`` per template ref.

    The path-preserving variant of :func:`refs_in`: ``${a.b.c.d}`` yields
    ``("a", "b", ("c", "d"))``; ``${a.b}`` yields ``("a", "b", ())``; a bare
    ``${a}`` yields ``("a", None, ())``. One shared walk implements all three
    extractors so they cannot drift.
    """
    from pflow.runtime.template_resolver import TemplateResolver

    refs: list[tuple[str, str | None, tuple[str, ...]]] = []
    for block in _BRACE_BLOCK_RE.finditer(value):
        # Split coalesce operands and skip JSON literals (Optional A) — a
        # literal like ${missing ?? "x"} must not surface "x" as a data-flow
        # ref (it would draw a spurious edge from a node coincidentally named x).
        for operand in TemplateResolver.split_coalesce_operands(block.group(1)):
            if TemplateResolver.is_literal_operand(operand.strip()):
                continue
            # Grammar gate: only operands the runtime can actually resolve count
            # as refs. Deliberately UNtrimmed — `${ a.x }` must fail (the runtime
            # never resolves it); coalesce operands arrive pre-stripped from
            # split_coalesce_operands. The pattern includes bracket segments, so
            # `${data[0].x}` passes (its root keeps an edge).
            if not re.fullmatch(TemplateResolver._VAR_NAME_PATTERN, operand):
                continue
            for m in _REF_IN_BLOCK_RE.finditer(operand):
                # Group 2 is the dotted tail (".b.c") or the EMPTY STRING on a
                # bare ref — map "" to (root, None, ()), never (root, "", ()).
                segments = m.group(2).lstrip(".").split(".") if m.group(2) else []
                refs.append((m.group(1), segments[0] if segments else None, tuple(segments[1:])))
    return refs
