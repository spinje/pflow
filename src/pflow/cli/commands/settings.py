"""Settings management CLI commands."""

import json

import click

from pflow.core.settings import PflowSettings, SettingsManager


@click.group()
def settings() -> None:
    """Manage pflow settings."""
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

    # Show if environment variable is overriding
    import os

    if os.getenv("PFLOW_INCLUDE_TEST_NODES"):
        click.echo("\n⚠️  PFLOW_INCLUDE_TEST_NODES environment variable is set")
        click.echo(
            f"   Test nodes are {'enabled' if os.getenv('PFLOW_INCLUDE_TEST_NODES', '').lower() in ('true', '1', 'yes') else 'disabled'} via environment variable"
        )


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

    # Check environment override
    import os

    if os.getenv("PFLOW_INCLUDE_TEST_NODES") and node_name.startswith("test"):
        env_value = os.getenv("PFLOW_INCLUDE_TEST_NODES", "").lower()
        if env_value in ("true", "1", "yes"):
            click.echo("\n  ⚠️  Test node included due to PFLOW_INCLUDE_TEST_NODES=true")


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
    - discovery: Model for 'pflow registry discover' and 'pflow workflow discover'
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
    from pflow.core.llm_config import (
        get_default_llm_model,
        get_llm_cli_default_model,
    )

    if configured_value:
        return f"{configured_value} (configured)"

    # For default_model, resolution is: settings → llm CLI → error
    if setting_name == "default":
        llm_cli_default = get_llm_cli_default_model()
        if llm_cli_default:
            return f"(llm CLI default → {llm_cli_default})"
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

    click.echo("\nResolution order:")
    click.echo("  default:    workflow params → default_model → llm CLI default → error")
    click.echo("  discovery:  discovery_model → default_model → auto-detect → fallback")
    click.echo("  filtering:  filtering_model → default_model → auto-detect → fallback")

    click.echo("\nTo configure:")
    click.echo("  pflow settings llm set-default <model>")
    click.echo("  pflow settings llm set-discovery <model>")
    click.echo("  pflow settings llm set-filtering <model>")


@llm.command(name="set-default")
@click.argument("model")
def llm_set_default(model: str) -> None:
    """Set the default model for all pflow LLM usage.

    This model is used as the fallback for:
    - LLM nodes in workflows (when no model specified)
    - Discovery commands (when discovery_model not set)
    - Smart filtering (when filtering_model not set)

    Example:
        pflow settings llm set-default gpt-5.2
        pflow settings llm set-default anthropic/claude-sonnet-4-5
        pflow settings llm set-default gemini-3-flash-preview
    """
    manager = SettingsManager()
    current_settings = manager.load()
    current_settings.llm.default_model = model
    manager.save(current_settings)

    click.echo(f"✓ Set default_model: {model}")


@llm.command(name="set-discovery")
@click.argument("model")
def llm_set_discovery(model: str) -> None:
    """Set the model for discovery commands.

    Used by 'pflow registry discover' and 'pflow workflow discover'.

    Example:
        pflow settings llm set-discovery anthropic/claude-sonnet-4-5
        pflow settings llm set-discovery gemini-3-flash-preview
    """
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

    Example:
        pflow settings llm set-filtering gemini-2.5-flash-lite
        pflow settings llm set-filtering gpt-4o-mini
    """
    manager = SettingsManager()
    current_settings = manager.load()
    current_settings.llm.filtering_model = model
    manager.save(current_settings)

    click.echo(f"✓ Set filtering_model: {model}")


# Valid setting names for unset command
_LLM_SETTING_NAMES = {"default", "discovery", "filtering", "all"}


@llm.command(name="unset")
@click.argument("setting", type=click.Choice(["default", "discovery", "filtering", "all"]))
def llm_unset(setting: str) -> None:
    """Remove an LLM model setting.

    Removes the configured value, reverting to auto-detection behavior.

    SETTING can be: default, discovery, filtering, or all

    Example:
        pflow settings llm unset default      # Clear default_model
        pflow settings llm unset discovery    # Clear discovery_model
        pflow settings llm unset all          # Clear all LLM settings
    """
    manager = SettingsManager()
    current_settings = manager.load()

    if setting == "all":
        current_settings.llm.default_model = None
        current_settings.llm.discovery_model = None
        current_settings.llm.filtering_model = None
        manager.save(current_settings)
        click.echo("✓ Removed all LLM settings (will use auto-detection)")
    elif setting == "default":
        if current_settings.llm.default_model is None:
            click.echo("default_model is not set")
        else:
            current_settings.llm.default_model = None
            manager.save(current_settings)
            click.echo("✓ Removed default_model (will use llm CLI default or error)")
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


# ============================================================================
# Registry Settings Subgroup
# ============================================================================


@settings.group(name="registry")
def registry_settings() -> None:
    """Manage registry settings.

    Configure registry behavior including output display mode.
    """
    pass


@registry_settings.command(name="output-mode")
@click.argument("mode", required=False, type=click.Choice(["smart", "structure", "full"]))
def registry_output_mode(mode: str | None) -> None:
    """Show or set registry output mode.

    Controls how 'pflow registry run' displays node execution results.

    MODES:
      smart     - Show values with truncation, apply smart filtering (default)
      structure - Show template paths only, no values (Task 89 behavior)
      full      - Show all values, no filtering or truncation

    Examples:
        pflow settings registry output-mode           # Show current mode
        pflow settings registry output-mode smart     # Set to smart
        pflow settings registry output-mode structure # Set to structure-only
        pflow settings registry output-mode full      # Set to full output
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
        click.echo("\nTo change: pflow settings registry output-mode <mode>")
    else:
        # Set mode
        current_settings.registry.output_mode = mode
        manager.save(current_settings)
        click.echo(f"✓ Set registry output mode: {mode}")
