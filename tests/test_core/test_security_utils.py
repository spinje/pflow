"""Word-aware sensitive-parameter detection — the single source of truth all redaction sites defer to.

The earlier raw-substring rule redacted innocent names that merely CONTAINED a sensitive word (``author``
→ matched ``auth``); these pin the word-boundary behavior so real secrets still redact while innocent
look-alikes don't.
"""

from __future__ import annotations

from pflow.core.security_utils import is_sensitive_parameter, mask_sensitive_value, sanitize_parameters


class TestIsSensitiveParameter:
    def test_redacts_standard_secret_names(self) -> None:
        for key in (
            "password",
            "passwd",
            "api_key",
            "apikey",
            "api-key",
            "access_token",
            "client_secret",
            "authorization",
            "private_key",
            "secret",
            "token",
            "auth_token",
            "credentials",
        ):
            assert is_sensitive_parameter(key), key

    def test_is_case_insensitive(self) -> None:
        assert is_sensitive_parameter("API_KEY")
        assert is_sensitive_parameter("Password")
        assert is_sensitive_parameter("TOKEN")

    def test_matches_across_delimiters_and_camelcase(self) -> None:
        """A sensitive word as a WHOLE word in any casing/delimiter style — including variants the old
        exact-match in rerun display missed (``my_api_key``)."""
        for key in ("my_api_key", "X-API-Key", "apiKey", "accessToken", "clientSecret", "user.password"):
            assert is_sensitive_parameter(key), key

    def test_does_not_false_positive_on_innocent_words(self) -> None:
        """The bug this fixes: a sensitive word embedded in a LARGER word must not match."""
        for key in (
            "author",
            "authority",
            "authentic",
            "secretary",
            "tokens",
            "tokenizer",
            "username",
            "name",
            "model",
            "command",
        ):
            assert not is_sensitive_parameter(key), key


class TestSanitizeParameters:
    def test_redacts_nested_and_list_sensitive_keys(self) -> None:
        out = sanitize_parameters({
            "headers": {"Authorization": "Bearer x", "X-Trace": "ok"},
            "accounts": [{"api_key": "AKIA", "name": "prod"}],
            "author": "Ada",
        })
        assert out["headers"]["Authorization"] == "<REDACTED>"
        assert out["headers"]["X-Trace"] == "ok"
        assert out["accounts"][0]["api_key"] == "<REDACTED>"
        assert out["accounts"][0]["name"] == "prod"
        assert out["author"] == "Ada"  # the false-positive fix — no longer redacted

    def test_always_redact_keys_override(self) -> None:
        out = sanitize_parameters({"channel": "C09"}, always_redact_keys={"channel"})
        assert out["channel"] == "<REDACTED>"

    def test_truncates_long_non_secret_strings(self) -> None:
        out = sanitize_parameters({"note": "x" * 200})
        assert out["note"].endswith("...<truncated>")


def test_mask_sensitive_value_defers_to_the_shared_rule() -> None:
    assert mask_sensitive_value("api_key", "sk-123") == "<REDACTED>"
    assert mask_sensitive_value("author", "Ada") == "Ada"  # the false-positive fix
