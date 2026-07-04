"""Settings management CLI commands."""

import json
import os
from typing import ClassVar

import click

from pflow.core.settings import OUTPUT_MODES, LLMSettings, PflowSettings, SettingsManager


class SettingsGroup(click.Group):
    """Settings group with migration hints for removed subgroups."""

    _removed_commands: ClassVar[dict[str, str]] = {
        "registry": "Flattened: use 'pflow settings output-mode' directly (was: pflow settings registry output-mode)",
    }

    def resolve_command(
        self,
        ctx: click.Context,
        args: list[str],
    ) -> tuple[str | None, click.Command | None, list[str]]:
        if args and args[0] in self._removed_commands:
            click.echo(f"Error: 'settings {args[0]}' was removed.\n{self._removed_commands[args[0]]}", err=True)
            ctx.exit(1)
        return super().resolve_command(ctx, args)


@click.group(cls=SettingsGroup)
def settings() -> None:
    """Manage pflow settings — credentials, LLM models, and node filtering.

    \b
    Credentials:
      pflow settings set-env API_TOKEN "sk-..."    Store API key
      pflow settings set-env GITHUB_TOKEN "ghp-..."
      pflow settings show                          Verify stored values
    \b
    LLM provider keys (via environment variables or pflow settings):
      export ANTHROPIC_API_KEY=sk-ant-...
      export GEMINI_API_KEY=AI...
      pflow settings set-env OPENAI_API_KEY "sk-..."
      pflow settings llm providers                 # Full list of LLM providers and their env vars
    \b
    Stored credentials are available as fallbacks for declared workflow inputs.
    Precedence: CLI params > shell env > settings env > workflow defaults.
    Credentials must still be declared as inputs — they are not injected implicitly.
    """
    pass


@settings.command()
def init() -> None:
    """Initialize settings file with defaults.

    Creates ~/.pflow/settings.json with default configuration.
    """
    manager = SettingsManager()

    # Check if settings already exist
    if manager.settings_path.exists():
        click.confirm(f"Settings file already exists at {manager.settings_path}. Overwrite?", abort=True)

    # Create default settings
    default_settings = PflowSettings()
    manager.save(default_settings)

    click.echo(f"Created settings file at: {manager.settings_path}")
    click.echo("\nDefault settings:")
    click.echo(json.dumps(default_settings.model_dump(), indent=2))


def _mask_sensitive_env(settings_dict: dict) -> dict:
    """Create a copy of settings dict with sensitive env values masked.

    Args:
        settings_dict: Raw settings dictionary from settings.model_dump()

    Returns:
        New dict with sensitive env values masked (first 3 chars + ***)
    """
    from pflow.core.security_utils import is_sensitive_parameter

    # Create a copy to avoid mutating original
    masked = settings_dict.copy()

    # Only mask if env section exists and has values
    if masked.get("env"):
        masked_env = {}
        for key, value in masked["env"].items():
            if is_sensitive_parameter(key):
                # Mask sensitive values
                masked_env[key] = SettingsManager._mask_value(value)
            else:
                # Keep non-sensitive values as-is
                masked_env[key] = value
        masked["env"] = masked_env

    return masked


@settings.command()
def show() -> None:
    """Show current settings.

    Sensitive environment variable values are masked for security.
    Use 'pflow settings list-env --show-values' to view full values.
    """
    manager = SettingsManager()
    settings = manager.load()

    click.echo(f"Settings file: {manager.settings_path}")
    click.echo("\nCurrent settings:")

    # Get masked version of settings
    settings_dict = settings.model_dump()
    masked_dict = _mask_sensitive_env(settings_dict)

    click.echo(json.dumps(masked_dict, indent=2))


@settings.command()
@click.argument("pattern")
def allow(pattern: str) -> None:
    """Add an allow pattern for nodes.

    Example:
        pflow settings allow "file.*"
        pflow settings allow "mcp-github-*"
    """
    manager = SettingsManager()
    settings = manager.load()

    if pattern not in settings.registry.nodes.allow:
        settings.registry.nodes.allow.append(pattern)
        manager.save(settings)
        click.echo(f"✓ Added allow pattern: {pattern}")
    else:
        click.echo(f"Pattern already exists: {pattern}")

    # Show current allow list
    click.echo("\nCurrent allow patterns:")
    for p in settings.registry.nodes.allow:
        click.echo(f"  - {p}")


