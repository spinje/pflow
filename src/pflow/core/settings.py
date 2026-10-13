"""Settings management for pflow with environment variable override support."""

import json
import logging
import os
import stat
import sys
import tempfile
import threading
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)


# Settings files already warned about insecure permissions in this process: one run loads settings from
# several places (and Retention once more at finalize), and the warning is per file, not per load.
_INSECURE_PERMISSIONS_WARNED: set[Path] = set()
_INSECURE_PERMISSIONS_LOCK = threading.Lock()  # concurrent MCP requests build separate managers

# Valid output modes for probe output (used by settings validator and CLI)
OUTPUT_MODES: list[str] = ["smart", "structure", "full"]


class NodeFilterSettings(BaseModel):
    """Node filtering configuration."""

    model_config = ConfigDict(extra="allow")

    allow: list[str] = Field(default_factory=lambda: ["*"])  # Default: allow all
    deny: list[str] = Field(default_factory=list)


class RegistrySettings(BaseModel):
    """Registry-specific settings."""

    model_config = ConfigDict(extra="allow")

    nodes: NodeFilterSettings = Field(default_factory=NodeFilterSettings)
    output_mode: str = Field(
        default="smart",
        description="Output mode for probe: smart (show values with truncation), "
        "structure (paths only), or full (all values, no filtering)",
    )

    @field_validator("output_mode")
    @classmethod
    def validate_output_mode(cls, v: str) -> str:
        """Validate output_mode is valid."""
        if v not in OUTPUT_MODES:
            raise ValueError(f"Invalid output_mode: {v}. Must be one of: {', '.join(OUTPUT_MODES)}")
        return v


