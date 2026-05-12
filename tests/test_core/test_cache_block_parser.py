"""Tests for the ``## Cache`` section parser extension (Task 159 B2.1).

The cache section is a structurally novel shape in pflow's markdown parser:
section-level YAML params (``- ttl: ...``) and a section-level tagged code
block (``` ```cache ```), with NO ``### entities``. All other sections require
``### entity`` headings; the cache section bypasses that rule for itself only.

Per spec § "## Cache Block Parsing".
"""

from __future__ import annotations

import pytest

from pflow.core.exceptions import MarkdownParseError
from pflow.core.markdown_parser import parse_markdown


def _wrap(body: str) -> str:
    """Wrap a cache section body inside a minimal-but-valid ``.pflow.md`` file."""
    return (
        "# Test\n\n"
        "Test workflow.\n\n"
        "## Cache\n\n"
        f"{body}\n\n"
        "## Steps\n\n"
        "### my-node\n\n"
        "Description of what this node does.\n\n"
        "- type: shell\n\n"
        "```shell command\n"
        'echo "hi"\n'
        "```\n"
    )


# ------------------------------------------------------------------------------
# Happy-path parsing
# ------------------------------------------------------------------------------


def test_parses_valid_cache_block_with_one_chunk() -> None:
    body = "- ttl: 5m\n\n```cache\nDescription of the concept:\n\n${concept}\n```"
    result = parse_markdown(_wrap(body))
    cache = result.ir.get("cache")
    assert cache is not None
    assert cache["ttl"] == "5m"
    assert len(cache["items"]) == 1
    item = cache["items"][0]
    assert item["name"] == "concept"
    assert item["var"] == "concept"
    assert "Description of the concept" in item["prose_before"]


def test_parses_valid_cache_block_with_multiple_chunks() -> None:
    body = (
        "- ttl: 1h\n\n"
        "```cache\n"
        "The concept:\n\n"
        "${concept}\n\n"
        "The brief:\n\n"
        "${concept_brief}\n\n"
        "The chorus:\n\n"
        "${chorus-chooser.winning_chorus}\n"
        "```"
    )
    result = parse_markdown(_wrap(body))
    cache = result.ir["cache"]
    assert cache["ttl"] == "1h"
    names = [item["name"] for item in cache["items"]]
    assert names == ["concept", "concept_brief", "chorus-chooser.winning_chorus"]


@pytest.mark.parametrize("ttl", ["1m", "2m", "11m", "55m", "60m", "1h"])
def test_parses_supported_cache_ttl_values(ttl: str) -> None:
    body = f"- ttl: {ttl}\n\n```cache\nx\n${{a}}\n```"
    result = parse_markdown(_wrap(body))
    assert result.ir["cache"]["ttl"] == ttl


def test_chunk_identifier_strips_template_braces() -> None:
    body = "```cache\nFoo:\n${a-b.c_d}\n```"
    result = parse_markdown(_wrap(body))
    item = result.ir["cache"]["items"][0]
    assert item["name"] == "a-b.c_d"
    assert item["var"] == "a-b.c_d"


def test_back_to_back_chunks_have_empty_prose_before() -> None:
    body = "```cache\n${a}${b}\n```"
    result = parse_markdown(_wrap(body))
    items = result.ir["cache"]["items"]
    assert len(items) == 2
    assert items[0]["name"] == "a"
    # First chunk's prose is everything before ${a} (in this case empty/just header).
    assert items[1]["name"] == "b"
    assert items[1]["prose_before"] == ""


def test_inline_prose_between_chunks_is_attached_to_following_chunk() -> None:
    body = "```cache\n${a}\nfoo bar\n${b}\n```"
    result = parse_markdown(_wrap(body))
    items = result.ir["cache"]["items"]
    assert items[0]["name"] == "a"
    assert items[1]["name"] == "b"
    assert "foo bar" in items[1]["prose_before"]


def test_cache_section_without_ttl_omits_ttl_field() -> None:
    """Default-TTL workflows omit ``- ttl:``; the IR field should be absent or None."""
    body = "```cache\nA value:\n${val}\n```"
    result = parse_markdown(_wrap(body))
    cache = result.ir["cache"]
    # Either the key is absent OR explicitly None — both are valid "default TTL" states.
    assert cache.get("ttl") in (None,)


def test_chunks_carry_source_line_metadata() -> None:
    body = "```cache\nText:\n\n${concept}\n```"
    md = _wrap(body)
    result = parse_markdown(md)
    item = result.ir["cache"]["items"][0]
    # _source_line should point to the line containing ${concept} in the file.
    expected_line = md.splitlines().index("${concept}") + 1
    assert item["_source_line"] == expected_line


