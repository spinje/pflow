"""Settings management for pflow with environment variable override support."""

import json
import logging
import os
import stat
import tempfile
import threading
from fnmatch import fnmatch
from pathlib import Path
from typing import ClassVar, Optional

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class NodeFilterSettings(BaseModel):
    """Node filtering configuration."""

    allow: list[str] = Field(default_factory=lambda: ["*"])  # Default: allow all
    # Default: deny git/github nodes (require external tools, not universally useful)
    # Users can enable with: pflow settings allow pflow.nodes.git.* pflow.nodes.github.*
    deny: list[str] = Field(default_factory=lambda: ["pflow.nodes.git.*", "pflow.nodes.github.*"])


class RegistrySettings(BaseModel):
    """Registry-specific settings."""

    nodes: NodeFilterSettings = Field(default_factory=NodeFilterSettings)
    include_test_nodes: bool = Field(default=False)  # Can be overridden by env var
    output_mode: str = Field(
        default="smart",
        description="Output mode for registry run: smart (show values with truncation), "
        "structure (paths only), or full (all values, no filtering)",
    )

    @field_validator("output_mode")
    @classmethod
    def validate_output_mode(cls, v: str) -> str:
        """Validate output_mode is valid."""
        valid_modes = ["smart", "structure", "full"]
        if v not in valid_modes:
            raise ValueError(f"Invalid output_mode: {v}. Must be one of: {', '.join(valid_modes)}")
        return v