class RuntimeSettings(BaseModel):
    """Runtime execution configuration.

    These settings control workflow execution behavior.
    """

    model_config = ConfigDict(extra="allow")

    template_resolution_mode: str = Field(
        default="strict", description="Default template resolution mode: strict or permissive"
    )
    trace_retention_days: int = Field(
        default=14,
        ge=0,
        description="Days a trace is kept in ~/.pflow/debug before Retention removes it (protected traces are "
        "kept whatever their age); 0 keeps every trace. Read by runtime/trace_retention.retention_days, where "
        "PFLOW_TRACE_RETENTION_DAYS overrides it for one process.",
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

    Resolution order:
    - LLM nodes:  workflow params → default_model → auto-detect → error
    - discovery:  discovery_model → default_model → auto-detect → fallback
    - filtering:  filtering_model → default_model → auto-detect → fallback

    The default_model serves as a shared fallback for all features when
    feature-specific settings are not configured.

    Examples:
        # Set default model for everything (LLM nodes, discovery, filtering)
        {"default_model": "gemini/gemini-3-flash-preview"}

        # Override just discovery while using default for others
        {
            "default_model": "gemini/gemini-3-flash-preview",
            "discovery_model": "anthropic/claude-sonnet-4-5"
        }
    """

    model_config = ConfigDict(extra="allow")

    default_model: str | None = Field(
        default=None,
        description="Default model for all pflow LLM usage. "
        "Used by LLM nodes, discovery, and filtering when specific settings are not set.",
    )
    discovery_model: str | None = Field(
        default=None,
        description="Model for discovery commands. Overrides default_model for discovery only.",
    )
    filtering_model: str | None = Field(
        default=None,
        description="Model for smart field filtering. Overrides default_model for filtering only.",
    )
    tts_model: str = Field(
        default="gemini-3.1-flash-tts-preview",
        description="TTS model for `pflow ui --say` narration.",
    )
    tts_voice: str = Field(
        default="Kore",
        description="TTS voice name for `pflow ui --say` narration.",
    )


class PflowSettings(BaseModel):
    """Main settings configuration.

    Every settings model keeps keys it does not declare (``extra="allow"``): a typo never fails the whole file
    and survives a save, so Retention can see it (``unknown_settings_keys``); ``settings show`` omits them."""

    model_config = ConfigDict(extra="allow")

    version: str = Field(default="1.0.0")
    registry: RegistrySettings = Field(default_factory=RegistrySettings)
    runtime: RuntimeSettings = Field(default_factory=RuntimeSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    env: dict[str, str] = Field(default_factory=dict)


def _first_insecure_warning(settings_path: Path) -> bool:
    """Whether this process has not yet warned about ``settings_path``'s permissions (and now has)."""
    with _INSECURE_PERMISSIONS_LOCK:
        if settings_path in _INSECURE_PERMISSIONS_WARNED:
            return False
        _INSECURE_PERMISSIONS_WARNED.add(settings_path)
        return True


def unknown_settings_keys(model: BaseModel, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    """Every key no settings model declares, at every level, as ``(path, value)`` — e.g.
    ``(("llm", "trace_retention_day"), 0)``."""
    found: list[tuple[tuple[str, ...], Any]] = [
        ((*path, key), value) for key, value in (model.model_extra or {}).items()
    ]
    for name in type(model).model_fields:
        section = getattr(model, name)
        if isinstance(section, BaseModel):
            found += unknown_settings_keys(section, (*path, name))
    return found


class SettingsManager:
    """Manages pflow settings with environment variable override support."""

    def __init__(self, settings_path: Path | None = None):
        self.settings_path = settings_path or Path.home() / ".pflow" / "settings.json"
        self._settings: PflowSettings | None = None
        # Why the file failed to load (defaults are in use), else None. ``save()`` refuses while it is set:
        # writing the defaults back would wipe the user's file.
        self.load_error: str | None = None
        # RLock for thread-safe operations (reentrant since set_env calls load)
        self._lock = threading.RLock()

    def load(self) -> PflowSettings:
        """Load settings with environment variable overrides."""
        with self._lock:
            if self._settings is None:
                self._settings = self._load_from_file()
                # Validate permissions after loading (defense-in-depth)
                self._validate_permissions(self._settings)
            settings = self._settings
            # Always (re)apply env overrides to handle toggling without restart
            self._apply_env_overrides(settings)
            return settings

    def reload(self) -> PflowSettings:
        """Force reload settings from file."""
        with self._lock:
            self._settings = None
        return self.load()

    def _load_from_file(self) -> PflowSettings:
        """Load settings from file or return defaults. Only a file that does not exist means defaults; any
        other fault (unreadable, corrupt, invalid) sets ``load_error`` — never ``Path.exists()``, which reads a
        permission fault as "absent" on Python 3.14."""
        self.load_error = None
        try:
            with open(self.settings_path, encoding="utf-8") as f:
                data = json.load(f)
            return PflowSettings(**data)
        except (FileNotFoundError, NotADirectoryError):
            return PflowSettings()
        except Exception as e:
            self.load_error = str(e)
            logger.warning(f"Failed to load settings from {self.settings_path} ({e}); using defaults")
            return PflowSettings()

    def _apply_env_overrides(self, settings: PflowSettings) -> None:
        """Apply environment variable overrides."""
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

    def should_include_node(self, node_name: str, node_module: str | None = None) -> bool:
        """Check if a node should be included based on settings.

        Args:
            node_name: The node name (e.g., "read-file", "shell")
            node_module: Optional module path (e.g., "pflow.nodes.file.read_file")

        Returns:
            True if the node should be included, False otherwise.
        """
        settings = self.load()

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
    def _build_match_candidates(node_name: str, node_module: str | None) -> list[str]:
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

    def save(self, settings: PflowSettings | None = None) -> None:
        """Save settings to file with atomic operations and secure permissions.

        Refuses when the file failed to load (``load_error``): the in-memory settings are defaults, and
        writing them would erase the user's file. A fresh manager that never loaded (``settings init`` /
        ``reset``) saves normally."""
        if settings is None:
            settings = self.load()
        if self.load_error is not None:
            from pflow.core.user_errors import UserFriendlyError

            raise UserFriendlyError(
                "Settings file not saved",
                f"{self.settings_path} could not be loaded ({self.load_error}), so saving now would replace it "
                "with defaults.",
                suggestions=[
                    f"Fix the file by hand: {self.settings_path}",
                    "Or start over with 'pflow settings reset' (replaces the file with defaults).",
                ],
            )

        self.settings_path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write pattern: write to temp file, then replace
        temp_fd, temp_path = tempfile.mkstemp(dir=self.settings_path.parent, prefix=".settings.", suffix=".tmp")

        try:
            with open(temp_fd, "w", encoding="utf-8") as f:
                json.dump(settings.model_dump(), f, indent=2)

            # Atomic replace (works on all platforms)
            os.replace(temp_path, self.settings_path)

            # Set restrictive permissions (owner read/write only)
            os.chmod(self.settings_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600

            # Clear cache to force reload on next access (protected by lock)
            with self._lock:
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

    def get_env(self, key: str, default: str | None = None) -> str | None:
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
            mask_values: If True, mask each value (``_mask_value``)

        Returns:
            Dictionary of environment variables (possibly masked)
        """
        settings = self.load()
        if not mask_values:
            return settings.env.copy()
        return {k: self._mask_value(v) for k, v in settings.env.items()}

    @staticmethod
    def _mask_value(value: str) -> str:
        """Mask a value for display: its length only, never any of its characters (a prefix narrows a guess)."""
        return f"*** ({len(value)} chars)"

    def _validate_permissions(self, settings: PflowSettings | None = None) -> None:
        """Validate file permissions and warn if insecure (defense-in-depth).

        Checks if settings file has world/group-readable permissions when it
        contains secrets. This is a safety check in case chmod fails or user
        manually changes permissions.

        Args:
            settings: Optional pre-loaded settings to avoid recursion during load()
        """
        # POSIX permission bits are meaningless on Windows: st_mode always
        # reports group/other read on regular files, so this check would
        # warn every Windows user with secrets on every load — and the
        # `chmod 600` advice it gives is a no-op there. Windows ACLs are a
        # different mechanism entirely; skip the check.
        if sys.platform == "win32":
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
                    if settings.env and _first_insecure_warning(self.settings_path):
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