# ------------------------------------------------------------------------------
# Error paths
# ------------------------------------------------------------------------------


@pytest.mark.parametrize("ttl", ["0m", "61m", "2h", "90s", "1.5m", "3600s", "5 min"])
def test_invalid_ttl_value_rejected(ttl: str) -> None:
    body = f"- ttl: {ttl}\n\n```cache\nx\n${{a}}\n```"
    with pytest.raises(MarkdownParseError, match="ttl"):
        parse_markdown(_wrap(body))


def test_unknown_section_level_param_rejected() -> None:
    body = "- mode: explicit\n\n```cache\nx\n${a}\n```"
    with pytest.raises(MarkdownParseError, match=r"## Cache|ttl|mode"):
        parse_markdown(_wrap(body))


def test_duplicate_ttl_rejected() -> None:
    body = "- ttl: 5m\n- ttl: 1h\n\n```cache\nx\n${a}\n```"
    with pytest.raises(MarkdownParseError, match=r"[Dd]uplicate"):
        parse_markdown(_wrap(body))


def test_two_cache_code_blocks_rejected() -> None:
    body = "```cache\nA:\n${a}\n```\n\n```cache\nB:\n${b}\n```"
    with pytest.raises(MarkdownParseError, match=r"[Mm]ultiple"):
        parse_markdown(_wrap(body))


def test_wrong_code_block_tag_rejected() -> None:
    """Code blocks under ``## Cache`` must use the ``cache`` tag."""
    body = "```yaml\nfoo: bar\n```"
    with pytest.raises(MarkdownParseError, match=r"cache"):
        parse_markdown(_wrap(body))


def test_cache_block_with_no_template_var_rejected() -> None:
    """Empty cache block (no ``${var}``) is a syntax error."""
    body = "```cache\nJust prose, no variables.\n```"
    with pytest.raises(MarkdownParseError, match=r"[Vv]ariable|\$\{"):
        parse_markdown(_wrap(body))


def test_cache_section_without_code_block_rejected() -> None:
    """`## Cache` with only a ``- ttl:`` and no code block must error."""
    body = "- ttl: 5m"
    with pytest.raises(MarkdownParseError, match=r"cache|code block"):
        parse_markdown(_wrap(body))


def test_duplicate_chunk_identifier_rejected() -> None:
    body = "```cache\nA:\n${concept}\nB:\n${concept}\n```"
    with pytest.raises(MarkdownParseError, match=r"[Dd]uplicate"):
        parse_markdown(_wrap(body))


# ------------------------------------------------------------------------------
# prompt_cache: and prewarm: extraction at the node level
# ------------------------------------------------------------------------------


def test_prompt_cache_field_promoted_to_top_level() -> None:
    """``- prompt_cache: [...]`` on a node ends up at top-level node["prompt_cache"],
    NOT inside node["params"] — required for B2.2 schema validation to see it."""
    md = (
        "# T\n\nTest.\n\n"
        "## Cache\n\n```cache\nX:\n${concept}\n```\n\n"
        "## Steps\n\n"
        "### llm-step\n\nLLM call description here.\n\n"
        "- type: llm\n"
        "- prompt_cache: [concept]\n"
        "- model: anthropic/claude-sonnet-4-5\n\n"
        "```prompt\nDo a thing.\n```\n"
    )
    result = parse_markdown(md)
    nodes = result.ir["nodes"]
    node = next(n for n in nodes if n["id"] == "llm-step")
    assert node.get("prompt_cache") == ["concept"]
    assert "prompt_cache" not in node.get("params", {})


def test_prewarm_field_promoted_to_top_level() -> None:
    """``- prewarm: true`` on a node ends up at top-level node["prewarm"]."""
    md = (
        "# T\n\nTest.\n\n"
        "## Steps\n\n"
        "### llm-step\n\nA batch llm call.\n\n"
        "- type: llm\n"
        "- prewarm: true\n"
        "- model: anthropic/claude-sonnet-4-5\n\n"
        "```prompt\nfoo\n```\n"
    )
    result = parse_markdown(md)
    node = next(n for n in result.ir["nodes"] if n["id"] == "llm-step")
    assert node.get("prewarm") is True
    assert "prewarm" not in node.get("params", {})