@settings.command()
@click.argument("pattern")
def deny(pattern: str) -> None:
    """Add a deny pattern for nodes.

    Example:
        pflow settings deny "test.*"
        pflow settings deny "github.delete-*"
    """
    manager = SettingsManager()
    settings = manager.load()

    if pattern not in settings.registry.nodes.deny:
        settings.registry.nodes.deny.append(pattern)
        manager.save(settings)
        click.echo(f"✓ Added deny pattern: {pattern}")
    else:
        click.echo(f"Pattern already exists: {pattern}")

    # Show current deny list
    click.echo("\nCurrent deny patterns:")
    for p in settings.registry.nodes.deny:
        click.echo(f"  - {p}")


@settings.command()
@click.argument("pattern")
@click.option("--allow", "list_type", flag_value="allow", default=True, help="Remove from allow list")
@click.option("--deny", "list_type", flag_value="deny", help="Remove from deny list")
def remove(pattern: str, list_type: str) -> None:
    """Remove a pattern from allow or deny list.

    Example:
        pflow settings remove "test.*" --deny
        pflow settings remove "file.*" --allow
    """
    manager = SettingsManager()
    settings = manager.load()

    if list_type == "deny":
        if pattern in settings.registry.nodes.deny:
            settings.registry.nodes.deny.remove(pattern)
            manager.save(settings)
            click.echo(f"✓ Removed deny pattern: {pattern}")
        else:
            click.echo(f"Pattern not found in deny list: {pattern}")

        # Show current deny list
        click.echo("\nCurrent deny patterns:")
        for p in settings.registry.nodes.deny:
            click.echo(f"  - {p}")
    else:
        if pattern in settings.registry.nodes.allow:
            settings.registry.nodes.allow.remove(pattern)
            manager.save(settings)
            click.echo(f"✓ Removed allow pattern: {pattern}")
        else:
            click.echo(f"Pattern not found in allow list: {pattern}")

        # Show current allow list
        click.echo("\nCurrent allow patterns:")
        for p in settings.registry.nodes.allow:
            click.echo(f"  - {p}")


@settings.command()
def reset() -> None:
    """Reset settings to defaults.

    This will delete the settings file and recreate it with defaults.
    """
    manager = SettingsManager()

    if manager.settings_path.exists():
        click.confirm("This will reset all settings to defaults. Continue?", abort=True)
        manager.settings_path.unlink()
        click.echo("Settings file deleted.")

    # Create default settings
    default_settings = PflowSettings()
    manager.save(default_settings)

    click.echo(f"Reset settings to defaults at: {manager.settings_path}")
    click.echo("\nDefault settings:")
    click.echo(json.dumps(default_settings.model_dump(), indent=2))


@settings.command()
@click.argument("node_name")
def check(node_name: str) -> None:
    """Check if a node would be included based on current settings.

    Example:
        pflow settings check echo
        pflow settings check mcp-github-create-issue
    """
    manager = SettingsManager()

    # Check if node would be included
    included = manager.should_include_node(node_name)

    if included:
        click.echo(f"✓ Node '{node_name}' would be INCLUDED")
    else:
        click.echo(f"✗ Node '{node_name}' would be EXCLUDED")

    # Show which patterns match (considering name/module/file_path variants)
    settings = manager.load()

    # Try to enrich with registry metadata for better diagnostics
    candidates = _build_candidates_for_check(node_name)
    _print_matching_patterns(settings, candidates, node_name)


def _build_candidates_for_check(node_name: str) -> list[str]:
    """Build candidate strings (name/module/file_path/category.name) for diagnostics."""
    candidates = [node_name]
    try:
        from pflow.registry import Registry

        reg = Registry()
        nodes = reg.load(include_filtered=True)
        meta = nodes.get(node_name, {})
        module = meta.get("module") or meta.get("module_path")
        file_path = meta.get("file_path")
        if module:
            candidates.append(str(module))
        if file_path:
            candidates.append(str(file_path))
    except Exception as e:
        # Non-fatal: diagnostics only
        import logging

        logging.getLogger(__name__).debug(f"Failed to load registry metadata for {node_name}: {e}")

    if "-" in node_name:
        prefix = node_name.split("-", 1)[0]
        candidates.append(f"{prefix}.{node_name}")
    # MCP aliases for diagnostics
    if node_name.startswith("mcp-"):
        parts = node_name.split("-", 2)
        if len(parts) >= 3:
            server = parts[1]
            tool = parts[2]
            if tool.startswith(f"{server}_"):
                tool = tool[len(server) + 1 :]
            tool_hyphen = tool.replace("_", "-")
            candidates.append(tool_hyphen)
            candidates.append(f"{server}.{tool_hyphen}")
    return candidates


