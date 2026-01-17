# Task 42: Claude Code Agentic Node

## Description
Create a Claude Code agentic super node that integrates with the Claude Code Python SDK to provide comprehensive AI-assisted development capabilities. This node will enable complex, multi-step development tasks with full project context, supporting the "Plan Once, Run Forever" philosophy by allowing workflows to leverage Claude's coding abilities.

## Status
done

## Completed
2025-09-07

## Dependencies
- Task 17: Implement Natural Language Planner System - The Claude Code node will receive planner-generated prompts with template variables
- Task 18: Template Variable System - Node must support ${variable} template resolution for dynamic prompts
- Task 9: Implement shared store collision detection using automatic namespacing - Node outputs need proper namespacing

## Priority
high

## Details
The Claude Code agentic node is a "super node" - an intentional exception to our simple node philosophy. It provides comprehensive development capabilities through integration with the Claude Code Python SDK rather than CLI subprocess execution.

### Key Design Decisions
- **Python SDK Integration**: Use `claude-code-sdk` package instead of CLI for native Python integration, structured responses, and better error handling
- **Dynamic Output Schema**: Accept an optional `output_schema` parameter that defines what Claude Code should output, making the node infinitely flexible and composable
- **Async-to-Sync Bridge**: Use `asyncio.run()` pattern (following MCP node) to wrap async SDK calls
- **Security-First**: Default allowed tools whitelist: ["Read", "Write", "Edit", "Bash"] with configurable permissions
- **Structured Error Handling**: Transform SDK exceptions into user-friendly guidance

### Technical Architecture
The node will:
1. Accept a task description and optional output schema
2. Build a prompt that includes the schema requirements
3. Execute Claude Code query via Python SDK
4. Parse response according to the provided schema
5. Store structured results in shared store with schema-defined keys

### Dynamic Schema Examples
```python
# Bug fixing with specific outputs
output_schema = {
    "root_cause": "str",
    "fix_applied": "str",
    "files_changed": "list[str]"
}

# Code review with structured analysis
output_schema = {
    "risk_level": "high|medium|low",
    "vulnerabilities": "list",
    "suggestions": "str"
}
```

### Interface Specification
- Reads: `shared["task"]` - Development task description (required)
- Reads: `shared["context"]` - Additional context (optional)
- Reads: `shared["output_schema"]` - Dynamic output structure (optional)
- Writes: Dynamic keys based on output_schema
- Params: `working_directory`, `model`, `allowed_tools`, `max_turns`, `temperature`

## Test Strategy
Comprehensive testing approach covering SDK integration and security:

- **Unit Tests**: Mock `claude_code_sdk.query()` responses, test schema validation, error transformations, async wrapper
- **Integration Tests**: Real Claude Code execution (gated by `RUN_CLAUDE_TESTS` env var), test tool permissions, timeout scenarios
- **Security Tests**: Validate tool whitelisting works, test dangerous command blocking, verify working directory restrictions
- **Schema Tests**: Test various output schemas, validate response parsing, test schema validation errors
- **Mock Patterns**: Follow MCP node patterns for async mocking, use structured response fixtures
