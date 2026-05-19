"""G.1 — public ``deterministic_serialize`` helper.

Locks the contract that the canonical byte-serializer is a single public
function. Forking would silently break the load-bearing byte-identity
invariant the entire cache-key pipeline depends on.
"""

from __future__ import annotations

import json
from pathlib import Path

from pflow.core.prompt_cache import _deterministic_serialize, deterministic_serialize


def test_string_passes_through_verbatim() -> None:
    assert deterministic_serialize("hello") == "hello"


def test_dict_keys_are_sorted_for_byte_stability() -> None:
    """Dict insertion order doesn't change output bytes — load-bearing."""
    a = deterministic_serialize({"a": 1, "b": 2})
    b = deterministic_serialize({"b": 2, "a": 1})
    assert a == b
    assert json.loads(a) == {"a": 1, "b": 2}


def test_list_preserves_order() -> None:
    assert deterministic_serialize([3, 1, 2]) == "[3,1,2]"
    assert deterministic_serialize([1, 2, 3]) == "[1,2,3]"


def test_nested_dict_in_list_sorted_at_each_level() -> None:
    value = [{"b": 1, "a": 2}, {"d": 3, "c": 4}]
    assert deterministic_serialize(value) == '[{"a":2,"b":1},{"c":4,"d":3}]'


def test_non_json_native_value_uses_str_default() -> None:
    """Non-JSON-native values (Path, datetime, etc.) serialize via str()."""
    p = Path("/abs/x.pflow.md")
    serialized = deterministic_serialize(p)
    # Result is JSON-encoded — the string representation gets quoted.
    assert serialized == json.dumps(str(p))


def test_compact_separator_no_whitespace() -> None:
    """No spaces in output — separators=(",", ":") is a stability invariant."""
    assert deterministic_serialize({"a": 1, "b": 2}) == '{"a":1,"b":2}'


def test_underscored_alias_preserved_for_backward_compat() -> None:
    """Phase B3 / C1.2 callers used the underscored name. Keep the alias so
    in-tree imports don't break."""
    assert _deterministic_serialize is deterministic_serialize


def test_idempotent_for_strings() -> None:
    """deterministic_serialize(deterministic_serialize(s)) == deterministic_serialize(s)
    for string inputs (string passes through twice)."""
    s = "hello"
    once = deterministic_serialize(s)
    twice = deterministic_serialize(once)
    assert once == twice == "hello"


def test_none_value() -> None:
    assert deterministic_serialize(None) == "null"


def test_bool_values() -> None:
    assert deterministic_serialize(True) == "true"
    assert deterministic_serialize(False) == "false"


def test_int_and_float() -> None:
    assert deterministic_serialize(42) == "42"
    assert deterministic_serialize(3.14) == "3.14"
