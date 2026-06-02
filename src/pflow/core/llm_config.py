"""Smart LLM model configuration with automatic key detection.

This module provides intelligent default model selection based on available
API keys, eliminating the need for hardcoded defaults throughout the codebase.

Key resolution sources (in priority order):
    1. Environment variables (os.environ)
    2. pflow settings (~/.pflow/settings.json env section)
"""

import logging
import os
from typing import Optional

from pflow.core.llm_providers import PROVIDERS
from pflow.core.settings import SettingsManager

logger = logging.getLogger(__name__)

# Cache the detected default model to avoid repeated key checks
_cached_default_model: Optional[str] = None
# Flag to track if detection has been completed (even if result is None)
_detection_complete: bool = False

# Provider to environment variable mapping derived from the canonical
# `llm_providers` registry. The registry's tuple of env vars carries
# canonical-first ordering plus any provider-accepted aliases (e.g. Gemini
# accepts both GEMINI_API_KEY and GOOGLE_API_KEY).
PROVIDER_ENV_VARS: dict[str, list[str]] = {p.name: list(p.env_vars) for p in PROVIDERS}

# Allowlist of trusted LLM providers — derived from the same registry.
ALLOWED_PROVIDERS = frozenset(PROVIDER_ENV_VARS.keys())


def _has_provider_key(provider: str) -> bool:
    """Check if an LLM provider key is configured from any source.

    Checks in order (stops at first found):
    1. Environment variables (os.environ)
    2. pflow settings (settings.json env section)

    Args:
        provider: Provider name ("anthropic", "gemini", "openai")

    Returns:
        True if key is configured in any source
    """
    if provider not in ALLOWED_PROVIDERS:
        logger.debug("Provider validation failed")
        return False

    env_vars = PROVIDER_ENV_VARS.get(provider, [])

    # 1. Check environment variables directly (fastest)
    for var in env_vars:
        value = os.environ.get(var, "").strip()
        if value:
            logger.debug(f"Found {provider} key in environment variable {var}")
            return True

    # 2. Check pflow settings (lazy import to avoid circular dependencies)
    try:
        from pflow.core.settings import SettingsManager

        manager = SettingsManager()
        for var in env_vars:
            settings_value = manager.get_env(var)
            if settings_value and settings_value.strip():
                logger.debug(f"Found {provider} key in pflow settings ({var})")
                return True
    except Exception as e:
        # Settings might not exist or be corrupt — graceful degradation
        logger.debug(f"Failed to check pflow settings for {provider}: {e}")

    return False


