"""Tests for environment variable expansion with default values.

This module comprehensively tests the ${VAR:-default} syntax for environment
variable expansion in the MCP authentication utilities. It covers:

1. Basic default value functionality
2. Edge cases with special characters
3. Nested data structures
4. Real-world authentication patterns
5. Backward compatibility with ${VAR} syntax
6. Type preservation for non-string values
"""

import os
from unittest.mock import patch

from pflow.mcp.auth_utils import expand_env_vars_nested


class TestEnvVarDefaultSyntax:
    """Test the ${VAR:-default} syntax expansion."""

    def test_simple_var_with_default_when_missing(self):
        """Test default is used when variable is not set."""
        with patch.dict(os.environ, {}, clear=True):
            result = expand_env_vars_nested("${MISSING_VAR:-default_value}")
            assert result == "default_value"

    def test_simple_var_with_default_when_present(self):
        """Test actual value is used when variable is set."""
        with patch.dict(os.environ, {"PRESENT_VAR": "actual_value"}, clear=True):
            result = expand_env_vars_nested("${PRESENT_VAR:-default_value}")
            assert result == "actual_value"

    def test_empty_env_var_uses_empty_not_default(self):
        """Test that empty string env var doesn't trigger default."""
        with patch.dict(os.environ, {"EMPTY_VAR": ""}, clear=True):
            result = expand_env_vars_nested("${EMPTY_VAR:-default_value}")
            assert result == ""  # Empty string, not default

    def test_default_with_spaces(self):
        """Test default values can contain spaces."""
        with patch.dict(os.environ, {}, clear=True):
            result = expand_env_vars_nested("${MISSING:-default with spaces}")
            assert result == "default with spaces"

    def test_default_with_special_chars(self):
        """Test default values can contain special characters."""
        with patch.dict(os.environ, {}, clear=True):
            result = expand_env_vars_nested("${MISSING:-key_123-@#$%}")
            assert result == "key_123-@#$%"

    def test_empty_default(self):
        """Test empty default value."""
        with patch.dict(os.environ, {}, clear=True):
            result = expand_env_vars_nested("${MISSING:-}")
            assert result == ""

    def test_multiple_vars_in_string(self):
        """Test multiple variables with defaults in one string."""
        with patch.dict(os.environ, {"VAR1": "value1"}, clear=True):
            result = expand_env_vars_nested("${VAR1:-default1}/${VAR2:-default2}")
            assert result == "value1/default2"

    def test_nested_dict_with_defaults(self):
        """Test default values in nested dictionaries."""
        input_dict = {
            "url": "${API_URL:-http://localhost:3000}/endpoint",
            "auth": {"token": "${API_TOKEN:-test_token}", "key": "${API_KEY:-default_key}"},
            "headers": {"Authorization": "Bearer ${TOKEN:-fallback}", "X-Custom": "${CUSTOM:-custom_default}"},
        }

        with patch.dict(os.environ, {"API_TOKEN": "real_token"}, clear=True):
            result = expand_env_vars_nested(input_dict)

        assert result["url"] == "http://localhost:3000/endpoint"
        assert result["auth"]["token"] == "real_token"  # noqa: S105
        assert result["auth"]["key"] == "default_key"
        assert result["headers"]["Authorization"] == "Bearer fallback"
        assert result["headers"]["X-Custom"] == "custom_default"

    def test_list_with_defaults(self):
        """Test default values in lists."""
        input_list = ["${VAR1:-default1}", "static", "${VAR2:-default2}", ["${NESTED:-nested_default}"]]

        with patch.dict(os.environ, {"VAR1": "actual1"}, clear=True):
            result = expand_env_vars_nested(input_list)

        assert result[0] == "actual1"
        assert result[1] == "static"
        assert result[2] == "default2"
        assert result[3][0] == "nested_default"

    def test_url_with_default(self):
        """Test realistic URL with default."""
        url = "${BASE_URL:-https://api.example.com}/v1/mcp"

        # Without env var
        with patch.dict(os.environ, {}, clear=True):
            result = expand_env_vars_nested(url)
            assert result == "https://api.example.com/v1/mcp"

        # With env var
        with patch.dict(os.environ, {"BASE_URL": "https://prod.example.com"}, clear=True):
            result = expand_env_vars_nested(url)
            assert result == "https://prod.example.com/v1/mcp"

    def test_github_token_pattern(self):
        """Test common GitHub token pattern."""
        env_dict = {"GITHUB_TOKEN": "${GITHUB_TOKEN:-ghp_test_token}"}

        # Without real token
        with patch.dict(os.environ, {}, clear=True):
            result = expand_env_vars_nested(env_dict)
            assert result["GITHUB_TOKEN"] == "ghp_test_token"  # noqa: S105

        # With real token
        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_real_token"}, clear=True):
            result = expand_env_vars_nested(env_dict)
            assert result["GITHUB_TOKEN"] == "ghp_real_token"  # noqa: S105

    def test_composio_pattern(self):
        """Test Composio API key pattern."""
        headers = {"Authorization": "Bearer ${COMPOSIO_API_KEY:-test_key}", "User-Agent": "pflow/1.0"}

        with patch.dict(os.environ, {}, clear=True):
            result = expand_env_vars_nested(headers)
            assert result["Authorization"] == "Bearer test_key"
            assert result["User-Agent"] == "pflow/1.0"

    def test_no_expansion_for_regular_syntax(self):
        """Test that regular ${VAR} still works without default."""
        with patch.dict(os.environ, {"REGULAR_VAR": "value"}, clear=True):
            result = expand_env_vars_nested("${REGULAR_VAR}")
            assert result == "value"

    def test_regular_var_missing_gets_empty(self):
        """Test regular ${VAR} gets empty string when missing."""
        with patch.dict(os.environ, {}, clear=True):
            result = expand_env_vars_nested("${MISSING_REGULAR}")
            assert result == ""

    def test_mixed_syntax_in_same_string(self):
        """Test mixing regular and default syntax."""
        with patch.dict(os.environ, {"PRESENT": "here"}, clear=True):
            result = expand_env_vars_nested("${PRESENT}_${MISSING:-default}_${ANOTHER}")
            assert result == "here_default_"

    def test_default_with_colons(self):
        """Test default values containing colons."""
        with patch.dict(os.environ, {}, clear=True):
            result = expand_env_vars_nested("${URL:-http://localhost:8080}")
            assert result == "http://localhost:8080"

    def test_default_with_curly_braces(self):
        """Test default values with curly braces (JSON-like)."""
        with patch.dict(os.environ, {}, clear=True):
            # JSON-like string in default value
            result = expand_env_vars_nested('${CONFIG:-{"key":"value"}}')
            assert result == '{"key":"value"}'

    def test_non_string_values_preserved(self):
        """Test that non-string values pass through unchanged."""
        input_data = {"string": "${VAR:-default}", "number": 123, "boolean": True, "null": None, "list": [1, 2, 3]}

        with patch.dict(os.environ, {}, clear=True):
            result = expand_env_vars_nested(input_data)

        assert result["string"] == "default"
        assert result["number"] == 123
        assert result["boolean"] is True
        assert result["null"] is None
        assert result["list"] == [1, 2, 3]


