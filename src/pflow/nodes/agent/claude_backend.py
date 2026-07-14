"""Claude Agent SDK adapter for the unified agent node."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

from pflow.nodes.agent.backend import AgentResult
from pflow.nodes.agent.schema_validation import (
    CLAUDE_PARAMS,
    SHARED_PARAMS,
    is_compiler_source_line_sidecar,
    validate_claude_max_thinking_tokens,
    validate_claude_max_turns,
    validate_claude_sandbox,
    validate_claude_tool_list,
)

try:
    from claude_agent_sdk import ClaudeAgentOptions, query
    from claude_agent_sdk.types import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

    ClaudeSDKError: type[Exception] | None
    CLIConnectionError: type[Exception] | None
    CLINotFoundError: type[Exception] | None
    ProcessError: type[Exception] | None
    try:
        from claude_agent_sdk import ClaudeSDKError as _ClaudeSDKError
        from claude_agent_sdk import CLIConnectionError as _CLIConnectionError
        from claude_agent_sdk import CLINotFoundError as _CLINotFoundError
        from claude_agent_sdk import ProcessError as _ProcessError

        ClaudeSDKError = _ClaudeSDKError
        CLIConnectionError = _CLIConnectionError
        CLINotFoundError = _CLINotFoundError
        ProcessError = _ProcessError
    except ImportError:
        ClaudeSDKError = None
        CLIConnectionError = None
        CLINotFoundError = None
        ProcessError = None
except ImportError as exc:
    raise ImportError("Claude Agent SDK is not installed. Install with: pip install claude-agent-sdk") from exc

_resolved_annotations = getattr(ResultMessage, "__annotations__", {})
if not isinstance(_resolved_annotations, dict) or "structured_output" not in _resolved_annotations:
    raise ImportError(
        "claude_agent_sdk.types.ResultMessage has no 'structured_output' field. "
        "pflow's Claude backend requires claude-agent-sdk>=0.2.82 with native structured output support. "
        "Got an incompatible SDK version."
    )

logger = logging.getLogger(__name__)
_AUTH_ERROR_MARKERS = (
    "invalid api key",
    "authentication_error",
    "authentication error",
    "run /login",
    "unauthorized",
    "credit balance",
    "api_error_status=401",
    "api_error_status=403",
)


def _claude_token_fields(usage: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize Claude cache fields to inclusive pflow input tokens."""
    base_input = usage.get("input_tokens", 0) or 0
    cache_creation = usage.get("cache_creation_input_tokens", 0) or 0
    cache_read = usage.get("cache_read_input_tokens", 0) or 0
    return {
        "input_tokens": base_input + cache_creation + cache_read,
        "uncached_input_tokens": base_input,
        "cache_creation_input_tokens": cache_creation,
        "cache_read_input_tokens": cache_read,
        "input_token_accounting": "split_cache_fields",
    }


