"""Classify template refs in prompt bodies with optional ``params.inputs`` dealiasing.

The analyzer and runtime both need to answer: given an LLM prompt body, where
is the first per-item batch reference, and what path does each ``${...}`` ref
point to after dealiasing through the node's ``- inputs:`` mapping?

This module is the single source of truth for that classification. Dealiasing
is intentionally one level deep: ``inputs`` values resolve against the runtime
shared store, not against other ``inputs`` entries.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pflow.runtime.template_resolver import TemplateResolver


@dataclass(frozen=True)
class PromptRef:
    """A single ``${...}`` occurrence in a prompt body, classified.

    ``position`` is the byte offset of the leading ``$`` in the original
    prompt string. ``end`` is the byte offset immediately after the closing
    ``}``, matching ``re.Match.end()`` semantics.

    ``raw_expr`` is the original inner expression without the surrounding
    ``${...}`` delimiters. It is intentionally not dealiased, so diagnostics
    can report the expression the workflow author actually wrote.

    ``operand_paths`` carries the dealiased path text for each coalesce
    operand. ``is_per_item`` is true iff any operand path starts with the
    batch alias. With ``batch_alias`` unset, ``is_per_item`` is always false.
    """

    position: int
    end: int
    raw_expr: str
    operand_paths: tuple[str, ...]
    is_per_item: bool


def classify_prompt_refs(
    prompt: str,
    batch_alias: str | None,
    node_inputs: Mapping[str, Any] | None,
) -> tuple[PromptRef, ...]:
    """Walk every ``${...}`` ref in ``prompt`` and return classified refs.

    ``is_per_item`` is true when any dealiased operand path begins with
    ``batch_alias.``, ``batch_alias[``, or equals ``batch_alias``. With
    ``batch_alias`` unset or empty, it is always false.
    """
    if not isinstance(prompt, str) or not prompt:
        return ()

    inputs: Mapping[str, Any] = node_inputs if isinstance(node_inputs, Mapping) else {}
    refs: list[PromptRef] = []
    for match in TemplateResolver.TEMPLATE_PATTERN.finditer(prompt):
        raw_expr = match.group(1)
        operands = TemplateResolver.split_coalesce_operands(raw_expr)
        # Literal operands (Optional A) are values, not refs — skip dealiasing.
        paths = tuple(
            path
            for operand in operands
            if not TemplateResolver.is_literal_operand(operand)
            for path in _dealias_operand(operand, inputs)
        )
        per_item = False
        if batch_alias:
            per_item = any(_starts_with_alias(path, batch_alias) for path in paths)
        refs.append(
            PromptRef(
                position=match.start(),
                end=match.end(),
                raw_expr=raw_expr,
                operand_paths=paths,
                is_per_item=per_item,
            )
        )
    return tuple(refs)


def first_per_item_position(
    prompt: str,
    batch_alias: str | None,
    node_inputs: Mapping[str, Any] | None,
) -> int | None:
    """Return the byte offset of the first per-item ref, or ``None``."""
    for ref in classify_prompt_refs(prompt, batch_alias, node_inputs):
        if ref.is_per_item:
            return ref.position
    return None


def _dealias_operand(operand: str, inputs: Mapping[str, Any]) -> tuple[str, ...]:
    """Replace an operand head with its single-template ``inputs`` mapping."""
    head, sep, rest = _split_head(operand)
    chain = sep + rest if sep else ""
    mapped = inputs.get(head)
    if not isinstance(mapped, str):
        # Dict/list-valued inputs can still resolve at runtime through the
        # remaining path chain. The classifier only dealiases simple template
        # strings, so preserve the author-written operand here.
        return (operand,)
    inner = _extract_template_inner(mapped)
    if inner is None:
        return (operand,)
    # Literal operands (Optional A) inside the aliased template are values,
    # not refs — drop them so they don't become bogus dealiased paths.
    return tuple(
        inner_operand + chain
        for inner_operand in TemplateResolver.split_coalesce_operands(inner)
        if not TemplateResolver.is_literal_operand(inner_operand)
    )


def _split_head(operand: str) -> tuple[str, str, str]:
    """Split an operand path into ``(head, separator, rest)``."""
    for index, char in enumerate(operand):
        if char == ".":
            return operand[:index], char, operand[index + 1 :]
        if char == "[":
            return operand[:index], char, operand[index + 1 :]
    return operand, "", ""


def _extract_template_inner(value: str) -> str | None:
    """Return the inner expression for a single strict ``"${...}"`` value."""
    stripped = value.strip()
    match = TemplateResolver.SIMPLE_TEMPLATE_PATTERN.match(stripped)
    if match is None:
        return None
    return match.group(1).strip()


def _starts_with_alias(path: str, alias: str) -> bool:
    return path == alias or path.startswith(f"{alias}.") or path.startswith(f"{alias}[")
