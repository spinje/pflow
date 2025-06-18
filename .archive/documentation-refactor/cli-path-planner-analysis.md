# CLI Path Planner Analysis

## Task Context

**Task #8 from taskmaster**: Build CLI Path Planner - CLI syntax to IR compilation without confirmation

**User's Direction**:
- "Yes, its a core feature that the user can write a flow in a pipe syntax without specifying every parameter (or shared store keys and how they interact with each other)."
- "We could treat this as a natural language planning task but with a pipe syntax"
- "The user can get cli auto completion for the pipe syntax while writing the flow"
- "We should add this later in the implementation plan and exclude special handling of the pipe syntax for now"
- "Just send the cli command to the natural language planner and let it handle it"

## Current Understanding from Documentation

### From planner.md

The planner already has **two distinct entry points**:
1. **Natural Language Prompts** - Converts user intent into validated flows via LLM selection
2. **CLI Pipe Syntax** - Validates and compiles manually written flows into complete IR

The documentation shows a sophisticated CLI path that:
- Parses CLI pipe syntax
- Validates node existence
- Analyzes template variables
- Generates IR directly
- Does NOT use LLM (unlike natural language path)

### The Conflict

The current documentation describes a sophisticated CLI validation planner, but the user wants to:
1. Initially treat CLI pipe syntax as natural language
2. Send it to the LLM planner
3. Add direct CLI parsing later

## Analysis of User's Approach

### Phase 1: CLI as Natural Language (MVP)
```bash
# User types:
pflow read-file --path=input.txt >> llm --prompt="summarize this"

# MVP approach: Send entire string to LLM planner
# LLM understands pipe syntax and generates appropriate IR
```

**Benefits**:
- Simpler initial implementation
- Leverages existing natural language planner
- LLM can handle incomplete parameter specifications
- Natural template variable generation

**Challenges**:
- Slower than direct parsing
- Requires LLM tokens for deterministic syntax
- Less predictable than direct compilation

### Phase 2: Direct CLI Parsing (Post-MVP)
```bash
# Future optimization: Parse CLI directly
# Skip LLM for deterministic syntax
```

## Task Recommendations

### 1. Remove Current Task #8?
The current task in tasks.json seems to assume direct CLI parsing. Given the user's direction, we might need to:
- Remove or defer the current task
- Add a simpler task for MVP

### 2. New MVP Task: "CLI Command Routing"
Create a simple task that:
- Detects if input looks like CLI pipe syntax
- Routes ALL input to natural language planner initially
- No special parsing or validation

### 3. Defer Advanced CLI Parsing
Create a v2.0 task for:
- Direct CLI parsing without LLM
- Template variable analysis
- Autocomplete support

## Implementation Details for MVP

### Simple CLI Detection
```python
def is_cli_pipe_syntax(input_str: str):
    # Very simple check - does it contain >> operator?
    return ">>" in input_str and any(flag in input_str for flag in ["--", "-"])

def plan_flow(user_input: str) -> JsonIR:
    # For MVP, treat everything as natural language
    return natural_language_planner(user_input)
```

### LLM Prompt for CLI Syntax
When sending CLI syntax to LLM, provide context:
```
The user provided this CLI pipe syntax:
read-file --path=input.txt >> llm --prompt="summarize this"

Generate a workflow that:
1. Reads the file from input.txt
2. Summarizes it using the llm node
3. Uses appropriate template variables where parameters are missing
```

### Template Variable Generation
The LLM will naturally:
- Recognize incomplete specifications
- Generate template variables like $file_path if --path is missing
- Create proper shared store mappings

## Documentation Updates Needed

### 1. planner.md
- Add note about MVP approach (CLI → natural language)
- Clarify that direct CLI parsing is v2.0
- Keep existing documentation but mark as "future state"

### 2. architecture.md
- Update to reflect MVP simplification
- Note that CLI parsing optimization comes later

### 3. mvp-scope.md
- Explicitly state: "Direct CLI parsing deferred to v2.0"
- MVP uses natural language planner for all inputs

## Autocomplete Considerations

The user mentioned "cli auto completion for the pipe syntax while writing the flow". This is complex because:

1. **Shell-level autocomplete** - Requires shell integration
2. **Node name completion** - Need registry of available nodes
3. **Parameter completion** - Need node metadata

For MVP, we should:
- Skip autocomplete entirely
- Add it as a v2.0 feature
- Focus on core execution first

## Task List Updates

### Current Task #8 Issues
Looking at tasks.json, task #8 doesn't exist! There's a gap in numbering. The tasks go from #7 to #9.

However, there are related tasks:
- Task #19: "Implement workflow generation engine" - This is where CLI → LLM routing would happen
- Task #4: "Build context-aware CLI parameter resolution" - Related but different

### Recommended Changes

1. **Update Task #19** to explicitly mention:
   - Handles both natural language AND CLI pipe syntax
   - Routes both through LLM for MVP
   - Generates appropriate prompts for CLI syntax

2. **Add new v2.0 task** for direct CLI parsing:
   - Parse pipe syntax without LLM
   - Generate IR directly from CLI
   - Implement autocomplete hooks

3. **Update Task #4** to clarify:
   - This is about runtime parameter resolution
   - Not about parsing CLI pipe syntax

## Simon Willison's LLM Inspiration

The user mentioned looking at Simon Willison's `llm` framework for inspiration. Key patterns:
- Simple pipe integration
- Streaming support
- Plugin architecture
- Clear stdin/stdout handling

We're already referencing this in task #4 for shell integration.

## Summary

The user wants a simpler MVP approach where:
1. ALL input (natural language or CLI) goes to LLM planner
2. Direct CLI parsing is deferred to v2.0
3. Autocomplete is a future feature
4. Focus on getting core workflow execution working

This is actually SIMPLER than what's currently documented, which is good for MVP focus.