def _detect_default_model() -> Optional[str]:
    """Detect best available LLM model based on configured API keys.

    Priority order:
    1. Anthropic Claude (best overall quality)
    2. Google Gemini (good quality, cheaper)
    3. OpenAI (widely available fallback)

    Returns:
        Model name string, or None if no keys configured
    """
    # Try Anthropic first (best overall quality)
    if _has_provider_key("anthropic"):
        logger.debug("Using Anthropic Claude (key detected)")
        return "anthropic/claude-sonnet-4-5"

    # Try Gemini second (good quality, cheaper)
    if _has_provider_key("gemini"):
        logger.debug("Using Google Gemini (key detected)")
        return "gemini/gemini-3-flash-preview"

    # Try OpenAI last (common fallback). Provider prefix is required —
    # LiteLLM rejects bare model names with a "LLM Provider NOT provided"
    # BadRequestError that pflow surfaces as UnknownModelError(reason="missing_prefix").
    if _has_provider_key("openai"):
        logger.debug("Using OpenAI GPT (key detected)")
        return "openai/gpt-5.2"

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

    Example (detect without enforcing; the caller decides how to react)::

        model = get_default_llm_model()
        if model is None:
            click.echo("Error: No LLM keys")  # handle at the caller level
    """
    global _cached_default_model, _detection_complete

    # Check if detection has been completed (not the cached value itself)
    if not _detection_complete:
        _cached_default_model = _detect_default_model()
        _detection_complete = True

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
        "    OR: pflow settings set-env ANTHROPIC_API_KEY your-key\n\n"
        "  Google Gemini (cheaper alternative):\n"
        "    export GEMINI_API_KEY=your-key\n"
        "    OR: pflow settings set-env GEMINI_API_KEY your-key\n\n"
        "  OpenAI (common fallback):\n"
        "    export OPENAI_API_KEY=your-key\n"
        "    OR: pflow settings set-env OPENAI_API_KEY your-key"
    )


def clear_model_cache() -> None:
    """Clear the cached default model.

    Useful for testing or when keys are added/removed at runtime.
    """
    global _cached_default_model, _detection_complete
    _cached_default_model = None
    _detection_complete = False


def inject_settings_env_vars() -> None:
    """Inject env vars from pflow settings into os.environ.

    This allows LiteLLM (and other tools) to find API keys stored in
    pflow settings via the standard env-var resolution path. Only injects
    if the key isn't already set in os.environ (user's actual environment
    takes priority).

    Should be called early in CLI/MCP server startup, before any LLM operations.

    Note:
        This is idempotent - safe to call multiple times.
        Failures are logged but don't raise (graceful degradation).
        Skipped in test environment to avoid test pollution.
    """
    # Skip in test environment to avoid polluting test state
    if os.environ.get("PYTEST_CURRENT_TEST"):
        logger.debug("Skipping env injection in test environment")
        return

    try:
        from pflow.core.settings import SettingsManager

        manager = SettingsManager()
        env_vars = manager.list_env(mask_values=False)

        for key, value in env_vars.items():
            if not value or not value.strip():
                continue  # Skip empty values

            if key not in os.environ:  # Don't override user's environment
                os.environ[key] = value
                logger.debug(f"Injected {key} from pflow settings into environment")
            else:
                logger.debug(f"Skipped {key} - already set in environment")
    except Exception as e:
        # Settings file might not exist or be corrupt - that's fine
        logger.debug(f"Failed to inject settings env vars: {e}")


# Default fallback model when nothing else is configured
_DEFAULT_FALLBACK_MODEL = "anthropic/claude-sonnet-4-5"


def get_model_for_feature(feature: str) -> str:
    """Get LLM model for a specific feature with fallback chain.

    Resolution order:
    1. Feature-specific setting (discovery_model or filtering_model)
    2. Default model setting (default_model) - shared fallback for all features
    3. Auto-detected default (based on available API keys)
    4. Hardcoded fallback (anthropic/claude-sonnet-4-5)

    Args:
        feature: Feature name - "discovery" or "filtering"

    Returns:
        Model name string (e.g., "anthropic/claude-sonnet-4-5", "gemini-2.5-flash")

    Raises:
        ValueError: If feature name is not recognized

    Examples:
        >>> model = get_model_for_feature("discovery")
        >>> model = get_model_for_feature("filtering")
    """
    if feature not in ("discovery", "filtering"):
        raise ValueError(f"Unknown feature: {feature}. Must be 'discovery' or 'filtering'")

    try:
        settings = SettingsManager().load()

        # 1. Check feature-specific setting first
        if feature == "discovery" and settings.llm.discovery_model:
            logger.debug(f"Using configured discovery model: {settings.llm.discovery_model}")
            return settings.llm.discovery_model
        elif feature == "filtering" and settings.llm.filtering_model:
            logger.debug(f"Using configured filtering model: {settings.llm.filtering_model}")
            return settings.llm.filtering_model

        # 2. Check default_model as shared fallback
        if settings.llm.default_model:
            logger.debug(f"Using default_model for {feature}: {settings.llm.default_model}")
            return settings.llm.default_model
    except Exception as e:
        # Settings load failed, continue with auto-detection
        logger.debug(f"Failed to load settings for {feature} model: {e}")

    # 3. Fall back to auto-detection
    detected = get_default_llm_model()
    if detected:
        logger.debug(f"Using auto-detected model for {feature}: {detected}")
        return detected

    # 4. Final fallback
    logger.debug(f"Using fallback model for {feature}: {_DEFAULT_FALLBACK_MODEL}")
    return _DEFAULT_FALLBACK_MODEL


def get_default_workflow_model() -> Optional[str]:
    """Get the default model for user workflow LLM nodes.

    Resolution order:
    1. settings.llm.default_model (pflow settings)
    2. Auto-detect from API keys (Anthropic → Gemini → OpenAI)
    3. None (caller should fail with helpful error)

    Returns:
        Model name string or None if nothing configured

    Example::

        model = get_default_workflow_model()
        if model is None:
            raise CompilationError("No model configured", ...)
    """
    # 1. Check pflow settings first
    try:
        settings = SettingsManager().load()
        if settings.llm.default_model:
            logger.debug(f"Using pflow settings default_model: {settings.llm.default_model}")
            return settings.llm.default_model
    except Exception as e:
        logger.debug(f"Failed to load settings for default_model: {e}")

    # 2. Auto-detect from API keys (matches discovery/filtering behavior)
    detected = get_default_llm_model()
    if detected:
        logger.debug(f"Using auto-detected model from API keys: {detected}")
        return detected

    # 3. Nothing configured
    logger.debug("No default workflow model configured or detected")
    return None


def get_model_not_configured_help(node_id: str) -> str:
    """Get helpful error message when no model is configured.

    Args:
        node_id: The LLM node ID for context in message

    Returns:
        Multi-line string with setup instructions
    """
    return f"""No model specified for LLM node '{node_id}' and no default could be detected.

pflow tried to auto-detect a model but no API keys were found for supported providers.

Configure using one of these methods:

  1. Set an API key (pflow will auto-detect the model):
     pflow settings set-env OPENAI_API_KEY "sk-..."
     pflow settings set-env ANTHROPIC_API_KEY "sk-ant-..."
     pflow settings set-env GEMINI_API_KEY "..."

     Or via shell environment:
     export ANTHROPIC_API_KEY=sk-ant-...

  2. Specify model in workflow (per-node, in .pflow.md):
     ### {node_id}
     - type: llm
     - model: openai/gpt-5.2

  3. Set pflow default model (overrides auto-detection):
     pflow settings llm set-default openai/gpt-5.2

To see configured pflow models: pflow settings llm show"""