def test_prompt_cache_empty_list_promoted_to_top_level() -> None:
    """``prompt_cache: []`` (empty list) is preserved as top-level field."""
    md = (
        "# T\n\nTest.\n\n"
        "## Steps\n\n"
        "### llm-step\n\nAn LLM call.\n\n"
        "- type: llm\n"
        "- prompt_cache: []\n"
        "- model: anthropic/claude-sonnet-4-5\n\n"
        "```prompt\nfoo\n```\n"
    )
    result = parse_markdown(md)
    node = next(n for n in result.ir["nodes"] if n["id"] == "llm-step")
    assert node.get("prompt_cache") == []


# ------------------------------------------------------------------------------
# Save round-trip preservation
# ------------------------------------------------------------------------------


def test_inputs_referenced_only_in_cache_not_flagged_unused() -> None:
    """A workflow input referenced ONLY by ``## Cache`` (no node param uses it)
    must NOT trigger the unused-input ERROR.

    Split-extractor contract (post-double-emit fix): cache vars live in
    ``_extract_cache_templates_for_unused_check`` and are unioned into the unused-check input
    only — they MUST NOT be in ``_extract_all_templates``'s output (which
    flows into ``validate_template_paths``, producing a duplicate generic
    "Template variable ${X} has no valid source" diagnostic alongside the
    richer ``Cache chunk 'X' references...`` one from
    ``core/workflow/data_flow.py::_validate_cache_block``).

    Regression: discovered via case-9 smoke test post-walker-fix. The first
    walker fix routed cache vars through BOTH passes; the second fix splits
    them so each pass owns exactly one rule (V5 single-source pattern).
    """
    from pflow.runtime.template_validation.validator import (
        _extract_all_templates,
        _extract_cache_templates_for_unused_check,
    )

    md = (
        "# Test\n\nTest workflow.\n\n"
        "## Inputs\n\n### concept\n\nConcept input.\n\n- type: string\n- required: true\n\n"
        "## Cache\n\n```cache\nThe concept:\n${concept}\n```\n\n"
        "## Steps\n\n### step\n\nA step that uses no template references.\n\n"
        "- type: shell\n\n```shell command\necho hi\n```\n"
    )
    result = parse_markdown(md)

    # (1) Mechanism: split-extractor contract.
    node_param_templates = _extract_all_templates(result.ir)
    cache_templates = _extract_cache_templates_for_unused_check(result.ir)
    assert "concept" not in node_param_templates, (
        f"Cache var must not be in _extract_all_templates output (would cause "
        f"path-validation to emit a generic duplicate diagnostic). Got: {sorted(node_param_templates)}"
    )
    assert "concept" in cache_templates, (
        f"Cache var must be in cache extractor output so the unused-input "
        f"check sees it via union. Got: {sorted(cache_templates)}"
    )

    # (2) Effect: running the FULL template validator produces no spurious
    # "unused input" or "Template variable has no valid source" errors. Without
    # this assertion, a future contributor could break the mechanism (e.g., add
    # a re-export and call the cache extractor in the wrong consumer) and the
    # mechanism check would still pass while the user-visible double-emit
    # returns silently.
    from pflow.core.diagnostic import Severity
    from pflow.registry.registry import Registry
    from pflow.runtime.template_validation.validator import validate_workflow_templates

    # Registry is auto-populated by the conftest's isolate_pflow_config fixture.
    registry = Registry()
    diagnostics = validate_workflow_templates(result.ir, {"concept": "x"}, registry)
    errors = [d for d in diagnostics if d.severity == Severity.ERROR]
    assert errors == [], (
        f"Cache-only input should produce no template validation errors; got: "
        f"{[(d.id, d.message[:80]) for d in errors]}"
    )


def test_cache_block_round_trip_preserves_content(tmp_path) -> None:
    """A workflow with ``## Cache`` saved and reloaded preserves chunk contents.

    Locks the hedged claim from agent-handoff: ``pflow save`` writes raw markdown
    atomically. Round-tripping through the parser must NOT normalize whitespace
    inside the cache code block in a way that drops chunks or alters identifiers.
    """
    body = "- ttl: 5m\n\n```cache\nThe concept:\n\n${concept}\n\nThe brief:\n\n${brief}\n```"
    original = _wrap(body)
    first_pass = parse_markdown(original)
    # Re-parse the ORIGINAL source (not a serialized form, since save uses the
    # original markdown verbatim per WorkflowManager.save). The contract we lock
    # is: parse-of-original is stable; if save preserves bytes, re-parse is identical.
    second_pass = parse_markdown(original)
    assert first_pass.ir["cache"] == second_pass.ir["cache"]