class TestEnvVarEdgeCases:
    """Test edge cases and boundary conditions for env var expansion."""

    def test_lowercase_variable_names_expanded(self):
        """Test that lowercase variable names ARE expanded (supports mixed case)."""
        with patch.dict(os.environ, {"lower_var": "value"}, clear=True):
            result = expand_env_vars_nested("${lower_var:-default}")
            # Regex now matches mixed case vars (updated to match execution_service.py)
            assert result == "value"

    def test_variable_starting_with_number_not_expanded(self):
        """Test that variables starting with numbers are not expanded."""
        result = expand_env_vars_nested("${123VAR:-default}")
        assert result == "${123VAR:-default}"  # Not a valid env var name

    def test_underscore_prefix_allowed(self):
        """Test that variables starting with underscore are allowed."""
        with patch.dict(os.environ, {}, clear=True):
            result = expand_env_vars_nested("${_PRIVATE_VAR:-secret}")
            assert result == "secret"

        with patch.dict(os.environ, {"_PRIVATE_VAR": "actual"}, clear=True):
            result = expand_env_vars_nested("${_PRIVATE_VAR:-secret}")
            assert result == "actual"

    def test_variable_with_numbers_allowed(self):
        """Test that variables containing numbers are allowed."""
        with patch.dict(os.environ, {"VAR123": "value123"}, clear=True):
            result = expand_env_vars_nested("${VAR123:-default}")
            assert result == "value123"

    def test_variable_with_underscores_allowed(self):
        """Test that variables containing underscores are allowed."""
        with patch.dict(os.environ, {"MY_VAR_NAME": "myvalue"}, clear=True):
            result = expand_env_vars_nested("${MY_VAR_NAME:-default}")
            assert result == "myvalue"

    def test_single_dash_not_default_syntax(self):
        """Test that single dash is not recognized as default syntax."""
        result = expand_env_vars_nested("${VAR-default}")
        assert result == "${VAR-default}"  # Not the correct syntax

    def test_single_colon_not_default_syntax(self):
        """Test that single colon is not recognized as default syntax."""
        result = expand_env_vars_nested("${VAR:default}")
        assert result == "${VAR:default}"  # Not the correct syntax

    def test_no_variable_name_not_expanded(self):
        """Test that missing variable name is not expanded."""
        result = expand_env_vars_nested("${:-default}")
        assert result == "${:-default}"

    def test_unclosed_brace_not_expanded(self):
        """Test that unclosed braces are not expanded."""
        result = expand_env_vars_nested("${VAR:-default")
        assert result == "${VAR:-default"  # Invalid syntax

    def test_no_braces_not_expanded(self):
        """Test that variables without braces are not expanded."""
        with patch.dict(os.environ, {"VAR": "value"}, clear=True):
            result = expand_env_vars_nested("$VAR")
            assert result == "$VAR"  # Not the correct syntax

    def test_default_with_closing_brace_stops_at_first(self):
        """Test that default value stops at first closing brace."""
        with patch.dict(os.environ, {}, clear=True):
            # The regex [^}]* stops at first }
            result = expand_env_vars_nested("${VAR:-nested}value}")
            assert result == "nestedvalue}"  # 'nested' is the default, rest is literal

    def test_double_closing_brace(self):
        """Test handling of double closing braces."""
        with patch.dict(os.environ, {}, clear=True):
            result = expand_env_vars_nested("${VAR:-}}")
            assert result == "}"  # Empty default, extra } is literal

    def test_nested_variable_in_default_not_expanded(self):
        """Test that nested variables in defaults are not recursively expanded."""
        with patch.dict(os.environ, {"OTHER": "other_value"}, clear=True):
            result = expand_env_vars_nested("${MISSING:-${OTHER}}")
            # The inner ${OTHER} is treated as literal text in the default
            assert result == "${OTHER}"

    def test_escaped_characters_in_default(self):
        """Test escaped characters in default values."""
        with patch.dict(os.environ, {}, clear=True):
            # Backslash in default - regex stops at first }
            result = expand_env_vars_nested("${VAR:-\\}escaped}")
            assert result == "\\escaped}"  # Backslash is the default, rest is literal

    def test_default_with_minus_flag(self):
        """Test default values that look like command-line flags."""
        with patch.dict(os.environ, {}, clear=True):
            result = expand_env_vars_nested("${DEBUG:--verbose}")
            assert result == "-verbose"

    def test_default_with_equals_sign(self):
        """Test default values containing equals signs."""
        with patch.dict(os.environ, {}, clear=True):
            result = expand_env_vars_nested("${PARAM:-key=value}")
            assert result == "key=value"

    def test_default_with_quotes(self):
        """Test default values containing quotes."""
        with patch.dict(os.environ, {}, clear=True):
            result = expand_env_vars_nested("${MESSAGE:-'hello world'}")
            assert result == "'hello world'"

            result = expand_env_vars_nested('${MESSAGE:-"hello world"}')
            assert result == '"hello world"'

    def test_default_with_newlines(self):
        """Test default values containing newlines."""
        with patch.dict(os.environ, {}, clear=True):
            result = expand_env_vars_nested("${TEXT:-line1\\nline2}")
            assert result == "line1\\nline2"  # Literal backslash-n, not newline

    def test_multiple_expansions_complex(self):
        """Test complex string with multiple expansions and mixed syntax."""
        with patch.dict(os.environ, {"SET1": "val1", "SET3": "val3"}, clear=True):
            result = expand_env_vars_nested("prefix-${SET1:-def1}/${UNSET2:-def2}/${SET3}/${UNSET4:-def4}-suffix")
            assert result == "prefix-val1/def2/val3/def4-suffix"