def _print_matching_patterns(settings: PflowSettings, candidates: list[str], node_name: str) -> None:
    """Print matched deny/allow patterns for the given candidates."""
    from fnmatch import fnmatch

    matching_deny = [p for p in settings.registry.nodes.deny if any(fnmatch(c, p) for c in candidates)]
    if matching_deny:
        click.echo(f"\n  Matched deny patterns: {', '.join(matching_deny)}")

    matching_allow = [p for p in settings.registry.nodes.allow if any(fnmatch(c, p) for c in candidates)]
    if matching_allow:
        click.echo(f"  Matched allow patterns: {', '.join(matching_allow)}")


@settings.command(name="set-env")
@click.argument("key")
@click.argument("value")
def set_env(key: str, value: str) -> None:
    """Set an environment variable in settings.

    Example:
        pflow settings set-env replicate_api_token r8_xxx
        pflow settings set-env OPENAI_API_KEY sk-...
    """
    manager = SettingsManager()
    manager.set_env(key, value)

    click.echo(f"✓ Set environment variable: {key}")
    click.echo(f"   Value: {manager._mask_value(value)}")


@settings.command(name="unset-env")
@click.argument("key")
def unset_env(key: str) -> None:
    """Remove an environment variable from settings.

    Example:
        pflow settings unset-env replicate_api_token
    """
    manager = SettingsManager()
    removed = manager.unset_env(key)

    if removed:
        click.echo(f"✓ Removed environment variable: {key}")
    else:
        click.echo(f"✗ Environment variable not found: {key}")


@settings.command(name="list-env")
@click.option("--show-values", is_flag=True, help="Show full values (unmasked)")
def list_env(show_values: bool) -> None:
    """List all environment variables.

    By default, values are masked showing only the first 3 characters.
    Use --show-values to display full values (use with caution).

    Example:
        pflow settings list-env              # Masked
        pflow settings list-env --show-values  # Unmasked
    """
    manager = SettingsManager()
    env_vars = manager.list_env(mask_values=not show_values)

    if show_values:
        click.echo("⚠️  Displaying unmasked values")

    if not env_vars:
        click.echo("No environment variables configured")
        return

    click.echo("Environment variables:")
    for key, value in sorted(env_vars.items()):
        click.echo(f"  {key}: {value}")


# ============================================================================
# LLM Settings Subgroup
# ============================================================================


@settings.group()
def llm() -> None:
    """Manage LLM model settings.

    Configure which models are used for different pflow features:
    - default: Model for LLM nodes in user workflows
    - discovery: Model for 'pflow mcp find' and 'pflow find'
    - filtering: Model for smart field filtering (structure-only mode)
    """
    pass


def _get_resolved_model(setting_name: str, configured_value: str | None, default_model: str | None = None) -> str:
    """Get the resolved model value with source indication.

    Args:
        setting_name: Name of the setting (default, discovery, filtering)
        configured_value: Value from settings (may be None)
        default_model: The default_model setting value (for fallback display)

    Returns:
        String describing the resolved value and its source
    """
    from pflow.core.llm_config import get_default_llm_model

    if configured_value:
        return f"{configured_value} (configured)"

    # For default_model, resolution is: settings → auto-detect → error
    if setting_name == "default":
        detected = get_default_llm_model()
        if detected:
            return f"(auto-detect → {detected})"
        return "(not configured - will error if LLM node used)"

    # For discovery/filtering, resolution is: feature → default_model → auto-detect → fallback
    # Check if default_model is set and will be used
    if default_model:
        return f"(using default_model → {default_model})"

    detected = get_default_llm_model()
    if detected:
        return f"(auto-detect → {detected})"
    return "(fallback → anthropic/claude-sonnet-4-5)"