class RuntimeSettings(BaseModel):
    """Runtime execution configuration.

    These settings control workflow execution behavior.
    """

    template_resolution_mode: str = Field(
        default="strict", description="Default template resolution mode: strict or permissive"
    )

    @field_validator("template_resolution_mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        """Validate mode is valid."""
        if v not in ["strict", "permissive"]:
            raise ValueError(f"Invalid mode: {v}. Must be 'strict' or 'permissive'")
        return v


class LLMSettings(BaseModel):
    """LLM model configuration.

    These settings control which LLM models are used for:
    - User workflow LLM nodes (default_model)
    - Discovery commands (discovery_model)
    - Smart filtering (filtering_model)

    The planner always uses Anthropic for its advanced features.

    Resolution order:
    - LLM nodes:  workflow params → default_model → llm CLI default → error
    - discovery:  discovery_model → default_model → auto-detect → fallback
    - filtering:  filtering_model → default_model → auto-detect → fallback

    The default_model serves as a shared fallback for all features when
    feature-specific settings are not configured.

    Examples:
        # Set default model for everything (LLM nodes, discovery, filtering)
        {"default_model": "gemini-3-flash-preview"}

        # Override just discovery while using default for others
        {
            "default_model": "gemini-3-flash-preview",
            "discovery_model": "anthropic/claude-sonnet-4-5"
        }
    """

    default_model: Optional[str] = Field(
        default=None,
        description="Default model for all pflow LLM usage. "
        "Used by LLM nodes, discovery, and filtering when specific settings are not set.",
    )
    discovery_model: Optional[str] = Field(
        default=None,
        description="Model for discovery commands. Overrides default_model for discovery only.",
    )
    filtering_model: Optional[str] = Field(
        default=None,
        description="Model for smart field filtering. Overrides default_model for filtering only.",
    )


class PflowSettings(BaseModel):
    """Main settings configuration."""

    version: str = Field(default="1.0.0")
    registry: RegistrySettings = Field(default_factory=RegistrySettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    env: dict[str, str] = Field(default_factory=dict)


class SettingsManager:
    # Reserved for future use (kept for compatibility)
    _DEFAULT_TEST_DENY: ClassVar[set[str]] = set()
    """Manages pflow settings with environment variable override support."""

    def __init__(self, settings_path: Optional[Path] = None):
        self.settings_path = settings_path or Path.home() / ".pflow" / "settings.json"
        self._settings: Optional[PflowSettings] = None
        # Track base include_test_nodes from file to correctly handle env toggling
        self._base_include_test_nodes: Optional[bool] = None
        # Lock for thread-safe load-modify-save operations
        self._lock = threading.Lock()

    def load(self) -> PflowSettings:
        """Load settings with environment variable overrides."""
        if self._settings is None:
            self._settings = self._load_from_file()
            # Validate permissions after loading (defense-in-depth)
            self._validate_permissions(self._settings)
        # Use local reference to prevent TOCTOU race condition
        # (another thread could set self._settings = None between reads)
        settings = self._settings
        if settings is not None:
            # Always (re)apply env overrides to handle toggling without restart
            self._apply_env_overrides(settings)
        return settings

    def reload(self) -> PflowSettings:
        """Force reload settings from file."""
        self._settings = None
        return self.load()

    def _load_from_file(self) -> PflowSettings:
        """Load settings from file or return defaults."""
        if self.settings_path.exists():
            try:
                with open(self.settings_path) as f:
                    data = json.load(f)
                loaded = PflowSettings(**data)
                # Capture base include_test_nodes from file
                self._base_include_test_nodes = loaded.registry.include_test_nodes
                return loaded
            except Exception as e:
                # If file is corrupted, use defaults
                logger.warning(f"Failed to load settings from {self.settings_path} ({e}); using defaults")
                defaults = PflowSettings()
                self._base_include_test_nodes = defaults.registry.include_test_nodes
                return defaults
        defaults = PflowSettings()
        self._base_include_test_nodes = defaults.registry.include_test_nodes
        return defaults

    def _apply_env_overrides(self, settings: PflowSettings) -> None:
        """Apply environment variable overrides."""
        # Check for test node inclusion override
        env_value = os.getenv("PFLOW_INCLUDE_TEST_NODES")
        # Start from base value from file each time
        if self._base_include_test_nodes is not None:
            settings.registry.include_test_nodes = bool(self._base_include_test_nodes)
        if env_value is not None:
            include_test = env_value.lower() in ("true", "1", "yes")
            settings.registry.include_test_nodes = include_test
        # Note: We don't mutate the deny list here - the override is handled
        # at runtime in should_include_node() to keep it ephemeral

        # Check for template resolution mode override
        env_mode = os.getenv("PFLOW_TEMPLATE_RESOLUTION_MODE")
        if env_mode is not None:
            if env_mode.lower() in ("strict", "permissive"):
                settings.runtime.template_resolution_mode = env_mode.lower()
            else:
                logger.warning(
                    f"Invalid PFLOW_TEMPLATE_RESOLUTION_MODE: {env_mode}. "
                    f"Using default: {settings.runtime.template_resolution_mode}"
                )

    def should_include_node(self, node_name: str, node_module: Optional[str] = None) -> bool:
        """Check if a node should be included based on settings.

        Args:
            node_name: The node name (e.g., "echo", "read-file")
            node_module: Optional module path (e.g., "pflow.nodes.test.echo")

        Returns:
            True if the node should be included, False otherwise.
        """
        settings = self.load()

        # Hard test-node policy: hidden by default, visible only with env/test override
        if self._is_test_node(node_name, node_module):
            return settings.registry.include_test_nodes

        # Build candidates (includes MCP aliases for convenience)
        base_candidates: list[str] = [node_name]
        if node_module:
            base_candidates.append(node_module)
        extended_candidates = self._build_match_candidates(node_name, node_module)

        # Partition patterns by presence of hyphen
        deny_with_hyphen = [p for p in settings.registry.nodes.deny if "-" in p]
        deny_without_hyphen = [p for p in settings.registry.nodes.deny if "-" not in p]
        allow_with_hyphen = [p for p in settings.registry.nodes.allow if "-" in p]
        allow_without_hyphen = [p for p in settings.registry.nodes.allow if "-" not in p]

        # Apply denies
        if self._any_match(extended_candidates, deny_with_hyphen):
            return False
        if self._any_match(base_candidates, deny_without_hyphen):
            return False

        # Apply allows
        if self._any_match(extended_candidates, allow_with_hyphen):
            return True
        if self._any_match(base_candidates, allow_without_hyphen):
            return True

        return "*" in settings.registry.nodes.allow

    @staticmethod
    def _is_test_node(node_name: str, node_module: Optional[str]) -> bool:
        """Heuristic classification of pflow internal test nodes.

        Hidden by default; only exposed when PFLOW_INCLUDE_TEST_NODES=true.
        """
        # Known test node names in core tree
        known_test_names = {
            "echo",
            "example",
            "custom-name",
            "no-docstring",
            "retry-example",
            "structured-example",
            "mcp",  # Internal MCPNode - only used for virtual MCP tool entries
        }
        if node_name in known_test_names:
            return True
        if node_name.startswith("test") or node_name.startswith("test-") or node_name.startswith("test_"):
            return True
        if not node_module:
            return False
        # Dotted module path (e.g., pflow.nodes.test.echo) or filename/path
        nm = node_module
        return ".test." in nm or "test_node" in nm or "/test/" in nm or "/nodes/test_" in nm

    @staticmethod
    def _build_match_candidates(node_name: str, node_module: Optional[str]) -> list[str]:
        """Build candidate strings used for pattern matching."""
        candidates: list[str] = [node_name]
        if node_module:
            candidates.append(node_module)
        if "-" in node_name:
            prefix = node_name.split("-", 1)[0]
            candidates.append(f"{prefix}.{node_name}")
        # MCP aliases: mcp-{server}-{tool} → add candidates for 'tool' (hyphen) and 'server.tool'
        if node_name.startswith("mcp-"):
            parts = node_name.split("-", 2)
            if len(parts) >= 3:
                server = parts[1]
                tool = parts[2]
                # Clean redundant server_ prefix and convert underscores to hyphens
                if tool.startswith(f"{server}_"):
                    tool = tool[len(server) + 1 :]
                tool_hyphen = tool.replace("_", "-")
                candidates.append(tool_hyphen)
                candidates.append(f"{server}.{tool_hyphen}")
        return candidates

    @staticmethod
    def _any_match(candidates: list[str], patterns: list[str]) -> bool:
        """Return True if any candidate matches any pattern using fnmatch."""
        for pattern in patterns:
            for candidate in candidates:
                if fnmatch(candidate, pattern):
                    return True
        return False

    def save(self, settings: Optional[PflowSettings] = None) -> None:
        """Save settings to file with atomic operations and secure permissions."""
        if settings is None:
            settings = self.load()

        self.settings_path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write pattern: write to temp file, then replace
        temp_fd, temp_path = tempfile.mkstemp(dir=self.settings_path.parent, prefix=".settings.", suffix=".tmp")

        try:
            with open(temp_fd, "w", encoding="utf-8") as f:
                data = settings.model_dump()
                # Never persist env-derived test override; keep override ephemeral
                if isinstance(data.get("registry"), dict):
                    data["registry"].pop("include_test_nodes", None)
                json.dump(data, f, indent=2)

            # Atomic replace (works on all platforms)
            os.replace(temp_path, self.settings_path)

            # Set restrictive permissions (owner read/write only)
            os.chmod(self.settings_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600

            # Clear cache to force reload on next access
            self._settings = None

        except Exception:
            # Clean up temp file on failure
            Path(temp_path).unlink(missing_ok=True)
            raise

    def update_allow_list(self, patterns: list[str]) -> None:
        """Update the allow list with new patterns."""
        settings = self.load()
        settings.registry.nodes.allow = patterns
        self.save(settings)

    def update_deny_list(self, patterns: list[str]) -> None:
        """Update the deny list with new patterns."""
        settings = self.load()
        settings.registry.nodes.deny = patterns
        self.save(settings)

    def add_allow_pattern(self, pattern: str) -> None:
        """Add a pattern to the allow list."""
        settings = self.load()
        if pattern not in settings.registry.nodes.allow:
            settings.registry.nodes.allow.append(pattern)
            self.save(settings)

    def add_deny_pattern(self, pattern: str) -> None:
        """Add a pattern to the deny list."""
        settings = self.load()
        if pattern not in settings.registry.nodes.deny:
            settings.registry.nodes.deny.append(pattern)
            self.save(settings)

    def remove_allow_pattern(self, pattern: str) -> None:
        """Remove a pattern from the allow list."""
        settings = self.load()
        if pattern in settings.registry.nodes.allow:
            settings.registry.nodes.allow.remove(pattern)
            self.save(settings)

    def remove_deny_pattern(self, pattern: str) -> None:
        """Remove a pattern from the deny list."""
        settings = self.load()
        if pattern in settings.registry.nodes.deny:
            settings.registry.nodes.deny.remove(pattern)
            self.save(settings)

    def set_env(self, key: str, value: str) -> None:
        """Set an environment variable in settings.

        Args:
            key: Environment variable name
            value: Environment variable value
        """
        with self._lock:
            settings = self.load()
            settings.env[key] = value
            self.save(settings)

    def unset_env(self, key: str) -> bool:
        """Remove an environment variable from settings.

        Args:
            key: Environment variable name

        Returns:
            True if the key was removed, False if it didn't exist
        """
        with self._lock:
            settings = self.load()
            if key in settings.env:
                del settings.env[key]
                self.save(settings)
                return True
            return False

    def get_env(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Get an environment variable value.

        Args:
            key: Environment variable name
            default: Default value if key doesn't exist

        Returns:
            The value of the environment variable or the default
        """
        settings = self.load()
        return settings.env.get(key, default)

    def list_env(self, mask_values: bool = True) -> dict[str, str]:
        """List all environment variables, optionally masking values.

        Args:
            mask_values: If True, mask values showing only first 3 chars

        Returns:
            Dictionary of environment variables (possibly masked)
        """
        settings = self.load()
        if not mask_values:
            return settings.env.copy()
        return {k: self._mask_value(v) for k, v in settings.env.items()}

    @staticmethod
    def _mask_value(value: str) -> str:
        """Mask a value for display (show first 3 chars + ***).

        Args:
            value: Value to mask

        Returns:
            Masked value
        """
        if len(value) <= 3:
            return "***"
        return value[:3] + "***"

    def _validate_permissions(self, settings: Optional[PflowSettings] = None) -> None:
        """Validate file permissions and warn if insecure (defense-in-depth).

        Checks if settings file has world/group-readable permissions when it
        contains secrets. This is a safety check in case chmod fails or user
        manually changes permissions.

        Args:
            settings: Optional pre-loaded settings to avoid recursion during load()
        """
        if not self.settings_path.exists():
            return

        try:
            # Check current permissions
            file_stat = os.stat(self.settings_path)
            mode = stat.S_IMODE(file_stat.st_mode)

            # Check if world or group readable
            if mode & (stat.S_IROTH | stat.S_IRGRP):
                # Only warn if file contains secrets
                try:
                    # Use provided settings or load (avoid recursion)
                    if settings is None:
                        settings = self.load()
                    if settings.env:
                        logger.warning(
                            f"Settings file {self.settings_path} contains secrets "
                            f"but has insecure permissions {oct(mode)}. "
                            f"Run: chmod 600 {self.settings_path}"
                        )
                except Exception as e:
                    # If we can't check, don't warn (defense-in-depth: validation failure is non-critical)
                    logger.debug(f"Permission validation failed during env check: {e}")
        except Exception as e:
            # Don't let validation errors break functionality (defense-in-depth: never breaks operations)
            logger.debug(f"Permission validation failed: {e}")