class TestEnvVarRealWorldPatterns:
    """Test real-world authentication and configuration patterns."""

    def test_openai_api_key_pattern(self):
        """Test OpenAI API key pattern with default."""
        config = {"auth": {"type": "bearer", "token": "${OPENAI_API_KEY:-sk-test-key-for-development}"}}

        # Without env var
        with patch.dict(os.environ, {}, clear=True):
            result = expand_env_vars_nested(config)
            assert result["auth"]["token"] == "sk-test-key-for-development"  # noqa: S105

        # With env var
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-real-key"}, clear=True):
            result = expand_env_vars_nested(config)
            assert result["auth"]["token"] == "sk-real-key"  # noqa: S105

    def test_database_url_pattern(self):
        """Test database URL pattern with complex default."""
        config = {"database": {"url": "${DATABASE_URL:-postgresql://user:pass@localhost:5432/mydb}"}}

        with patch.dict(os.environ, {}, clear=True):
            result = expand_env_vars_nested(config)
            assert result["database"]["url"] == "postgresql://user:pass@localhost:5432/mydb"

    def test_multiple_auth_providers(self):
        """Test configuration with multiple auth providers and defaults."""
        config = {
            "providers": {
                "github": {
                    "token": "${GITHUB_TOKEN:-ghp_default_token}",
                    "api_url": "${GITHUB_API_URL:-https://api.github.com}",
                },
                "gitlab": {
                    "token": "${GITLAB_TOKEN:-glpat_default_token}",
                    "api_url": "${GITLAB_API_URL:-https://gitlab.com/api/v4}",
                },
                "custom": {
                    "key": "${CUSTOM_API_KEY:-}",  # Empty default
                    "secret": "${CUSTOM_SECRET}",  # No default
                },
            },
        }

        with (
            patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_real"}, clear=True),
            patch("pflow.mcp.auth_utils.logger") as mock_logger,
        ):
            result = expand_env_vars_nested(config)

            # GitHub has real token, others use defaults
            assert result["providers"]["github"]["token"] == "ghp_real"  # noqa: S105
            assert result["providers"]["github"]["api_url"] == "https://api.github.com"
            assert result["providers"]["gitlab"]["token"] == "glpat_default_token"  # noqa: S105
            assert result["providers"]["custom"]["key"] == ""
            assert result["providers"]["custom"]["secret"] == ""

            # Warning should be logged for missing CUSTOM_SECRET
            mock_logger.warning.assert_called()

    def test_docker_registry_auth_pattern(self):
        """Test Docker registry authentication pattern."""
        config = {
            "registry": "${DOCKER_REGISTRY:-docker.io}",
            "auth": {"username": "${DOCKER_USER:-anonymous}", "password": "${DOCKER_PASS:-}"},
        }

        with patch.dict(os.environ, {"DOCKER_USER": "myuser"}, clear=True):
            result = expand_env_vars_nested(config)
            assert result["registry"] == "docker.io"
            assert result["auth"]["username"] == "myuser"
            assert result["auth"]["password"] == ""

    def test_proxy_configuration_pattern(self):
        """Test proxy configuration with defaults."""
        config = {
            "http_proxy": "${HTTP_PROXY:-http://proxy.local:8080}",
            "https_proxy": "${HTTPS_PROXY:-${HTTP_PROXY:-http://proxy.local:8080}}",
            "no_proxy": "${NO_PROXY:-localhost,127.0.0.1,.local}",
        }

        # Note: nested expansion in default doesn't work recursively
        with patch.dict(os.environ, {}, clear=True):
            result = expand_env_vars_nested(config)
            assert result["http_proxy"] == "http://proxy.local:8080"
            assert result["https_proxy"] == "${HTTP_PROXY:-http://proxy.local:8080}"
            assert result["no_proxy"] == "localhost,127.0.0.1,.local"


