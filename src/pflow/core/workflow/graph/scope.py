"""Template-reference extraction helpers for graph construction."""

from pflow.core.templates import Field, parse


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
    """``(root, first_field, remaining_fields)`` per Reference the runtime would resolve.

    ``${a.b.c.d}`` → ``("a", "b", ("c", "d"))``; a bare ``${a}`` → ``("a", None, ())``.
    Read from ``parse(value).references`` — the dependency view: literal operands,
    escapes and Issues yield nothing, and a dynamic index yields its outer reference
    AND its index source (``${a[${i}].x}`` → ``a``, then ``i``). Indices are not
    fields: ``${data[0].field}`` → ``("data", "field", ())``. One walk implements all
    three extractors so they cannot drift; ``web/src/graph/scan.ts`` mirrors it.
    """
    refs: list[tuple[str, str | None, tuple[str, ...]]] = []
    for ref in parse(value).references:
        fields = [seg.name for seg in ref.path if isinstance(seg, Field)]
        refs.append((ref.root, fields[0] if fields else None, tuple(fields[1:])))
    return refs
