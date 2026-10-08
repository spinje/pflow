"""Task 173 — the canonical IR digest factored out of the inline-workflow id (workflow_id.py).

The digest is the shared fingerprint behind TWO consumers: the inline-run scope id (``ir-hash:<digest>``)
and the replay version-detection ``content_hash`` (producer stamp + replay compare). Both depend on it being
ORDER-INSENSITIVE and DETERMINISTIC, and on ``synthesize_inline_workflow_id`` being exactly that digest under
an ``ir-hash:`` prefix (one definition — a drift would silently make an inline replay false-flag stale)."""

from __future__ import annotations

from typing import Any

import pytest

from pflow.core.workflow_id import (
    canonical_ir_digest,
    step_identity,
    synthesize_inline_workflow_id,
    workflow_content_hash,
)


def test_canonical_ir_digest_is_insensitive_to_dict_key_order() -> None:
    a = {"ir_version": "0.1.0", "nodes": [{"id": "x", "type": "shell", "params": {"command": "echo hi"}}]}
    b = {"nodes": [{"params": {"command": "echo hi"}, "type": "shell", "id": "x"}], "ir_version": "0.1.0"}
    assert canonical_ir_digest(a) == canonical_ir_digest(b)


def test_canonical_ir_digest_changes_when_content_changes() -> None:
    base = {"nodes": [{"id": "greet", "type": "shell", "params": {"command": "echo hi"}}]}
    renamed = {"nodes": [{"id": "greet2", "type": "shell", "params": {"command": "echo hi"}}]}
    assert canonical_ir_digest(base) != canonical_ir_digest(renamed)


def test_synthesize_inline_workflow_id_is_the_digest_under_an_ir_hash_prefix() -> None:
    # ONE definition: the inline id is exactly ``ir-hash:`` + the digest. The whole replay feature's
    # inline short-circuit (``_is_stale`` returns False on an ``ir-hash:`` key) banks on this equality.
    ir = {"nodes": [{"id": "x", "type": "shell", "params": {"command": "echo hi"}}]}
    assert synthesize_inline_workflow_id(ir) == f"ir-hash:{canonical_ir_digest(ir)}"


def test_workflow_content_hash_ignores_source_location_provenance() -> None:
    # The replay fingerprint is the LOGICAL workflow: a node that differs ONLY in source-line provenance
    # (`_source_line`/`_source_lines`/`_source_files` — editor-click metadata a comment/whitespace edit
    # shifts) hashes the SAME, so a layout-only edit never reads as "a different version".
    at_line_7 = {"nodes": [{"id": "x", "type": "shell", "params": {"command": "echo hi"}, "_source_line": 7}]}
    at_line_9 = {"nodes": [{"id": "x", "type": "shell", "params": {"command": "echo hi"}, "_source_line": 9}]}
    assert workflow_content_hash(at_line_7) == workflow_content_hash(at_line_9)
    # …and it still differs from the raw digest (provenance WAS present and stripped).
    assert workflow_content_hash(at_line_7) != canonical_ir_digest(at_line_7)


def test_workflow_content_hash_still_changes_on_a_logical_edit() -> None:
    # A real change (node rename) must still flip it — and `_routes_to_end` is semantic, NOT stripped.
    base = {"nodes": [{"id": "greet", "type": "shell", "params": {"command": "echo hi"}, "_source_line": 3}]}
    renamed = {"nodes": [{"id": "greet2", "type": "shell", "params": {"command": "echo hi"}, "_source_line": 3}]}
    routed = {"nodes": [{"id": "greet", "type": "shell", "params": {"command": "echo hi"}, "_routes_to_end": True}]}
    assert workflow_content_hash(base) != workflow_content_hash(renamed)
    assert workflow_content_hash(base) != workflow_content_hash(routed)  # _routes_to_end is kept (semantic)


def test_workflow_content_hash_does_not_mutate_its_input() -> None:
    ir = {"nodes": [{"id": "x", "type": "shell", "params": {"command": "echo hi"}, "_source_line": 7}]}
    workflow_content_hash(ir)
    assert ir["nodes"][0]["_source_line"] == 7, "the strip must rebuild containers, never mutate resolved.ir"


# ── step_identity (Task 180): what resume checks before restoring a step's saved output ──────────