@llm.command(name="show")
def llm_show() -> None:
    """Show current LLM model settings.

    Displays configured models and shows how unset values will be resolved.

    Example:
        pflow settings llm show
    """
    manager = SettingsManager()
    current_settings = manager.load()

    click.echo("LLM Model Settings:\n")

    # Show each setting with resolution info
    # Pass default_model to discovery/filtering so they can show fallback
    default_model = current_settings.llm.default_model
    default_resolved = _get_resolved_model("default", default_model)
    discovery_resolved = _get_resolved_model("discovery", current_settings.llm.discovery_model, default_model)
    filtering_resolved = _get_resolved_model("filtering", current_settings.llm.filtering_model, default_model)

    click.echo(f"  default_model:    {default_resolved}")
    click.echo(f"  discovery_model:  {discovery_resolved}")
    click.echo(f"  filtering_model:  {filtering_resolved}")
    # TTS narration (Task 174): concrete defaults, no resolution chain — shown as-is.
    click.echo(f"  tts_model:        {current_settings.llm.tts_model}")
    click.echo(f"  tts_voice:        {current_settings.llm.tts_voice}")

    click.echo("\nResolution order:")
    click.echo("  default:    workflow params → default_model → auto-detect → error")
    click.echo("  discovery:  discovery_model → default_model → auto-detect → fallback")
    click.echo("  filtering:  filtering_model → default_model → auto-detect → fallback")

    click.echo("\nTo configure:")
    click.echo("  pflow settings llm set-default <model>")
    click.echo("  pflow settings llm set-discovery <model>")
    click.echo("  pflow settings llm set-filtering <model>")
    click.echo("  pflow settings llm set-tts-model <model>")
    click.echo("  pflow settings llm set-tts-voice <voice>")