class TestEnvVarIntegration:
    """Test integration with the broader auth_utils module."""

    def test_full_auth_flow_with_defaults(self):
        """Test complete authentication flow using defaults."""
        from pflow.mcp.auth_utils import build_auth_headers, expand_env_vars_nested

        config = {
            "headers": {"User-Agent": "${USER_AGENT:-pflow/1.0}", "Accept": "application/json"},
            "auth": {"type": "bearer", "token": "${API_TOKEN:-test-token-12345}"},
        }

        with patch.dict(os.environ, {}, clear=True):
            config = expand_env_vars_nested(config)
            headers = build_auth_headers(config)
            assert headers["User-Agent"] == "pflow/1.0"
            assert headers["Accept"] == "application/json"
            assert headers["Authorization"] == "Bearer test-token-12345"

    def test_warning_for_missing_without_default(self):
        """Test that missing env vars without defaults log warnings."""
        with patch.dict(os.environ, {}, clear=True), patch("pflow.mcp.auth_utils.logger") as mock_logger:
            result = expand_env_vars_nested("${MISSING_VAR}")
            assert result == ""
            mock_logger.warning.assert_called_with("Environment variable MISSING_VAR not found, using empty string")

    def test_no_warning_when_default_provided(self):
        """Test that no warning is logged when default is provided."""
        with patch.dict(os.environ, {}, clear=True), patch("pflow.mcp.auth_utils.logger") as mock_logger:
            result = expand_env_vars_nested("${MISSING_VAR:-default}")
            assert result == "default"
            mock_logger.warning.assert_not_called()

    def test_empty_string_vs_missing_env_var(self):
        """Test distinction between empty string and missing env var."""
        # Empty string in env var
        with patch.dict(os.environ, {"EMPTY": ""}, clear=True):
            result = expand_env_vars_nested("${EMPTY:-default}")
            assert result == ""  # Empty string is a value, not missing

        # Missing env var
        with patch.dict(os.environ, {}, clear=True):
            result = expand_env_vars_nested("${MISSING:-default}")
            assert result == "default"  # Missing triggers default

    def test_whitespace_only_env_var(self):
        """Test that whitespace-only values don't trigger defaults."""
        with patch.dict(os.environ, {"WHITESPACE": "   "}, clear=True):
            result = expand_env_vars_nested("${WHITESPACE:-default}")
            assert result == "   "  # Whitespace is still a value

    def test_complex_nested_structure(self):
        """Test deeply nested structure with mixed types and defaults."""
        config = {
            "api": {
                "endpoints": [
                    {
                        "name": "production",
                        "url": "${PROD_URL:-https://api.prod.example.com}",
                        "auth": {
                            "token": "${PROD_TOKEN:-prod-default-token}",
                            "timeout": 30,  # Non-string value
                        },
                    },
                    {
                        "name": "staging",
                        "url": "${STAGING_URL:-https://api.staging.example.com}",
                        "auth": {"token": "${STAGING_TOKEN:-staging-default-token}", "timeout": 60},
                    },
                ],
                "retry_count": 3,
                "debug": True,
            },
            "logging": {"level": "${LOG_LEVEL:-INFO}", "file": "${LOG_FILE:-/var/log/app.log}"},
        }

        with patch.dict(os.environ, {"PROD_URL": "https://api.example.com"}, clear=True):
            result = expand_env_vars_nested(config)

            # Check that structure is preserved
            assert len(result["api"]["endpoints"]) == 2
            assert result["api"]["endpoints"][0]["url"] == "https://api.example.com"
            assert result["api"]["endpoints"][0]["auth"]["token"] == "prod-default-token"  # noqa: S105
            assert result["api"]["endpoints"][0]["auth"]["timeout"] == 30  # Unchanged
            assert result["api"]["endpoints"][1]["url"] == "https://api.staging.example.com"
            assert result["api"]["retry_count"] == 3
            assert result["api"]["debug"] is True
            assert result["logging"]["level"] == "INFO"
            assert result["logging"]["file"] == "/var/log/app.log"
