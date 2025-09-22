"""Tests for validation utilities."""

from pflow.core.validation_utils import get_parameter_validation_error, is_valid_parameter_name


def test_valid_parameter_names():
    """Test that valid parameter names are accepted."""
    # Traditional Python identifiers
    assert is_valid_parameter_name("my_var")
    assert is_valid_parameter_name("MyVar")
    assert is_valid_parameter_name("_private")
    assert is_valid_parameter_name("var123")

    # Now also valid: hyphens
    assert is_valid_parameter_name("my-var")
    assert is_valid_parameter_name("api-key")
    assert is_valid_parameter_name("user-name")

    # Now also valid: dots
    assert is_valid_parameter_name("file.path")
    assert is_valid_parameter_name("data.field")
    assert is_valid_parameter_name("config.setting.value")

    # Now also valid: numbers at start
    assert is_valid_parameter_name("123start")
    assert is_valid_parameter_name("2fa-token")
    assert is_valid_parameter_name("1st-place")

    # Complex but valid
    assert is_valid_parameter_name("my-complex.param-123")


def test_invalid_parameter_names():
    """Test that invalid parameter names are rejected."""
    # Empty or whitespace
    assert not is_valid_parameter_name("")
    assert not is_valid_parameter_name("  ")
    assert not is_valid_parameter_name("\t")

    # Shell special characters
    assert not is_valid_parameter_name("my$var")  # Dollar sign
    assert not is_valid_parameter_name("cmd|pipe")  # Pipe
    assert not is_valid_parameter_name("out>file")  # Redirect
    assert not is_valid_parameter_name("in<file")  # Redirect
    assert not is_valid_parameter_name("cmd&bg")  # Background
    assert not is_valid_parameter_name("cmd;next")  # Command separator
    assert not is_valid_parameter_name("cmd`sub`")  # Backticks

    # Control characters
    assert not is_valid_parameter_name("line\nbreak")
    assert not is_valid_parameter_name("carriage\rreturn")
    assert not is_valid_parameter_name("null\0char")

    # Quotes and backslash
    assert not is_valid_parameter_name('my"var')
    assert not is_valid_parameter_name("my'var")
    assert not is_valid_parameter_name("my\\var")


def test_parameter_validation_error_messages():
    """Test that error messages are descriptive."""
    # Empty string
    error = get_parameter_validation_error("", "input")
    assert "cannot be empty" in error

    # Dollar sign
    error = get_parameter_validation_error("my$var", "input")
    assert "$" in error
    assert "template syntax" in error

    # Shell characters
    error = get_parameter_validation_error("cmd|pipe", "output")
    assert "shell special characters" in error

    # Control characters
    error = get_parameter_validation_error("line\nbreak", "parameter")
    assert "control characters" in error

    # Quotes
    error = get_parameter_validation_error('"quoted"', "input")
    assert "quotes" in error
