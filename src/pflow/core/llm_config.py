"""Smart LLM model configuration with automatic key detection.

This module provides intelligent default model selection based on available
API keys, eliminating the need for hardcoded defaults throughout the codebase.
"""

import logging
import shutil
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

# Cache the detected default model to avoid repeated key checks
_cached_default_model: Optional[str] = None

# Constant for the llm CLI command name
LLM_COMMAND = "llm"

# Allowlist of trusted LLM providers
ALLOWED_PROVIDERS = frozenset({"anthropic", "gemini", "openai"})

# Constant command args (security: prevents injection)
_LLM_KEYS_SUBCOMMAND = ["keys", "get"]


def _get_validated_llm_path() -> str | None:
    """Get validated path to llm executable.

    Returns:
        Full path to llm executable, or None if not found

    Security:
        Uses shutil.which() to resolve full path, avoiding
        execution of untrusted partial paths.
    """
    return shutil.which(LLM_COMMAND)


def _has_llm_key(provider: str) -> bool:
    """Check if an LLM provider key is configured.

    Uses Simon Willison's llm CLI to check for configured keys.

    Args:
        provider: Provider name ("anthropic", "gemini", "openai")

    Returns:
        True if key exists and is configured

    Security:
        - Validates provider against ALLOWED_PROVIDERS allowlist
        - Uses validated full executable path from _get_validated_llm_path()
        - No shell expansion (shell=False, list-based args)
    """
    # Security: Validate provider name to prevent command injection
    if provider not in ALLOWED_PROVIDERS:
        logger.debug(f"Unknown provider: {provider}")
        return False

    llm_path = _get_validated_llm_path()
    if not llm_path:
        logger.debug(f"{LLM_COMMAND} command not found in PATH")
        return False

    # Build command from constants and validated inputs
    command = [llm_path, *_LLM_KEYS_SUBCOMMAND, provider]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,  # Explicitly close stdin to prevent hang
            timeout=2,
            check=False,
        )
        # Key exists if command succeeds and returns non-empty output
        return result.returncode == 0 and bool(result.stdout.strip())
    except subprocess.TimeoutExpired:
        logger.debug(f"Timeout checking {provider} key")
        return False
    except Exception as e:
        logger.debug(f"Failed to check {provider} key: {e}")
        return False


def _detect_default_model() -> Optional[str]:
    """Detect best available LLM model based on configured API keys.

    Priority order:
    1. Anthropic Claude (best quality for planning/repair)
    2. Google Gemini (good quality, cheaper)
    3. OpenAI (widely available fallback)

    Returns:
        Model name string, or None if no keys configured
    """
    # Try Anthropic first (best for planning/repair)
    if _has_llm_key("anthropic"):
        logger.debug("Using Anthropic Claude (key detected)")
        return "anthropic/claude-sonnet-4-5"

    # Try Gemini second (good quality, cheaper)
    if _has_llm_key("gemini"):
        logger.debug("Using Google Gemini (key detected)")
        return "gemini/gemini-2.0-flash-lite"

    # Try OpenAI last (common fallback)
    if _has_llm_key("openai"):
        logger.debug("Using OpenAI GPT (key detected)")
        return "gpt-4o-mini"

    logger.debug("No LLM API keys detected")
    return None


def get_default_llm_model() -> Optional[str]:
    """Get default LLM model with caching.

    This function:
    1. Checks cache first (for performance)
    2. Detects available API keys if not cached
    3. Returns best available model or None

    Returns:
        Model name string (e.g., "anthropic/claude-sonnet-4-5")
        or None if no API keys configured

    Note:
        This function only detects - it does NOT enforce.
        The caller (CLI) decides whether to error or proceed.

    Examples:
        >>> # Detect without enforcing
        >>> model = get_default_llm_model()
        >>> if model is None:
        >>>     # Handle at caller level
        >>>     click.echo("Error: No LLM keys")
    """
    global _cached_default_model

    # Check cache first
    if _cached_default_model is None:
        _cached_default_model = _detect_default_model()

    return _cached_default_model


def get_llm_setup_help() -> str:
    """Get helpful error message for LLM setup.

    Returns:
        Multi-line string with setup instructions
    """
    return (
        "No LLM API keys configured. Please configure at least one:\n\n"
        "  Anthropic (recommended):\n"
        "    export ANTHROPIC_API_KEY=your-key\n"
        "    OR: llm keys set anthropic\n\n"
        "  Google Gemini (cheaper alternative):\n"
        "    llm keys set gemini\n\n"
        "  OpenAI (common fallback):\n"
        "    export OPENAI_API_KEY=your-key\n"
        "    OR: llm keys set openai\n\n"
        "See: https://llm.datasette.io/en/stable/setup.html"
    )


def clear_model_cache() -> None:
    """Clear the cached default model.

    Useful for testing or when keys are added/removed at runtime.
    """
    global _cached_default_model
    _cached_default_model = None
