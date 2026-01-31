"""Claude Code Agentic Node - AI-powered development assistant with schema-driven outputs.

This node integrates with Claude Code Python SDK to execute comprehensive development tasks.
Features a dynamic schema-driven output system where users provide an output schema that
gets converted to system prompt instructions, enabling structured outputs from Claude's
unstructured text generation.

Interface:
- Params: prompt: str  # The prompt to send to Claude (required)
- Params: output_schema: dict  # JSON schema for structured outputs (optional)
- Writes: shared["result"]: any  # Response - string or dict with schema keys
- Writes: shared["_schema_error"]: str  # Error message if JSON parsing fails (optional)
- Writes: shared["_claude_metadata"]: dict  # Execution metadata (cost, duration, usage, session_id)
- Params: cwd: str  # Working directory for Claude (default: os.getcwd())
- Params: model: str  # Claude model identifier (default: claude-sonnet-4-5)
- Params: allowed_tools: list  # Permitted tools (default: None = all tools including Task for subagents)
- Params: max_turns: int  # Maximum conversation turns (default: 50)
- Params: max_thinking_tokens: int  # Maximum tokens for reasoning (default: 8000)
- Params: timeout: int  # Execution timeout in seconds (default: 300; max: 3600)
- Params: system_prompt: str  # System instructions for Claude (optional)
- Params: resume: str  # Session ID to resume a previous conversation (optional)
- Params: sandbox: dict  # Sandbox configuration for command isolation (optional)
    - enabled: bool  # Enable sandbox mode (default: false)
    - autoAllowBashIfSandboxed: bool  # Auto-allow bash when sandboxed (default: false)
    - excludedCommands: list  # Commands that bypass sandbox (e.g., ["docker"])
    - allowUnsandboxedCommands: bool  # Allow model to request unsandboxed execution
    - network: dict  # Network settings (allowLocalBinding, allowUnixSockets, etc.)

Note: When output_schema is provided, the result is a dict with schema keys.
Access values as shared["result"]["key"] in templates: ${node.result.key}
Session ID is available at ${node._claude_metadata.session_id} for chaining sessions.
"""

import asyncio
import json
import logging
import os
import re
from typing import Any, Optional

from pflow.pocketflow import Node

# Import Claude Agent SDK (renamed from Claude Code SDK)
try:
    from claude_agent_sdk import ClaudeAgentOptions, query
    from claude_agent_sdk.types import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

    # Try to import exceptions, but make them optional for test environments
    try:
        from claude_agent_sdk import (
            ClaudeSDKError,
            CLIConnectionError,
            CLINotFoundError,
            ProcessError,
        )
    except ImportError:
        # In test environments, these might not be available
        CLINotFoundError = None
        CLIConnectionError = None
        ProcessError = None
        ClaudeSDKError = None
except ImportError as e:
    raise ImportError("Claude Agent SDK is not installed. Install with: pip install claude-agent-sdk") from e

logger = logging.getLogger(__name__)

# Security patterns for bash command validation
DANGEROUS_BASH_PATTERNS = [
    r"rm\s+-rf\s+/",  # Recursive root deletion
    r"rm\s+-rf\s+~",  # Home directory deletion
    r":\(\)\{\s*:\|\s*:\s*&\s*\};",  # Fork bomb
    r">\s*/dev/sd",  # Disk overwrite
    r"chmod\s+777\s+/",  # Overly permissive root
    r"curl.*\|.*sh",  # Remote code execution
    r"wget.*\|.*bash",  # Remote code execution
]

# Restricted directories that should not be used as working directories
RESTRICTED_DIRECTORIES = ["/", "/etc", "/usr", "/bin", "/sbin", "/lib", "/sys", "/proc"]


