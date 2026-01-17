# Task 94: Display Available LLM Models Based on Configured API Keys

## Description
Enhance the LLM node information displayed to agents (via `registry describe` and `registry discover`) to show which models are actually available based on configured API keys. If no keys are configured, show instructions for the agent to ask the user to set up keys using `pflow settings set-env`.

## Status
not started

## Dependencies
- Task 80: Implement API Key Management via Settings - Provides the `pflow settings set-env` and `pflow settings list-env` commands for managing API keys

## Priority
medium

## Details
Currently when an agent sees the LLM node (via `pflow registry describe llm` or when returned from `pflow registry discover`), it sees:

```
- Params: model: str  # Model to use (default: gemini-2.5-flash)
```

The agent doesn't know which models are actually available - this depends on which API keys the user has configured. The agent might try to use a model the user doesn't have a key for, resulting in workflow execution failures.

### Problem
- Agent sees LLM node with generic `model: str` parameter
- No visibility into which providers/models are actually configured
- Failed workflows when agent picks unavailable models
- Poor user experience when keys are missing

### Solution
When LLM node information is surfaced to agents, dynamically show:

1. **If keys are configured**: List available models based on configured keys
   ```
   - Params: model: str  # Available models: claude-sonnet-4-0, claude-haiku, gpt-4o, gemini-2.5-flash (default)
   ```

2. **If no keys configured**: Show instructions for the agent
   ```
   - Params: model: str  # No LLM providers configured. Ask user to run: pflow settings set-env <PROVIDER>_API_KEY "key"
   ```

### Affected Commands
- `pflow registry describe llm` - Direct node lookup
- `pflow registry discover "..."` - When LLM node is returned as relevant

### Implementation Considerations
- Check configured keys via `pflow settings list-env` and/or `llm keys` (Simon Willison's llm library)
- Map API keys to available models (ANTHROPIC_API_KEY → Claude models, OPENAI_API_KEY → GPT models, etc.)
- This should happen at display time, not stored in registry metadata
- Keep it simple - just show what's available, don't try to enumerate all possible models

### Key Design Decisions
- Display-time check (not cached) since keys can change
- Show provider names or specific models? (needs discussion)
- How to detect llm library's configured keys vs pflow settings?

## Test Strategy
- Unit tests for key detection logic
- Test display output with various key configurations:
  - No keys configured
  - Only Anthropic key
  - Only OpenAI key
  - Multiple keys configured
- Integration test: `pflow registry describe llm` shows correct available models
- Integration test: `pflow registry discover` returns LLM node with available models info
