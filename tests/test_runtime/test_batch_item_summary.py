"""Tests for display-safe failed batch item summaries."""

import re

import pytest

from pflow.runtime.engine.batch_item_summary import summarize_batch_item


def _large_payload() -> str:
    return "PAYLOAD-START " + " ".join(f"token{i}" for i in range(200)) + " PAYLOAD-END"


def test_dict_with_label_and_huge_string_is_bounded_and_deterministic() -> None:
    item = {"label": "oversized-item", "payload": _large_payload()}

    first = summarize_batch_item(item)
    second = summarize_batch_item(item)

    assert first["summary_version"] == 1
    assert first["label"] == "oversized-item"
    assert first["summary"] == second["summary"]
    assert first["sha256"] == second["sha256"]
    assert re.fullmatch(r"[0-9a-f]{12}", first["sha256"])
    assert "label='oversized-item'" in first["summary"]
    assert "payload=<str" in first["summary"]
    assert "sha256=" in first["summary"]
    assert len(first["summary"]) <= 240
    assert "PAYLOAD-START" not in first["summary"]
    assert "PAYLOAD-END" not in first["summary"]
    assert "token199" not in first["summary"]


def test_short_string_uses_quoted_value() -> None:
    summary = summarize_batch_item("fail-b")

    assert summary["summary"] == "'fail-b'"
    assert summary["truncated"] is False


def test_long_string_uses_size_and_hash_without_preview() -> None:
    payload = _large_payload()

    summary = summarize_batch_item(payload)

    assert summary["summary"].startswith("<str ")
    assert "chars sha256=" in summary["summary"]
    assert "PAYLOAD-START" not in summary["summary"]
    assert "PAYLOAD-END" not in summary["summary"]
    assert "token199" not in summary["summary"]


def test_nested_values_are_not_recursively_dumped() -> None:
    item = {"workflow": "child.pflow.md", "inputs": {"lyrics": _large_payload()}}

    summary = summarize_batch_item(item)

    assert "workflow='child.pflow.md'" in summary["summary"]
    assert "inputs=<dict 1 fields sha256=" in summary["summary"]
    assert "PAYLOAD-START" not in summary["summary"]
    assert len(summary["summary"]) <= 240


def test_hostile_non_serializable_object_does_not_raise() -> None:
    class Hostile:
        def __str__(self) -> str:
            raise RuntimeError("no str")

        def __repr__(self) -> str:
            raise RuntimeError("no repr")

    summary = summarize_batch_item(Hostile())

    assert summary["summary_version"] == 1
    assert summary["sha256"]
    assert summary["summary"]
    assert summary["type"] in {"Hostile", "unrepresentable"}


def test_sensitive_short_value_is_redacted_but_hash_is_stable() -> None:
    item = {"label": "row-1", "api_key": "sk-live-123"}

    first = summarize_batch_item(item)
    second = summarize_batch_item(item)

    assert "api_key=<redacted" in first["summary"]
    assert "sk-live-123" not in first["summary"]
    assert first["sha256"] == second["sha256"]


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("pwd", "hunter2"),
        ("private_key", "-----BEGIN-key"),
        ("ssh_key", "ssh-rsa AAAA"),
        ("credentials", "user:pass"),
        ("access_token", "tok-abc"),
    ],
)
def test_shared_rule_covers_names_the_old_fragment_list_missed(key: str, value: str) -> None:
    """The batch summary now defers to ``core.security_utils.is_sensitive_parameter`` (the single redaction
    rule), so a short-valued field named ``pwd`` / ``private_key`` / ``ssh_key`` / ``credentials`` —
    previously rendered VERBATIM because the local fragment list omitted them — is redacted."""
    summary = summarize_batch_item({"label": "row-1", key: value})["summary"]
    assert f"{key}=<redacted" in summary
    assert value not in summary


def test_shared_rule_does_not_over_redact_innocent_lookalike_keys() -> None:
    """The word-aware rule no longer redacts keys that merely CONTAIN a sensitive substring (``author`` →
    ``auth``, ``tokens`` → ``token``) — the over-match the old raw-substring fragment list had."""
    summary = summarize_batch_item({"author": "ada", "tokens": "42"})["summary"]
    assert "author='ada'" in summary
    assert "<redacted" not in summary