class ClaudeCodeNode(Node):
    """Claude Code agentic super node for AI-assisted development tasks.

    This node integrates with Claude Code Python SDK to execute comprehensive development tasks.
    Features a dynamic schema-driven output system where users provide an output schema that
    gets converted to system prompt instructions, enabling structured outputs.

    Output Schema Format:
        Each field in the schema is a dict with "type" and "description" keys:
        - "type": One of "str", "int", "bool", "list", "dict"
        - "description": Human-readable description of the field

        Example: {"risk_level": {"type": "str", "description": "high/medium/low"},
                  "score": {"type": "int", "description": "Security score 1-10"}}

    Interface:
    - Params: prompt: str  # The prompt to send to Claude (required)
    - Params: output_schema: dict  # Schema for structured outputs (optional): {"field": {"type": "str", "description": "..."}}
    - Writes: shared["result"]: any  # Response - string without schema, dict with schema
    - Writes: shared["_schema_error"]: str  # Error message if JSON parsing fails (optional)
    - Writes: shared["_claude_metadata"]: dict  # Execution metadata
        - duration_ms: int  # Execution time in milliseconds
        - total_cost_usd: float  # Total cost in USD
        - session_id: str  # Session ID for resuming conversations
        - usage: dict  # Token usage information
            - input_tokens: int  # Number of input tokens
            - output_tokens: int  # Number of output tokens
            - cache_creation_input_tokens: int  # Cache creation tokens (if applicable)
            - cache_read_input_tokens: int  # Cache read tokens (if applicable)
    - Params: cwd: str  # Working directory for Claude (default: os.getcwd())
    - Params: model: str  # Claude model identifier (default: claude-sonnet-4-5)
    - Params: allowed_tools: list  # Permitted tools (default: None = all tools including Task for subagents)
    - Params: max_turns: int  # Maximum conversation turns (default: 50)
    - Params: max_thinking_tokens: int  # Maximum tokens for reasoning (default: 8000)
    - Params: timeout: int  # Execution timeout in seconds (default: 300; valid: 30-3600)
    - Params: system_prompt: str  # System instructions for Claude (optional)
    - Params: resume: str  # Session ID to resume a previous conversation (optional)
    - Params: sandbox: dict  # Sandbox configuration for command isolation (optional)
        - enabled: bool  # Enable sandbox mode (default: false)
        - autoAllowBashIfSandboxed: bool  # Auto-allow bash when sandboxed (default: false)
        - excludedCommands: list  # Commands that bypass sandbox (e.g., ["docker"])
        - allowUnsandboxedCommands: bool  # Allow model to request unsandboxed execution
        - network: dict  # Network settings (allowLocalBinding, allowUnixSockets, etc.)

    Authentication:
        The Claude Code SDK supports two authentication methods:

        1. API Key (Console billing):
           export ANTHROPIC_API_KEY=sk-ant-...
           Uses your Anthropic Console account for billing

        2. CLI Authentication (Claude Pro/Max subscription):
           claude auth login      # Interactive OAuth
           claude setup-token     # Long-lived token (requires subscription)
           Uses your Claude Pro/Max subscription entitlements

        The SDK automatically runs in headless mode using --output-format json
        and bypasses all permission prompts since workflows run autonomously.

    Note: Result type depends on schema usage:
    - Without schema: String response in ${node_id.result}
    - With schema (success): Dict with fields accessible via ${node_id.result.field_name}
    - With schema (parse failure): Falls back to string in ${node_id.result} with error in _schema_error

    Example:
        # Basic execution
        shared = {"prompt": "Write a fibonacci function"}
        node = ClaudeCodeNode()
        node.run(shared)  # Result in shared["result"] as string

        # With schema-driven output
        shared = {
            "prompt": "Review this code for security issues",
            "output_schema": {
                "risk_level": {"type": "str", "description": "high/medium/low"},
                "issues": {"type": "list", "description": "List of security issues"},
                "score": {"type": "int", "description": "Security score 1-10"},
                "needs_fix": {"type": "bool", "description": "True if critical issues found"}
            }
        }
        node = ClaudeCodeNode()
        node.run(shared)
        # Success: shared["result"] = {"risk_level": "low", "issues": [...], "score": 8, "needs_fix": False}
        # Access as: shared["result"]["risk_level"], shared["result"]["issues"], etc.
        # Parse failure: shared["result"] = raw_text_string, shared["_schema_error"] = error
    """

    def __init__(self) -> None:
        """Initialize with conservative retry settings for expensive API calls."""
        # Only 2 attempts total (1 initial + 1 retry) due to API cost
        super().__init__(max_retries=2, wait=1.0)

    def _validate_prompt(self, prompt: Any) -> str:
        """Validate prompt parameter."""
        if not prompt:
            raise ValueError("No prompt provided. Please specify a prompt in shared['prompt'] or params.")
        if not isinstance(prompt, str):
            raise TypeError(f"Prompt must be a string, got {type(prompt).__name__}")
        if len(prompt) > 10000:
            raise ValueError(f"Prompt too long ({len(prompt)} chars). Maximum 10000 characters allowed.")
        if not prompt.strip():
            raise ValueError("Prompt cannot be empty or whitespace only.")
        return prompt

    def _validate_schema(self, output_schema: Any) -> Optional[dict]:
        """Validate output schema parameter."""
        if not output_schema:
            return None
        if not isinstance(output_schema, dict):
            raise TypeError(f"Output schema must be a dict, got {type(output_schema).__name__}")

        # Validate schema keys are valid Python identifiers
        for key in output_schema:
            if not str(key).isidentifier():
                raise ValueError(f"Invalid schema key '{key}'. Keys must be valid Python identifiers.")

        # Check schema complexity
        if len(output_schema) > 50:
            raise ValueError(f"Schema too complex ({len(output_schema)} keys). Maximum 50 keys allowed.")
        return output_schema

    def _validate_cwd(self, cwd: Optional[str]) -> str:
        """Validate and normalize working directory."""
        if not cwd:
            return os.getcwd()

        cwd = os.path.expanduser(cwd)
        cwd = os.path.abspath(cwd)

        if not os.path.exists(cwd):
            raise ValueError(f"Working directory does not exist: {cwd}")
        if not os.path.isdir(cwd):
            raise ValueError(f"Working directory is not a directory: {cwd}")

        # Check for restricted directories
        normalized_path = os.path.normpath(cwd)
        if normalized_path in RESTRICTED_DIRECTORIES:
            raise ValueError(f"Restricted directory: {cwd}")
        return cwd

    def _validate_tools(self, allowed_tools: Optional[list]) -> Optional[list]:
        """Validate allowed tools list.

        If None or empty, all tools are available (SDK default).
        If provided, pass through to SDK without validation - let SDK handle unknown tools.
        """
        if not allowed_tools:
            return None  # All tools available
        if not isinstance(allowed_tools, list):
            raise TypeError(f"allowed_tools must be a list, got {type(allowed_tools).__name__}")
        return allowed_tools

    def _validate_max_turns(self, max_turns: Any) -> int:
        """Validate and convert max_turns parameter."""
        default_max_turns = 50
        if max_turns is None:
            return default_max_turns
        try:
            max_turns_int = int(max_turns)
            if max_turns_int < 1 or max_turns_int > 100:
                raise ValueError
            return max_turns_int
        except (ValueError, TypeError):
            raise ValueError(f"Invalid max_turns: {max_turns}. Must be integer between 1 and 100.") from None

    def _validate_max_thinking_tokens(self, max_thinking_tokens: Any) -> int:
        """Validate and convert max_thinking_tokens parameter."""
        default_tokens = 8000
        if max_thinking_tokens is None:
            return default_tokens
        try:
            tokens = int(max_thinking_tokens)
            if tokens < 1000 or tokens > 100000:
                raise ValueError
            return tokens
        except (ValueError, TypeError):
            raise ValueError(
                f"Invalid max_thinking_tokens: {max_thinking_tokens}. Must be integer between 1000 and 100000."
            ) from None

    def _validate_timeout(self, timeout: Any) -> int:
        """Validate and convert timeout parameter."""
        default_timeout = 300  # 5 minutes default
        if timeout is None:
            return default_timeout
        try:
            timeout_int = int(timeout)
            if timeout_int < 30 or timeout_int > 3600:
                raise ValueError
            return timeout_int
        except (ValueError, TypeError):
            raise ValueError(f"Invalid timeout: {timeout}. Must be integer between 30 and 3600 seconds.") from None

    def _validate_resume(self, resume: Any) -> Optional[str]:
        """Validate resume session ID parameter."""
        if not resume:
            return None
        if not isinstance(resume, str):
            raise TypeError(f"resume must be a string (session ID), got {type(resume).__name__}")
        return resume

    def _validate_sandbox(self, sandbox: Any) -> Optional[dict]:
        """Validate sandbox configuration parameter.

        Sandbox settings control command execution isolation via the Claude Agent SDK.
        See: https://platform.claude.com/docs/en/agent-sdk/python#sandbox-configuration

        Args:
            sandbox: Sandbox configuration dict or None

        Returns:
            Validated sandbox dict or None

        Raises:
            TypeError: If sandbox or nested values have wrong types
        """
        if not sandbox:
            return None
        if not isinstance(sandbox, dict):
            raise TypeError(f"sandbox must be a dict, got {type(sandbox).__name__}")

        # Type validation for known keys (pass through unknown for SDK forward compatibility)
        # Boolean fields
        bool_fields = ["enabled", "autoAllowBashIfSandboxed", "allowUnsandboxedCommands", "enableWeakerNestedSandbox"]
        for field in bool_fields:
            if field in sandbox and not isinstance(sandbox[field], bool):
                raise TypeError(f"sandbox['{field}'] must be bool")

        # Dict fields
        dict_fields = ["network", "ignoreViolations"]
        for field in dict_fields:
            if field in sandbox and not isinstance(sandbox[field], dict):
                raise TypeError(f"sandbox['{field}'] must be a dict")

        # List fields
        if "excludedCommands" in sandbox and not isinstance(sandbox["excludedCommands"], list):
            raise TypeError("sandbox['excludedCommands'] must be a list")

        return sandbox

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        """Prepare Claude Code execution parameters.

        Args:
            shared: Shared store containing prompt and optional schema

        Returns:
            Dictionary with prepared execution parameters

        Raises:
            ValueError: If required parameters are missing or invalid
        """
        # Validate prompt
        prompt = self._validate_prompt(self.params.get("prompt"))

        # Validate optional parameters
        output_schema = self._validate_schema(self.params.get("output_schema"))
        cwd = self._validate_cwd(self.params.get("cwd"))

        # Get model with fallback
        model = self.params.get("model", "claude-sonnet-4-5")

        # Validate tools (None = all tools available, including Task for subagents)
        allowed_tools = self._validate_tools(self.params.get("allowed_tools"))

        # Validate numeric parameters
        max_turns = self._validate_max_turns(self.params.get("max_turns", 50))
        max_thinking_tokens = self._validate_max_thinking_tokens(self.params.get("max_thinking_tokens", 8000))

        # Get system prompt
        system_prompt = self.params.get("system_prompt", "")

        # Session management
        resume = self._validate_resume(self.params.get("resume"))

        # Timeout (default 300s, configurable for long multi-agent tasks)
        timeout = self._validate_timeout(self.params.get("timeout"))

        # Sandbox configuration for command isolation
        sandbox = self._validate_sandbox(self.params.get("sandbox"))

        logger.info(f"Prepared Claude Code execution for prompt: {prompt[:100]}...")

        return {
            "prompt": prompt,
            "output_schema": output_schema,
            "cwd": cwd,
            "model": model,
            "allowed_tools": allowed_tools,
            "max_turns": max_turns,
            "max_thinking_tokens": max_thinking_tokens,
            "system_prompt": system_prompt,
            "resume": resume,
            "timeout": timeout,
            "sandbox": sandbox,
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Execute Claude Code using async-to-sync wrapper.

        NO try/except here - let exceptions bubble up for PocketFlow's retry mechanism!

        Args:
            prep_res: Prepared parameters from prep()

        Returns:
            Dictionary with execution results
        """
        logger.info(f"Executing Claude Code node with model: {prep_res['model']}")

        # Run async code in sync context using asyncio.run()
        # This creates a new event loop for each execution
        result = asyncio.run(self._exec_async(prep_res), debug=False)

        return result

    async def _exec_async(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        """Async implementation using Claude Code SDK.

        Args:
            prep_res: Prepared parameters

        Returns:
            Dictionary with results to be processed by post()
        """
        # Build the prompt
        prompt = self._build_prompt(prep_res)

        # Build system prompt with schema instructions if needed
        system_prompt = self._build_system_prompt(prep_res)

        # Build Claude Code options
        options = self._build_claude_options(prep_res, system_prompt)

        logger.debug(f"Using model: {prep_res['model']}, max_turns: {prep_res['max_turns']}")

        # Execute with timeout handling
        result = await self._execute_with_timeout(prompt, options, prep_res)
        return result

    def _build_claude_options(self, prep_res: dict[str, Any], system_prompt: str) -> ClaudeAgentOptions:
        """Build Claude Code options object.

        Args:
            prep_res: Prepared parameters
            system_prompt: System prompt to use

        Returns:
            ClaudeAgentOptions configured for execution
        """
        # Build base options
        options_kwargs: dict[str, Any] = {
            "model": prep_res["model"],
            "max_thinking_tokens": prep_res["max_thinking_tokens"],
            "system_prompt": system_prompt,
            "max_turns": prep_res["max_turns"],
            "cwd": prep_res["cwd"],
            "permission_mode": "bypassPermissions",  # Always bypass prompts in autonomous workflows
        }

        # Only pass allowed_tools if explicitly set (None = all tools including Task for subagents)
        if prep_res["allowed_tools"] is not None:
            options_kwargs["allowed_tools"] = prep_res["allowed_tools"]

        # Add session resumption if provided
        if prep_res["resume"]:
            options_kwargs["resume"] = prep_res["resume"]

        # Add sandbox configuration if provided
        if prep_res.get("sandbox") is not None:
            options_kwargs["sandbox"] = prep_res["sandbox"]

        return ClaudeAgentOptions(**options_kwargs)

    async def _execute_with_timeout(
        self, prompt: str, options: ClaudeAgentOptions, prep_res: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute Claude Code query with timeout handling.

        Args:
            prompt: The prompt to send
            options: Claude Code options
            prep_res: Prepared parameters

        Returns:
            Dictionary with execution results
        """
        # Use configurable timeout from prep_res
        timeout = prep_res["timeout"]

        # Handle timeout at asyncio level (SDK has no timeout parameter)
        timeout_context = getattr(asyncio, "timeout", None)
        if timeout_context is not None:
            # Python 3.11+
            async with timeout_context(timeout):
                return await self._run_claude_session(prompt, options, prep_res)
        else:
            # Python 3.10 fallback
            return await asyncio.wait_for(self._run_claude_session(prompt, options, prep_res), timeout=timeout)

    async def _run_claude_session(
        self, prompt: str, options: ClaudeAgentOptions, prep_res: dict[str, Any]
    ) -> dict[str, Any]:
        """Run the Claude Code session and process messages.

        Args:
            prompt: The prompt to send
            options: Claude Code options
            prep_res: Prepared parameters

        Returns:
            Dictionary with results
        """
        result_text = ""
        tool_uses = []
        message_count = 0
        metadata = {}
        progress_events = []  # Track streaming progress for tracing

        async for message in query(prompt=prompt, options=options):
            message_count += 1
            logger.debug(f"Received message {message_count}: type={type(message).__name__}")

            if isinstance(message, AssistantMessage):
                text_chunk, tools, events = self._process_assistant_message(message, result_text)
                result_text += text_chunk
                tool_uses.extend(tools)
                progress_events.extend(events)

            elif isinstance(message, ResultMessage):
                metadata = self._extract_metadata(message)
                progress_events.append(self._create_completion_event(metadata))

        # Log results
        self._log_session_results(tool_uses, result_text)

        # Return results to be processed by post()
        return {
            "result_text": result_text,
            "tool_uses": tool_uses,
            "output_schema": prep_res.get("output_schema"),
            "metadata": metadata,
            "progress_events": progress_events,
        }

    def _process_assistant_message(
        self, message: AssistantMessage, current_text: str
    ) -> tuple[str, list[dict], list[dict]]:
        """Process an assistant message and extract content.

        Args:
            message: The AssistantMessage to process
            current_text: Current accumulated text

        Returns:
            Tuple of (text_chunk, tool_uses, progress_events)
        """
        text_chunk = ""
        tool_uses = []
        progress_events = []

        for block in message.content:
            if isinstance(block, TextBlock):
                block_text = block.text
                text_chunk += block_text
                logger.debug(f"  TextBlock ({len(block_text)} chars): {block_text[:100]}...")

                # Track text generation progress
                progress_events.append({
                    "type": "text_chunk",
                    "length": len(block_text),
                    "total_length": len(current_text) + len(text_chunk),
                    "preview": block_text[:100] if block_text else "",
                })

            elif isinstance(block, ToolUseBlock):
                tool_uses.append({
                    "name": block.name,
                    "input": block.input,
                })
                logger.debug(f"  ToolUseBlock: {block.name}")

                # Track tool usage progress
                progress_events.append({
                    "type": "tool_use",
                    "tool": block.name,
                    "input_preview": str(block.input)[:200] if block.input else "",
                })

        return text_chunk, tool_uses, progress_events

    def _extract_metadata(self, message: ResultMessage) -> dict[str, Any]:
        """Extract metadata from a ResultMessage.

        Args:
            message: The ResultMessage containing metadata

        Returns:
            Dictionary with extracted metadata
        """
        metadata = {
            "total_cost_usd": getattr(message, "total_cost_usd", None),
            "duration_ms": getattr(message, "duration_ms", None),
            "duration_api_ms": getattr(message, "duration_api_ms", None),
            "num_turns": getattr(message, "num_turns", None),
            "session_id": getattr(message, "session_id", None),
            "usage": getattr(message, "usage", None),
        }
        logger.info(
            f"Captured metadata: cost=${metadata['total_cost_usd']}, "
            f"duration={metadata['duration_ms']}ms, turns={metadata['num_turns']}"
        )
        return metadata

    def _create_completion_event(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """Create a completion event from metadata.

        Args:
            metadata: The metadata dictionary

        Returns:
            Completion event dictionary
        """
        return {
            "type": "completion",
            "cost": metadata.get("total_cost_usd"),
            "duration_ms": metadata.get("duration_ms"),
            "turns": metadata.get("num_turns"),
        }

    def _log_session_results(self, tool_uses: list[dict], result_text: str) -> None:
        """Log the results of a Claude session.

        Args:
            tool_uses: List of tools used
            result_text: The response text
        """
        # Log tool uses for audit
        if tool_uses:
            logger.info(f"Claude Code used {len(tool_uses)} tools")
            for tool in tool_uses[:5]:  # Log first 5 tools
                logger.debug(f"Tool: {tool['name']}")

        # Log response for debugging
        if result_text:
            logger.debug(f"Received response text ({len(result_text)} chars): {result_text[:200]}...")
        else:
            logger.warning("No response text received from Claude Code")

    def post(self, shared: dict[str, Any], prep_res: dict[str, Any], exec_res: dict[str, Any]) -> str:
        """Store results in shared store and determine next action.

        Args:
            shared: Shared store
            prep_res: Preparation results
            exec_res: Execution results from exec()

        Returns:
            Always "default" due to planner limitations
        """
        # Store results based on schema or as raw text
        self._store_results(shared, exec_res)

        return "default"

    def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> None:
        """Handle execution failures after all retries exhausted.

        Transform SDK exceptions into user-friendly messages.

        Args:
            prep_res: Preparation results
            exc: The exception that caused failure

        Raises:
            ValueError: With user-friendly error message and remediation steps
        """
        error_msg = str(exc)
        exc_type = type(exc).__name__

        logger.error(f"Claude Code execution failed: {error_msg}", exc_info=True)

        # Handle specific SDK exceptions (check if exception classes are available)
        if (CLINotFoundError is not None and isinstance(exc, CLINotFoundError)) or "CLINotFoundError" in exc_type:
            raise ValueError(
                "Claude Code CLI not installed. Install with: npm install -g @anthropic-ai/claude-code\n"
                f"Original error: {error_msg}"
            ) from None

        if (CLIConnectionError is not None and isinstance(exc, CLIConnectionError)) or "CLIConnectionError" in exc_type:
            raise ValueError(
                "Failed to connect to Claude Code. Check authentication with: claude doctor\n"
                "If not authenticated, run: claude auth login\n"
                f"Original error: {error_msg}"
            ) from None

        if (ProcessError is not None and isinstance(exc, ProcessError)) or "ProcessError" in exc_type:
            # Extract exit code if available
            exit_code = getattr(exc, "exit_code", "unknown")
            stderr = getattr(exc, "stderr", "")
            raise ValueError(
                f"Claude Code process failed (exit code {exit_code})\n"
                f"Error output: {stderr}\n"
                f"Original error: {error_msg}"
            ) from None

        # Handle timeout
        if isinstance(exc, asyncio.TimeoutError):
            timeout = prep_res.get("timeout", 300)
            raise ValueError(  # noqa: TRY004 - This is a timeout error, not a type error
                f"Claude Code execution timed out after {timeout} seconds. "
                "The task may be too complex or the system may be slow. "
                "Consider increasing timeout or breaking the task into smaller parts."
            ) from None

        # Handle rate limiting
        if "rate limit" in error_msg.lower() or "429" in error_msg:
            raise ValueError(
                f"Claude API rate limit exceeded. Please wait a moment and try again.\nOriginal error: {error_msg}"
            ) from None

        # Generic error
        raise ValueError(
            f"Claude Code execution failed after {self.max_retries} attempts.\n"
            f"Error type: {exc_type}\n"
            f"Error message: {error_msg}\n"
            "Suggestions:\n"
            "- Check your internet connection\n"
            "- Verify Claude CLI is authenticated: claude doctor\n"
            "- Try a simpler task to isolate the issue"
        ) from None

    def _build_prompt(self, prep_res: dict[str, Any]) -> str:
        """Build the prompt for Claude Code.

        Args:
            prep_res: Prepared parameters

        Returns:
            Formatted prompt string
        """
        prompt = prep_res["prompt"]
        output_schema = prep_res.get("output_schema")

        # Build base prompt
        prompt_parts = []

        # If there's a schema, be very direct about JSON output requirement
        if output_schema:
            prompt_parts.append("RESPOND WITH JSON ONLY. Complete the following task and output the result as JSON:")
            prompt_parts.append("")

        prompt_parts.append(prompt)

        # If there's a schema, remind again at the end
        if output_schema:
            prompt_parts.append("\nREMEMBER: Output JSON only, no explanatory text.")

        return "\n".join(prompt_parts)

    def _build_system_prompt(self, prep_res: dict[str, Any]) -> str:
        """Build system prompt, merging schema instructions if needed.

        Args:
            prep_res: Prepared parameters

        Returns:
            System prompt with schema instructions prepended if applicable
        """
        prompts = []

        # Add schema instructions if schema provided
        if prep_res["output_schema"]:
            schema_prompt = self._build_schema_prompt(prep_res["output_schema"])
            prompts.append(schema_prompt)

        # Add user's system prompt
        if prep_res["system_prompt"]:
            prompts.append(prep_res["system_prompt"])

        return "\n\n".join(prompts) if prompts else ""

    def _build_schema_prompt(self, output_schema: dict[str, dict]) -> str:
        """Convert output schema to JSON format instructions.

        This is the core innovation - converting schema to prompt instructions.

        Args:
            output_schema: Schema dictionary with keys and type/description

        Returns:
            Prompt instructions for structured JSON output
        """
        if not output_schema:
            return ""

        # Build JSON template
        json_template = {}
        descriptions = []

        for key, config in output_schema.items():
            type_str = config.get("type", "str")
            desc = config.get("description", f"Value for {key}")

            # Add to template
            json_template[key] = f"<{type_str}: {desc}>"
            descriptions.append(f"  - {key}: {desc}")

        # Create instruction prompt - MUST output JSON ONLY
        prompt = (
            "YOU MUST RESPOND WITH JSON ONLY.\n\n"
            "DO NOT output any preliminary text like 'I'll analyze...' or 'Let me examine...'.\n"
            "DO NOT explain what you're doing.\n"
            "ONLY output a single JSON code block with your analysis results.\n\n"
            "Required JSON structure with these EXACT keys:\n"
            f"{json.dumps(json_template, indent=2)}\n\n"
            "Your COMPLETE response should be:\n"
            "```json\n"
            "{\n"
            '  "key1": actual_value,\n'
            '  "key2": [actual_values]\n'
            "}\n"
            "```\n\n"
            "Field descriptions:\n" + "\n".join(descriptions) + "\n\n"
            "START YOUR RESPONSE WITH ```json AND END WITH ```\n"
            "NO OTHER TEXT ALLOWED."
        )

        return prompt

    def _store_results(self, shared: dict[str, Any], exec_res: dict[str, Any]) -> None:
        """Store results in shared store.

        When schema is provided:
        - Success: shared["result"] = dict with parsed JSON values
        - Failure: shared["result"] = raw_text, shared["_schema_error"] = error

        When no schema:
        - shared["result"] = response_text

        Also stores standardized LLM usage data for tracing and tool usage details.

        Args:
            shared: Shared store to write results to
            exec_res: Execution results containing result_text, output_schema, metadata, and tool_uses
        """
        result_text = exec_res.get("result_text", "")
        output_schema = exec_res.get("output_schema")
        metadata = exec_res.get("metadata", {})
        tool_uses = exec_res.get("tool_uses", [])
        progress_events = exec_res.get("progress_events", [])

        # Store progress events for trace visibility (if any)
        if progress_events:
            shared["_claude_progress"] = progress_events
            logger.debug(f"Stored {len(progress_events)} progress events for tracing")

        # Store metadata in BOTH formats for compatibility
        if metadata:
            # Keep original format for backward compatibility
            shared["_claude_metadata"] = metadata

            # Store in standardized llm_usage format for tracing
            usage = metadata.get("usage", {})

            # Store token counts separately - do NOT aggregate cache tokens into input_tokens
            base_input = usage.get("input_tokens", 0)
            cache_creation = usage.get("cache_creation_input_tokens", 0)
            cache_read = usage.get("cache_read_input_tokens", 0)
            total_output = usage.get("output_tokens", 0)

            shared["llm_usage"] = {
                "model": self.params.get("model", "claude-sonnet-4-5"),
                "input_tokens": base_input,  # Only non-cached input tokens
                "output_tokens": total_output,
                "total_tokens": base_input + total_output,
                "cache_creation_input_tokens": cache_creation,  # Keep breakdown for visibility
                "cache_read_input_tokens": cache_read,  # Keep breakdown for visibility
                # Additional Claude Code specific metrics
                # NOTE: total_cost_usd is the ACTUAL cost from Claude Code
                # The metrics system may calculate a different cost based on token counts
                "total_cost_usd": metadata.get("total_cost_usd"),
                "duration_ms": metadata.get("duration_ms"),
                "duration_api_ms": metadata.get("duration_api_ms"),
                "num_turns": metadata.get("num_turns"),
                "session_id": metadata.get("session_id"),
            }

            if metadata.get("total_cost_usd"):
                logger.info(f"Claude Code execution cost: ${metadata['total_cost_usd']}")
        else:
            # Empty dict per spec when usage unavailable
            shared["llm_usage"] = {}

        # Store tool usage for trace visibility
        if tool_uses:
            shared["_claude_tools"] = [
                {
                    "name": tool["name"],
                    "input_summary": str(tool.get("input", ""))[:500],  # Truncated for storage
                }
                for tool in tool_uses
            ]
            logger.debug(f"Stored {len(tool_uses)} tool uses for tracing")

        # If no result text, store empty string
        if not result_text:
            shared["result"] = ""
            return

        # If no schema, store text directly
        if not output_schema:
            shared["result"] = result_text
            return

        # Try to extract and parse JSON
        json_data = self._extract_json(result_text)

        if json_data:
            # Successfully parsed JSON - create result dict with schema keys
            result_dict = {}
            for key in output_schema:
                if key in json_data:
                    result_dict[key] = json_data[key]
                else:
                    # Missing key - store None
                    result_dict[key] = None
                    logger.warning(f"Schema key '{key}' not found in JSON response")

            # Store the parsed dict in result
            shared["result"] = result_dict
            logger.info(f"Successfully parsed JSON with {len(output_schema)} schema values")
        else:
            # Failed to parse JSON - fallback to raw text
            shared["result"] = result_text
            shared["_schema_error"] = "Failed to parse JSON from response. Raw text stored in result"
            logger.warning("Could not extract JSON from response, stored raw text in result")

    def _extract_json(self, text: str) -> Optional[dict]:
        """Extract JSON from Claude's response with multiple strategies.

        Args:
            text: Response text that may contain JSON

        Returns:
            Parsed JSON dictionary or None if extraction fails
        """
        if not text:
            return None

        # Try extraction strategies in order of likelihood
        strategies = [
            self._extract_json_from_code_block,
            self._extract_json_from_raw_object,
            self._extract_json_from_last_brace,
        ]

        for strategy in strategies:
            result = strategy(text)
            if result is not None:
                return result

        return None  # Failed to extract JSON

    def _extract_json_from_code_block(self, text: str) -> Optional[dict]:
        """Extract JSON from markdown code blocks.

        Args:
            text: Response text that may contain code blocks

        Returns:
            Parsed JSON dictionary or None if extraction fails
        """
        code_block_pattern = r"```(?:json)?\s*\n(.*?)\n```"
        matches = re.findall(code_block_pattern, text, re.DOTALL)

        for match in matches:
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                continue

        return None

    def _extract_json_from_raw_object(self, text: str) -> Optional[dict]:
        """Extract raw JSON objects from text.

        Args:
            text: Response text that may contain raw JSON

        Returns:
            Parsed JSON dictionary or None if extraction fails
        """
        json_pattern = r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}"
        matches = re.findall(json_pattern, text)

        for match in matches:
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                continue

        return None

    def _extract_json_from_last_brace(self, text: str) -> Optional[dict]:
        """Extract JSON by finding the last opening brace and its matching close.

        Args:
            text: Response text that may contain JSON

        Returns:
            Parsed JSON dictionary or None if extraction fails
        """
        try:
            start = text.rfind("{")
            if start == -1:
                return None

            depth = 0
            for i, char in enumerate(text[start:], start):
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        potential_json = text[start : i + 1]
                        return json.loads(potential_json)
        except Exception as e:
            logger.debug(f"Failed to extract JSON using last brace method: {e}")

        return None
