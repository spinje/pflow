"""C1.1 round-trip tests for ``MockLLMClient.complete()`` ``system`` widening.

The adapter's ``system`` parameter accepts both ``str`` (today's plain-text
shape) and ``list[dict]`` (structured content blocks for cache rendering — see
``llm_client.complete`` docstring). The mock mirrors that contract; both shapes
must round-trip into ``call_history_full[-1]["system"]`` byte-for-byte so
cache-structure tests can assert on the recorded shape directly.
"""

from __future__ import annotations

from tests.shared.llm_mock import MockLLMClient


def test_complete_records_string_system_verbatim() -> None:
    mock = MockLLMClient()
    mock.complete(model="anthropic/claude-sonnet-4-5", prompt="hi", system="You are a helpful assistant.")

    assert mock.call_history_full[-1]["system"] == "You are a helpful assistant."


def test_complete_records_list_system_verbatim() -> None:
    blocks = [
        {"type": "text", "text": "stable context block 1"},
        {
            "type": "text",
            "text": "stable context block 2",
            "cache_control": {"type": "ephemeral"},
        },
    ]
    mock = MockLLMClient()
    mock.complete(model="anthropic/claude-sonnet-4-5", prompt="hi", system=blocks)

    recorded = mock.call_history_full[-1]["system"]
    assert recorded == blocks
    assert isinstance(recorded, list)
    assert recorded[-1]["cache_control"] == {"type": "ephemeral"}


def test_complete_records_list_system_with_ttl_marker() -> None:
    blocks = [
        {
            "type": "text",
            "text": "stable context",
            "cache_control": {"type": "ephemeral", "ttl": "1h"},
        },
    ]
    mock = MockLLMClient()
    mock.complete(model="anthropic/claude-sonnet-4-5", prompt="hi", system=blocks)

    recorded_marker = mock.call_history_full[-1]["system"][-1]["cache_control"]
    assert recorded_marker == {"type": "ephemeral", "ttl": "1h"}


def test_complete_none_system_records_none() -> None:
    mock = MockLLMClient()
    mock.complete(model="anthropic/claude-sonnet-4-5", prompt="hi")

    assert mock.call_history_full[-1]["system"] is None


def test_build_messages_accepts_list_system() -> None:
    """The adapter's _build_messages assembles the LiteLLM messages list. The
    ``messages.append({"role": "system", "content": system})`` line works
    unchanged for both string and list shapes — LiteLLM accepts either."""
    from pflow.core.llm_client import _build_messages

    blocks = [
        {"type": "text", "text": "block A"},
        {"type": "text", "text": "block B", "cache_control": {"type": "ephemeral"}},
    ]
    messages = _build_messages(system=blocks, prompt="ask", attachments=None)

    assert messages[0] == {"role": "system", "content": blocks}
    assert messages[1]["role"] == "user"


def test_build_messages_accepts_string_system_unchanged() -> None:
    from pflow.core.llm_client import _build_messages

    messages = _build_messages(system="be brief", prompt="ask", attachments=None)

    assert messages[0] == {"role": "system", "content": "be brief"}


def test_build_messages_omits_system_when_none() -> None:
    from pflow.core.llm_client import _build_messages

    messages = _build_messages(system=None, prompt="ask", attachments=None)

    assert all(m["role"] != "system" for m in messages)
    assert messages[0]["role"] == "user"