# Curated registry of LLM providers and their LiteLLM-recognized env vars.
# Source: https://docs.litellm.ai/docs/providers (verified against
# litellm.validate_environment for the canonical short-list).
#
# Schema: (provider_name, env_vars_tuple, semantics, note)
#   semantics: "single" | "or" | "and" | "local"
#   - "or": any one of env_vars satisfies auth
#   - "and": all of env_vars must be set
#   - "local": no remote auth (env var, if any, is config like a server URL)
#
# Maintenance: when bumping LiteLLM, cross-check against
# litellm.models_by_provider keys for any popular additions. The list is
# curated — completeness < correctness. For providers not listed, the
# convention is <PROVIDER>_API_KEY where <PROVIDER> matches the slash-prefix.
_LLM_PROVIDERS: tuple[tuple[str, tuple[str, ...], str, str | None], ...] = (
    # OR semantics — either key works.
    ("gemini", ("GEMINI_API_KEY", "GOOGLE_API_KEY"), "or", None),
    # AND semantics — all required.
    ("bedrock", ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"), "and", "Or use AWS IAM role / ~/.aws/credentials"),
    ("azure", ("AZURE_API_KEY", "AZURE_API_BASE", "AZURE_API_VERSION"), "and", None),
    ("vertex_ai", ("VERTEXAI_PROJECT", "VERTEXAI_LOCATION"), "and", "Or use gcloud GOOGLE_APPLICATION_CREDENTIALS"),
    # Local — no key, just a server URL config.
    ("ollama", ("OLLAMA_API_BASE",), "local", "URL of local Ollama server, not a key"),
    ("vllm", (), "local", "Typically no auth required"),
    ("hosted_vllm", (), "local", "Typically no auth required"),
    # Single-key providers — alphabetical.
    ("ai21", ("AI21_API_KEY",), "single", None),
    ("anthropic", ("ANTHROPIC_API_KEY",), "single", None),
    ("anyscale", ("ANYSCALE_API_KEY",), "single", None),
    ("baseten", ("BASETEN_API_KEY",), "single", None),
    ("cerebras", ("CEREBRAS_API_KEY",), "single", None),
    ("cohere", ("COHERE_API_KEY",), "single", None),
    ("databricks", ("DATABRICKS_API_KEY",), "single", None),
    ("deepinfra", ("DEEPINFRA_API_KEY",), "single", None),
    ("deepseek", ("DEEPSEEK_API_KEY",), "single", None),
    ("fireworks_ai", ("FIREWORKS_AI_API_KEY",), "single", None),
    ("groq", ("GROQ_API_KEY",), "single", None),
    ("huggingface", ("HUGGINGFACE_API_KEY",), "single", None),
    ("mistral", ("MISTRAL_API_KEY",), "single", None),
    ("openai", ("OPENAI_API_KEY",), "single", None),
    ("openrouter", ("OPENROUTER_API_KEY",), "single", None),
    ("perplexity", ("PERPLEXITYAI_API_KEY",), "single", None),
    ("replicate", ("REPLICATE_API_KEY",), "single", None),
    ("together_ai", ("TOGETHERAI_API_KEY",), "single", "Note: not TOGETHER_API_KEY"),
    ("voyage", ("VOYAGE_API_KEY",), "single", None),
    ("xai", ("XAI_API_KEY",), "single", None),
)


def _provider_status(env_vars: tuple[str, ...], semantics: str) -> str:
    """Return display status: "set" | "-" | "n/a"."""
    if semantics == "local":
        return "n/a"
    if not env_vars:
        return "-"

    def _present(var: str) -> bool:
        return bool(os.environ.get(var, "").strip())

    ok = all(_present(v) for v in env_vars) if semantics == "and" else any(_present(v) for v in env_vars)
    return "set" if ok else "-"


def _format_env_vars(env_vars: tuple[str, ...], semantics: str) -> str:
    if not env_vars:
        return "(no key needed)"
    if semantics == "single" or len(env_vars) == 1:
        return env_vars[0]
    joiner = " and " if semantics == "and" else " or "
    return joiner.join(env_vars)


@llm.command(name="providers")
@click.argument("keyword", required=False)
@click.option(
    "--output-format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format (text table or JSON for agent parsing).",
)
def llm_providers(keyword: str | None, output_format: str) -> None:
    """List LLM providers and the API-key env vars each one needs.

    Curated against LiteLLM provider docs. For the full LiteLLM provider
    universe (including TTS/image/local providers not listed here), see
    https://docs.litellm.ai/docs/providers — most follow the convention
    <PROVIDER>_API_KEY where <PROVIDER> matches the slash-prefix.

    \b
    Examples:
      pflow settings llm providers                       # Full table
      pflow settings llm providers gemini                # Filter by substring
      pflow settings llm providers --output-format json  # For agent parsing
    """
    from pflow.core.llm_config import inject_settings_env_vars

    # Mirror pflow run startup: keys stored via `pflow settings set-env` must
    # be visible in os.environ so the installed-status check sees them.
    inject_settings_env_vars()

    entries = _LLM_PROVIDERS
    if keyword:
        needle = keyword.lower()
        entries = tuple(e for e in entries if needle in e[0].lower())

    # Sort: actionable rows (single/or/and) first, then local. Alphabetical within each.
    _priority = {"single": 0, "or": 0, "and": 0, "local": 1}
    rows = sorted(entries, key=lambda e: (_priority.get(e[2], 2), e[0]))

    if output_format == "json":
        click.echo(
            json.dumps(
                [
                    {
                        "name": name,
                        "env_vars": list(env_vars),
                        "semantics": semantics,
                        "status": _provider_status(env_vars, semantics),
                        "note": note,
                    }
                    for name, env_vars, semantics, note in rows
                ],
                indent=2,
            )
        )
        return

    if not rows:
        click.echo(f"No providers match '{keyword}'.", err=True)
        click.echo("Try: pflow settings llm providers              # see all", err=True)
        return

    vars_col = [_format_env_vars(env_vars, semantics) for _, env_vars, semantics, _ in rows]
    name_w = max(max(len(r[0]) for r in rows), len("PROVIDER"))
    vars_w = max(max(len(v) for v in vars_col), len("ENV VARS"))

    click.echo(f"{'PROVIDER':<{name_w}}  {'ENV VARS':<{vars_w}}  STATUS")
    for (name, env_vars, semantics, note), vars_str in zip(rows, vars_col, strict=True):
        status = _provider_status(env_vars, semantics)
        click.echo(f"{name:<{name_w}}  {vars_str:<{vars_w}}  {status}")
        if note:
            click.echo(f"{'':<{name_w}}  ({note})")

    click.echo(f"\nShowing {len(rows)} curated provider(s).")
    click.echo("Convention for unlisted providers: <PROVIDER>_API_KEY (matches slash-prefix).")
    click.echo('Set a key:  pflow settings set-env <ENV_VAR> "<value>"')
    click.echo("Full LiteLLM list: https://docs.litellm.ai/docs/providers")


def _normalize_and_warn_model(model: str) -> str:
    """Normalize bare model names and warn on unrecognized patterns.

    LiteLLM requires provider-prefixed model names (e.g. ``gemini/gemini-3-flash-preview``).
    Bare names route inconsistently — e.g. ``gemini-3-flash-preview`` routes to Vertex AI
    instead of Google AI Studio.
    """
    from pflow.core.llm_client import _normalize_model_name

    normalized = _normalize_model_name(model)
    if normalized != model:
        click.echo(f"  Normalized: {normalized}", err=True)
    elif "/" not in model:
        click.echo(
            f"  ⚠ '{model}' doesn't match any known provider (anthropic/, gemini/, openai/).\n"
            f"    If this is a custom or self-hosted model, it will be passed to LiteLLM as-is.",
            err=True,
        )
    return normalized


@llm.command(name="set-default")
@click.argument("model")
def llm_set_default(model: str) -> None:
    """Set the default model for all pflow LLM usage.

    This model is used as the fallback for:
    - LLM nodes in workflows (when no model specified)
    - Discovery commands (when discovery_model not set)
    - Smart filtering (when filtering_model not set)

    Bare names from known providers are auto-prefixed (e.g.
    ``gpt-4o-mini`` → ``openai/gpt-4o-mini``); a "Normalized:" line
    confirms the rewrite. Unknown bare names pass through with a
    warning so custom or self-hosted models still work.

    Example:
        pflow settings llm set-default openai/gpt-5.2
        pflow settings llm set-default anthropic/claude-sonnet-4-5
        pflow settings llm set-default gemini/gemini-3-flash-preview
    """
    model = _normalize_and_warn_model(model)
    manager = SettingsManager()
    current_settings = manager.load()
    current_settings.llm.default_model = model
    manager.save(current_settings)

    click.echo(f"✓ Set default_model: {model}")


@llm.command(name="set-discovery")
@click.argument("model")
def llm_set_discovery(model: str) -> None:
    """Set the model for discovery commands.

    Used by 'pflow mcp find' and 'pflow find'. Bare names are
    auto-prefixed (e.g. ``claude-sonnet-4-5`` → ``anthropic/claude-sonnet-4-5``);
    unknown bare names pass through with a warning.

    Example:
        pflow settings llm set-discovery anthropic/claude-sonnet-4-5
        pflow settings llm set-discovery gemini/gemini-3-flash-preview
    """
    model = _normalize_and_warn_model(model)
    manager = SettingsManager()
    current_settings = manager.load()
    current_settings.llm.discovery_model = model
    manager.save(current_settings)

    click.echo(f"✓ Set discovery_model: {model}")


@llm.command(name="set-filtering")
@click.argument("model")
def llm_set_filtering(model: str) -> None:
    """Set the model for smart field filtering.

    Used for structure-only mode when filtering large LLM responses.
    Bare names are auto-prefixed (e.g. ``gpt-4o-mini`` →
    ``openai/gpt-4o-mini``); unknown bare names pass through with a
    warning.

    Example:
        pflow settings llm set-filtering gemini/gemini-2.5-flash-lite
        pflow settings llm set-filtering openai/gpt-4o-mini
    """
    model = _normalize_and_warn_model(model)
    manager = SettingsManager()
    current_settings = manager.load()
    current_settings.llm.filtering_model = model
    manager.save(current_settings)

    click.echo(f"✓ Set filtering_model: {model}")


@llm.command(name="set-tts-model")
@click.argument("model")
def llm_set_tts_model(model: str) -> None:
    """Set the TTS model for `pflow ui --say` narration.

    A Gemini TTS model id; a leading ``gemini/`` prefix is accepted (it is
    stripped at call time). Narration needs a Gemini API key —
    `pflow settings set-env GEMINI_API_KEY <value>`.

    Example:
        pflow settings llm set-tts-model gemini-3.1-flash-tts-preview
    """
    manager = SettingsManager()
    current_settings = manager.load()
    current_settings.llm.tts_model = model
    manager.save(current_settings)

    click.echo(f"✓ Set tts_model: {model}")


@llm.command(name="set-tts-voice")
@click.argument("voice")
def llm_set_tts_voice(voice: str) -> None:
    """Set the TTS voice for `pflow ui --say` narration.

    A Gemini prebuilt voice name — e.g. Kore (the default), Puck, Charon,
    or Aoede. Full list: https://ai.google.dev/gemini-api/docs/speech-generation

    Example:
        pflow settings llm set-tts-voice Puck
    """
    manager = SettingsManager()
    current_settings = manager.load()
    current_settings.llm.tts_voice = voice
    manager.save(current_settings)

    click.echo(f"✓ Set tts_voice: {voice}")


# Valid setting names for unset command
_LLM_SETTING_NAMES = {"default", "discovery", "filtering", "tts-model", "tts-voice", "all"}


@llm.command(name="unset")
@click.argument("setting", type=click.Choice(["default", "discovery", "filtering", "tts-model", "tts-voice", "all"]))
def llm_unset(setting: str) -> None:
    """Remove an LLM model setting.

    Removes the configured value: models revert to auto-detection, the TTS
    fields revert to their built-in defaults.

    SETTING can be: default, discovery, filtering, tts-model, tts-voice, or all

    Example:
        pflow settings llm unset default      # Clear default_model
        pflow settings llm unset discovery    # Clear discovery_model
        pflow settings llm unset tts-voice    # Back to the default voice
        pflow settings llm unset all          # Clear all LLM settings
    """
    manager = SettingsManager()
    current_settings = manager.load()
    tts_defaults = LLMSettings()

    if setting == "all":
        current_settings.llm.default_model = None
        current_settings.llm.discovery_model = None
        current_settings.llm.filtering_model = None
        current_settings.llm.tts_model = tts_defaults.tts_model
        current_settings.llm.tts_voice = tts_defaults.tts_voice
        manager.save(current_settings)
        click.echo("✓ Removed all LLM settings (models use auto-detection; TTS back to defaults)")
    elif setting == "tts-model":
        current_settings.llm.tts_model = tts_defaults.tts_model
        manager.save(current_settings)
        click.echo(f"✓ Reset tts_model to the default: {tts_defaults.tts_model}")
    elif setting == "tts-voice":
        current_settings.llm.tts_voice = tts_defaults.tts_voice
        manager.save(current_settings)
        click.echo(f"✓ Reset tts_voice to the default: {tts_defaults.tts_voice}")
    elif setting == "default":
        if current_settings.llm.default_model is None:
            click.echo("default_model is not set")
        else:
            current_settings.llm.default_model = None
            manager.save(current_settings)
            click.echo("✓ Removed default_model (will use auto-detection or error)")
    elif setting == "discovery":
        if current_settings.llm.discovery_model is None:
            click.echo("discovery_model is not set")
        else:
            current_settings.llm.discovery_model = None
            manager.save(current_settings)
            click.echo("✓ Removed discovery_model (will use auto-detection)")
    elif setting == "filtering":
        if current_settings.llm.filtering_model is None:
            click.echo("filtering_model is not set")
        else:
            current_settings.llm.filtering_model = None
            manager.save(current_settings)
            click.echo("✓ Removed filtering_model (will use auto-detection)")


@settings.command(name="output-mode")
@click.argument("mode", required=False, type=click.Choice(OUTPUT_MODES))
def registry_output_mode(mode: str | None) -> None:
    """Show or set registry output mode.

    Controls how 'pflow probe' displays node execution results.

    MODES:
      smart     - Show values with truncation, apply smart filtering (default)
      structure - Show template paths only, no values (Task 89 behavior)
      full      - Show all values, no filtering or truncation

    Examples:
        pflow settings output-mode           # Show current mode
        pflow settings output-mode smart     # Set to smart
        pflow settings output-mode structure # Set to structure-only
        pflow settings output-mode full      # Set to full output
    """
    manager = SettingsManager()
    current_settings = manager.load()

    if mode is None:
        # Show current mode
        current_mode = current_settings.registry.output_mode
        click.echo(f"Current output mode: {current_mode}")
        click.echo("\nModes:")
        click.echo("  smart     - Show values with truncation, apply smart filtering (default)")
        click.echo("  structure - Show template paths only, no values")
        click.echo("  full      - Show all values, no filtering or truncation")
        click.echo("\nTo change: pflow settings output-mode <mode>")
    else:
        # Set mode
        current_settings.registry.output_mode = mode
        manager.save(current_settings)
        click.echo(f"✓ Set registry output mode: {mode}")