class ClaudeBackend:
    """Run agent turns through the Claude Agent SDK."""

    default_model: str | None = "claude-sonnet-4-5"
    max_retries = 2

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        authored_params = {key for key in params if not is_compiler_source_line_sidecar(key, params)}
        invalid = sorted(authored_params - (SHARED_PARAMS | CLAUDE_PARAMS))
        if invalid:
            raise ValueError(f"{invalid[0]!r} is not valid for backend 'claude'")
        max_turns = validate_claude_max_turns(params.get("max_turns"))
        if params.get("output_schema") is not None and max_turns < 2:
            raise ValueError(
                f"max_turns must be >= 2 when output_schema is set (got {max_turns}). "
                "Structured output requires the agent to take at least one turn beyond producing "
                "the final response. Set max_turns to 2 or higher (default is typically sufficient)."
            )
        return {
            "allowed_tools": validate_claude_tool_list(params.get("allowed_tools"), "allowed_tools"),
            "disallowed_tools": validate_claude_tool_list(params.get("disallowed_tools"), "disallowed_tools"),
            "max_turns": max_turns,
            "max_thinking_tokens": validate_claude_max_thinking_tokens(params.get("max_thinking_tokens")),
            "sandbox": validate_claude_sandbox(params.get("sandbox")),
        }

    def run(self, prompt: str, options: dict[str, Any]) -> AgentResult:
        system_prompt = options.get("system_prompt") or ""
        sdk_options = self._build_claude_options(options, system_prompt)
        logger.debug("Using model: %s, max_turns: %s", options["model"], options["max_turns"])
        return asyncio.run(self._execute_with_timeout(prompt, sdk_options, options), debug=False)

    def continuation_options(self, previous: AgentResult, options: dict[str, Any]) -> dict[str, Any] | None:
        session_id = previous.metadata.get("session_id")
        if not session_id:
            return None
        continuation = options.copy()
        continuation["resume"] = session_id
        return continuation

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

        # Only pass disallowed_tools if explicitly set (None = no restrictions)
        if prep_res.get("disallowed_tools") is not None:
            options_kwargs["disallowed_tools"] = prep_res["disallowed_tools"]

        # Add session resumption if provided
        if prep_res["resume"]:
            options_kwargs["resume"] = prep_res["resume"]

        # Native structured output: SDK translates this to --json-schema CLI flag.
        # subprocess_cli.py only wires the exact json_schema wrapper shape.
        if prep_res.get("output_schema"):
            options_kwargs["output_format"] = {
                "type": "json_schema",
                "schema": prep_res["output_schema"],
            }

        # Add sandbox configuration if provided
        if prep_res.get("sandbox") is not None:
            options_kwargs["sandbox"] = prep_res["sandbox"]

        # Default (use_api_key=False): blank ANTHROPIC_API_KEY for THIS subprocess
        # only, so the Claude CLI uses the Pro/Max subscription instead of API/
        # Console billing. The SDK merges options.env OVER the inherited os.environ
        # (subprocess_cli.py), so we must OVERRIDE the key with an empty string —
        # omitting it leaves the inherited (or pflow settings-injected) key intact,
        # since a dict merge cannot delete an inherited key. os.environ is untouched,
        # so a sibling llm node still reads the real key for LiteLLM. See issue #455.
        if not prep_res.get("use_api_key"):
            options_kwargs["env"] = {"ANTHROPIC_API_KEY": ""}

        return ClaudeAgentOptions(**options_kwargs)

    async def _execute_with_timeout(
        self, prompt: str, options: ClaudeAgentOptions, prep_res: dict[str, Any]
    ) -> AgentResult:
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
    ) -> AgentResult:
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
        structured_output: Any = None
        is_error_from_sdk = False
        sdk_exception_text: str | None = None
        api_error_status: int | None = None

        try:
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
                    if message.result and not result_text:
                        result_text = message.result
                    structured_output = message.structured_output
                    is_error_from_sdk = is_error_from_sdk or message.is_error
                    # HTTP status of an API-level error (e.g. 401/403 auth). The
                    # SDK drops this from the exception it raises, so capture it
                    # here while the ResultMessage is in scope (#455).
                    api_error_status = getattr(message, "api_error_status", None) or api_error_status
        except Exception as exc:
            # The SDK pairs ``ResultMessage(is_error=True)`` with a non-zero CLI
            # exit raised as ``ProcessError``. That single class of exception is
            # the same signal expressed two ways — soft-fail semantics in post()
            # need the prior is_error state preserved instead of re-raising.
            #
            # Connection failures, missing CLI, timeouts and any other Exception
            # subclass must still reach exec_fallback so the user sees the
            # remediation message for that concrete failure mode.
            exc_type_name = type(exc).__name__
            is_process_error = (
                ProcessError is not None and isinstance(exc, ProcessError)
            ) or exc_type_name == "ProcessError"
            if not is_error_from_sdk or not is_process_error:
                enriched = self._enrich_error_result_exception(
                    exc, exc_type_name, is_error_from_sdk, result_text, api_error_status
                )
                if enriched is not None:
                    raise enriched from exc
                raise
            sdk_exception_text = str(exc)
            logger.warning("Claude Code SDK raised after an error ResultMessage: %s", sdk_exception_text)

        # Log results
        self._log_session_results(tool_uses, result_text)

        return AgentResult(
            result_text=result_text,
            tool_uses=tool_uses,
            metadata=metadata,
            progress_events=progress_events,
            structured_output=structured_output,
            is_error=is_error_from_sdk,
            error_text=sdk_exception_text,
        )

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
        usage = getattr(message, "usage", None) or {}
        token_fields = _claude_token_fields(usage)
        output_tokens = usage.get("output_tokens", 0) or 0
        metadata = {
            **token_fields,
            "output_tokens": output_tokens,
            "total_tokens": token_fields["input_tokens"] + output_tokens,
            "cost_usd": None,
            "api_equivalent_cost_usd": getattr(message, "total_cost_usd", None),
            "duration_ms": getattr(message, "duration_ms", None),
            "num_turns": getattr(message, "num_turns", None),
            "session_id": getattr(message, "session_id", None),
            "usage_available": bool(usage),
            "sdk_result": getattr(message, "result", None),
            "sdk_errors": getattr(message, "errors", None),
            "sdk_error_status": getattr(message, "api_error_status", None),
            "sdk_stop_reason": getattr(message, "stop_reason", None),
        }
        logger.info(
            "Captured metadata: api_equivalent_cost=$%s, duration=%sms, turns=%s",
            metadata["api_equivalent_cost_usd"],
            metadata["duration_ms"],
            metadata["num_turns"],
        )
        return metadata

    def _create_completion_event(self, metadata: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "completion",
            "api_equivalent_cost": metadata.get("api_equivalent_cost_usd"),
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

    def translate_error(self, exc: Exception, options: dict[str, Any]) -> Exception:
        error_msg = str(exc)
        exc_type = type(exc).__name__
        logger.error("Claude Code execution failed: %s", error_msg, exc_info=exc)
        if (CLINotFoundError is not None and isinstance(exc, CLINotFoundError)) or "CLINotFoundError" in exc_type:
            return ValueError(
                "Claude Code CLI not installed. Install with: npm install -g @anthropic-ai/claude-code\n"
                f"Original error: {error_msg}"
            )
        if (CLIConnectionError is not None and isinstance(exc, CLIConnectionError)) or "CLIConnectionError" in exc_type:
            return ValueError(
                "Failed to connect to Claude Code. Check health with: claude doctor\n"
                f"{self._auth_failure_guidance(bool(options.get('use_api_key')))}\n"
                f"Original error: {error_msg}"
            )
        if (ProcessError is not None and isinstance(exc, ProcessError)) or "ProcessError" in exc_type:
            return ValueError(
                f"Claude Code process failed (exit code {getattr(exc, 'exit_code', 'unknown')})\nError output: {getattr(exc, 'stderr', '')}\nOriginal error: {error_msg}"
            )
        if isinstance(exc, asyncio.TimeoutError):
            return ValueError(
                f"Claude Code execution timed out after {options.get('timeout', 300)} seconds. The task may be too complex or the system may be slow. Consider increasing timeout or breaking the task into smaller parts."
            )
        if "rate limit" in error_msg.lower() or "429" in error_msg:
            return ValueError(
                f"Claude API rate limit exceeded. Please wait a moment and try again.\nOriginal error: {error_msg}"
            )
        if self._is_auth_error(exc):
            return ValueError(self._auth_failure_guidance(bool(options.get("use_api_key"))))
        return ValueError(f"Claude Code execution failed after {self.max_retries} attempts: {error_msg}")

    @staticmethod
    def _enrich_error_result_exception(
        exc: Exception,
        exc_type_name: str,
        is_error_from_sdk: bool,
        result_text: str,
        api_error_status: int | None,
    ) -> Exception | None:
        """Recover the real error detail the SDK drops from an error-result.

        When the CLI reports an error result then exits, the SDK raises a *bare*
        Exception whose text is only the result subtype — e.g. an invalid key
        surfaces as "...returned an error result: success" instead of "Invalid
        API key" (#455). Rebuild the message from the real result text / HTTP
        status captured off the ResultMessage so exec_fallback can detect auth
        failures. Returns an enriched exception to raise, or None to re-raise the
        original unchanged. Typed SDK errors (CLIConnectionError, ...) are left
        alone so exec_fallback's typed branches still match.
        """
        if not (is_error_from_sdk and exc_type_name == "Exception"):
            return None
        detail = str(exc)
        if result_text and result_text not in detail:
            detail = f"{detail}: {result_text}"
        if api_error_status is not None:
            detail = f"{detail} [api_error_status={api_error_status}]"
        return RuntimeError(detail) if detail != str(exc) else None

    @staticmethod
    def _is_auth_error(exc: Exception) -> bool:
        """Heuristically detect a Claude CLI authentication/billing failure.

        The common auth failure surfaces as a bare ``Exception`` whose message
        carries the CLI's error text (the SDK rewrites the result-level error
        before re-raising), so we match on the message string, not the exception
        type. A multi-marker OR keeps this robust to CLI wording drift.
        """
        text = str(exc).lower()
        return any(marker in text for marker in _AUTH_ERROR_MARKERS)

    @staticmethod
    def _auth_failure_guidance(use_api_key: bool) -> str:
        """Build remediation text for an auth failure, tailored to the billing mode."""
        if use_api_key:
            return (
                "Claude Code authentication failed while API-key billing is permitted "
                "(use_api_key: true). This flag grants permission but does not prove which "
                "credential the CLI used.\n"
                "  - If ANTHROPIC_API_KEY is configured, verify the key and Anthropic Console credit.\n"
                "  - Otherwise run `claude auth login` and `claude auth status` to verify "
                "your account/subscription login.\n"
                "  - Remove `- use_api_key: true` to disallow ANTHROPIC_API_KEY billing."
            )
        return (
            "Claude Code could not authenticate. This node uses your Claude "
            "Pro/Max subscription by default and ignores ANTHROPIC_API_KEY "
            "unless you opt in.\n"
            "  - Recommended: run `claude auth login` (or `claude setup-token` "
            "for non-interactive/CI) to authenticate with your account/subscription.\n"
            "  - Or add `- use_api_key: true` to this node to bill "
            "ANTHROPIC_API_KEY to your Anthropic Console (pay per token)."
        )

    def build_warning_context(self, options: dict[str, Any], result: AgentResult) -> dict[str, Any]:
        output_schema = options.get("output_schema") or {}
        properties = output_schema.get("properties") if isinstance(output_schema, dict) else None
        metadata = result.metadata
        return {
            "node_type": "agent",
            "backend": "claude",
            "backend_display": "Claude CLI",
            "backend_error_details": "SDK error details",
            "schema_properties": list(properties) if isinstance(properties, dict) else [],
            "schema_required": output_schema.get("required") if isinstance(output_schema, dict) else None,
            "result_preview": result.result_text[:500],
            "sdk_result": metadata.get("sdk_result"),
            "sdk_errors": metadata.get("sdk_errors"),
            "sdk_error_status": metadata.get("sdk_error_status"),
            "sdk_stop_reason": metadata.get("sdk_stop_reason"),
            "sdk_exception": result.error_text,
        }