_BASE = """# Pipeline

## Inputs

### greeting

What to say.

- type: string
- default: hello

## Cache

```cache
Context for the summary:

${produce.stdout}

Unused chunk:

${greeting}
```

## Steps

### produce

Produce it.

- type: shell
- env:
    G: ${greeting}

```shell command
printf '%s' "$G"
```

### summarize

Summarize it.

- type: llm
- model: anthropic/claude-haiku-4-5
- prompt_cache: [produce.stdout]

```prompt
Summarize.
```

### save

Save it.

- type: write-file
- file_path: out.txt
- content: ${summarize.response}
"""


def _identity(markdown: str) -> dict[str, Any]:
    from pflow.core.markdown_parser import parse_markdown

    return step_identity(parse_markdown(markdown).ir)


def _changed_steps(before: dict[str, Any], after: dict[str, Any]) -> dict[str, set[str]]:
    """Which steps' hash / next differ between two identities (steps present in both)."""
    shared = before["steps"].keys() & after["steps"].keys()
    return {
        "hash": {n for n in shared if before["steps"][n]["hash"] != after["steps"][n]["hash"]},
        "next": {n for n in shared if before["steps"][n]["next"] != after["steps"][n]["next"]},
    }


def test_step_identity_covers_every_top_level_step_with_its_recorded_next_steps() -> None:
    identity = _identity(_BASE)
    assert identity["start"] == "produce"
    assert list(identity["steps"]) == ["produce", "summarize", "save"]
    # A document-order edge carries no `action` in the IR; it is recorded as "default".
    assert identity["steps"]["produce"]["next"] == [["default", "summarize"]]
    assert identity["steps"]["save"]["next"] == []
    assert all(len(step["hash"]) == 32 for step in identity["steps"].values())


def test_step_identity_ignores_prose_and_layout_but_not_a_params_edit() -> None:
    base = _identity(_BASE)
    prose = _identity(_BASE.replace("Summarize it.", "Summarize it, briefly and well."))
    # A blank line inserted above the steps shifts every `_source_line` — layout, not definition.
    layout = _identity(_BASE.replace("## Steps\n", "## Steps\n\n\n"))
    edited = _identity(_BASE.replace("printf '%s' \"$G\"", "printf '%s!' \"$G\""))
    assert prose == base
    assert layout == base
    assert _changed_steps(base, edited) == {"hash": {"produce"}, "next": set()}


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("- type: shell\n", "- type: shell\n- retry:\n    max_attempts: 3\n"),
        ("- type: shell\n", "- type: shell\n- approval: required\n"),
        ("- type: shell\n", "- type: shell\n- cache: true\n"),
        ("    G: ${greeting}\n", "    G: ${greeting}\n    H: extra\n"),
    ],
    ids=["retry", "approval", "cache", "env"],
)
def test_step_identity_counts_policy_and_env_settings_as_edits(old: str, new: str) -> None:
    # Fail-closed: "definition minus prose" — settings that cannot change the saved output still count.
    base = _identity(_BASE)
    assert _changed_steps(base, _identity(_BASE.replace(old, new, 1))) == {"hash": {"produce"}, "next": set()}


def test_step_identity_counts_loop_and_batch_as_edits() -> None:
    base = _identity(_BASE)
    looped = _identity(_BASE.replace("- type: write-file\n", "- type: write-file\n- loop:\n    max_iterations: 2\n"))
    batched = _identity(_BASE.replace("- type: write-file\n", '- type: write-file\n- batch:\n    items: ["a", "b"]\n'))
    assert _changed_steps(base, looped) == {"hash": {"save"}, "next": set()}
    assert _changed_steps(base, batched) == {"hash": {"save"}, "next": set()}


def test_step_identity_follows_the_cache_chunks_a_step_uses_and_only_those() -> None:
    base = _identity(_BASE)
    used = _identity(_BASE.replace("Context for the summary:", "Context for the summary, revised:"))
    unused = _identity(_BASE.replace("Unused chunk:", "Unused chunk, revised:"))
    assert _changed_steps(base, used) == {"hash": {"summarize"}, "next": set()}
    assert unused == base
    # The chunks alone are recorded too (only on a step that uses one), so a refusal can name the cause.
    assert "cache" not in base["steps"]["produce"]
    assert base["steps"]["summarize"]["cache"] != used["steps"]["summarize"]["cache"]
    params_edit = _identity(_BASE.replace("Summarize.", "Summarize briefly."))
    assert params_edit["steps"]["summarize"]["cache"] == base["steps"]["summarize"]["cache"]


@pytest.mark.parametrize("malformed", ["42", "[{a: 1}]"])
def test_step_identity_tolerates_an_unvalidated_prompt_cache_and_still_counts_it(malformed: str) -> None:
    """Resume computes identity BEFORE validation, so a malformed ``prompt_cache`` must not crash it
    (the validator reports it after); it still changes that step's hash."""
    edited = _identity(_BASE.replace("- file_path: out.txt\n", f"- file_path: out.txt\n- prompt_cache: {malformed}\n"))
    assert _changed_steps(_identity(_BASE), edited) == {"hash": {"save"}, "next": set()}


def test_step_identity_reads_an_explicit_next_like_document_order() -> None:
    explicit = _identity(_BASE.replace("- type: shell\n", "- type: shell\n- next: summarize\n"))
    assert explicit["steps"]["produce"]["next"] == [["default", "summarize"]]
    # `next:` lives on the edge list, not the node — the step's hash is untouched too.
    assert explicit == _identity(_BASE)


def test_step_identity_records_a_reroute_on_the_from_step_only() -> None:
    base = _identity(_BASE)
    rerouted = _identity(_BASE.replace("- type: shell\n", "- type: shell\n- next: save\n"))
    assert rerouted["steps"]["produce"]["next"] == [["default", "save"]]
    assert _changed_steps(base, rerouted) == {"hash": set(), "next": {"produce"}}


def test_step_identity_keeps_an_on_error_edge_beside_the_implicit_next() -> None:
    with_handler = (
        _BASE.replace("- type: shell\n", "- type: shell\n- on-error: recover\n", 1).replace(
            "- type: write-file\n", "- type: write-file\n- next: end\n"
        )
        + "\n### recover\n\nRecover.\n\n- type: shell\n- next: end\n\n```shell command\ntrue\n```\n"
    )
    identity = _identity(with_handler)
    assert identity["steps"]["produce"]["next"] == [["default", "summarize"], ["error", "recover"]]


def test_step_identity_shows_an_inserted_step_on_its_predecessor_only() -> None:
    base = _identity(_BASE)
    inserted = _identity(
        _BASE.replace(
            "### save\n",
            "### prepare\n\nPrepare it.\n\n- type: shell\n\n```shell command\ntrue\n```\n\n### save\n",
        )
    )
    assert inserted["steps"]["summarize"]["next"] == [["default", "prepare"]]
    assert inserted["steps"]["prepare"]["next"] == [["default", "save"]]
    assert _changed_steps(base, inserted) == {"hash": set(), "next": {"summarize"}}


def test_step_identity_start_follows_start_node_then_the_first_node() -> None:
    nodes = [{"id": "a", "type": "shell"}, {"id": "b", "type": "shell"}]
    assert step_identity({"nodes": nodes})["start"] == "a"
    assert step_identity({"nodes": nodes, "start_node": "b"})["start"] == "b"


def test_step_identity_is_insensitive_to_key_order_and_never_mutates_the_ir() -> None:
    a = {"nodes": [{"id": "x", "type": "shell", "params": {"command": "true", "env": {"A": "1"}}, "_source_line": 3}]}
    b = {"nodes": [{"_source_line": 3, "params": {"env": {"A": "1"}, "command": "true"}, "type": "shell", "id": "x"}]}
    assert step_identity(a) == step_identity(b)
    assert a["nodes"][0]["_source_line"] == 3


def test_step_identity_reads_both_edge_spellings_as_the_compiler_does() -> None:
    nodes = [{"id": "a", "type": "shell"}, {"id": "b", "type": "shell"}]
    from_to = step_identity({"nodes": nodes, "edges": [{"from": "a", "to": "b"}]})
    source_target = step_identity({"nodes": nodes, "edges": [{"source": "a", "target": "b", "action": "default"}]})
    assert from_to == source_target
    assert from_to["steps"]["a"]["next"] == [["default", "b"]]
