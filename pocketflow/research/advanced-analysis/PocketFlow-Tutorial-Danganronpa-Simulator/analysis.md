# PocketFlow Danganronpa Simulator: Architecture & Pattern Analysis for pflow

## Executive Summary

The Danganronpa Simulator is a sophisticated AI-driven social deduction game built on PocketFlow. It demonstrates patterns highly relevant to pflow's mission of deterministic workflow execution, particularly in state management, node design, and parallel execution. This analysis maps each discovered pattern to specific pflow tasks from tasks.json.

**Key Finding**: This project exemplifies the "simple nodes with complex orchestration" pattern that pflow needs. The DecisionNode's focused responsibility combined with sophisticated flow orchestration directly informs pflow's implementation strategy.

## 1. Project Structure

### Module Organization
```
PocketFlow-Tutorial-Danganronpa-Simulator/
├── app.py           # Streamlit UI & game orchestration (668 lines)
├── flow.py          # PocketFlow flow definitions (58 lines)
├── nodes.py         # DecisionNode implementation (511 lines)
├── utils/           # LLM utilities
│   └── call_llm.py  # Async LLM wrapper (66 lines)
├── assets/          # Static resources
│   ├── texts.py     # Game data & prompts
│   └── [characters] # Sprites & audio
└── docs/
    └── design.md    # Game design document
```

**Pattern**: Clear separation between UI (app.py), business logic (nodes.py), and orchestration (flow.py).

**pflow Applicability**:
- **Helps Task 11**: File I/O nodes should follow this separation - node logic separate from CLI interface
- **Helps Task 12**: LLM node can use similar utility pattern for provider abstraction
- **Helps Task 5**: Node discovery can scan for this standard structure

## 2. Flow Architecture

### Flow Structure (flow.py)
```python
# Sequential flow for single character
def create_character_decision_flow() -> AsyncFlow:
    decision_node = DecisionNode(max_retries=3, wait=1)
    return AsyncFlow(start=decision_node)

# Parallel flow for multiple characters
class ParallelCharacterDecisionFlow(AsyncParallelBatchFlow):
    async def prep_async(self, shared: dict) -> list[dict]:
        acting_characters = shared.get("acting_characters")
        return [{"character_name": name} for name in acting_characters]
```

**Key Patterns**:
1. **Flow Factory Functions**: Clean flow creation with configuration
2. **Parallel Batch Processing**: Efficient concurrent execution
3. **Parameter Injection**: Dynamic params for node reuse

**pflow Applicability**:
- **Helps Task 4 (IR-to-Flow Converter)**: Factory pattern for creating flows from IR
- **Helps Task 3 (Hello World Workflow)**: Simple flow creation pattern
- **Helps Task 17 (LLM Workflow Generation)**: Template for generating parallel flows

**Deterministic Execution**: The retry configuration (max_retries=3, wait=1) ensures predictable behavior even with LLM variability.

## 3. State Management

### Shared Store Usage
The project uses shared store extensively for game state:

```python
# From app.py - State initialization
shared_state = {
    "db_conn": conn,
    "current_day": st.session_state.current_day,
    "current_state": st.session_state.current_state,
    "game_introduction_text": game_introduction_text,
    "character_profiles": character_profiles,
    "hint_text": hint_text,
    "shuffled_character_order": shuffled_order,
    "user_character_name": "Shuichi" if viewer_mode == PLAYER_MODE_OPTION else None,
    "user_input": user_input if user_input else None,
    "acting_characters": [character_name]  # For parallel flow
}
```

**Key Patterns**:
1. **Centralized State**: All game state in one dictionary
2. **Database Connection Sharing**: Pass conn through shared store
3. **Configuration Injection**: Game rules, profiles via shared store
4. **User Input Handling**: Optional user input through shared["user_input"]

**pflow Applicability**:
- **Helps Task 9 (Shared Store & Proxy)**: Pattern for handling complex state
- **Helps Task 3 (Hello World)**: Example of shared store initialization
- **Helps Task 8 (Shell Integration)**: Pattern for stdin → shared["stdin"]
- **Helps Task 1.1**: Shared store initialization pattern

## 4. Node Design Pattern

### DecisionNode Architecture
The DecisionNode (511 lines) demonstrates sophisticated single-purpose design:

```python
class DecisionNode(AsyncNode):
    async def prep_async(self, shared):
        # 1. Extract character from params
        character_name = self.params.get('character_name')

        # 2. Query database for context
        cursor = shared["db_conn"].cursor()
        # ... extensive context gathering ...

        # 3. Return structured context
        return {
            "character_name": character_name,
            "my_role": my_role,
            "living_players": living_players,
            "recent_history": history_log_str,
            # ... 15+ context fields ...
        }

    async def exec_async(self, context):
        # 1. Build sophisticated prompt
        # 2. Call LLM with retry logic
        # 3. Parse YAML response
        # 4. Validate output structure
        return parsed_output

    async def post_async(self, shared, prep_res, exec_res):
        # Log results to database
        cursor = shared["db_conn"].cursor()
        # ... transaction logging ...
```

**Key Patterns**:
1. **Three-Phase Lifecycle**: Clean prep/exec/post separation
2. **Context Building**: Sophisticated state gathering in prep
3. **Structured Output**: YAML parsing for deterministic results
4. **Validation**: Extensive output validation in exec
5. **Side Effects in Post**: Database writes isolated to post phase

**pflow Applicability**:
- **Helps Task 11-14, 25-28 (All Node Tasks)**: Template for node implementation
- **Helps Task 12 (LLM Node)**: YAML output pattern for structured responses
- **Helps Task 13 (GitHub Node)**: Pattern for API interaction nodes
- **Helps Task 7 (Metadata Extraction)**: Node structure to parse

## 5. LLM Integration Patterns

### Structured Prompting (nodes.py)
```python
prompt = f"""
You are acting as {character_name}.
Your personality: {personality}
Your role in this Killing Game is: {my_role}

Current Situation:
- Day: {context['current_day']}
- Phase: {current_phase}
- Recent History: {context['recent_history']}

Output Format (Strictly follow this YAML format):
```yaml
{yaml_output_instructions}
```
"""
```

### Output Validation
```python
# Parse YAML response
parsed_output = yaml.safe_load(yaml_content)

# Validate required fields
if 'thinking' not in parsed_output:
    raise ValueError(f"Missing 'thinking'")

if is_voting_phase:
    vote_index = int(parsed_output['vote_target_index'])
    if not (0 <= vote_index <= len(valid_targets)):
        raise ValueError(f"Invalid vote index")
```

**pflow Applicability**:
- **Helps Task 18 (Prompt Templates)**: Structured prompt generation
- **Helps Task 17 (LLM Workflow Generation)**: YAML parsing for workflows
- **Helps Task 19 (Template Resolver)**: Variable substitution patterns

## 6. Async Execution & Performance

### Async LLM Wrapper (utils/call_llm.py)
```python
async def call_llm_async(prompt):
    logger.info(f"PROMPT: {prompt}")

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    response = await client.aio.models.generate_content(
        model="gemini-2.5-flash-preview-04-17",
        contents=[prompt]
    )

    logger.info(f"RESPONSE: {response.text}")
    return response.text
```

**Key Patterns**:
1. **Async-First Design**: All LLM calls are async
2. **Comprehensive Logging**: Every call logged for debugging
3. **Environment Configuration**: API keys via env vars
4. **Provider Abstraction**: Easy to swap LLM providers

**pflow Applicability**:
- **Helps Task 15 (LLM Client)**: Async pattern for LLM integration
- **Helps Task 23 (Execution Tracing)**: Logging pattern for traces
- **Helps Task 12 (LLM Node)**: Provider abstraction approach

## 7. Database-Driven State Persistence

### SQLite Integration
```python
def init_db():
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    # Create roles and actions tables
    return conn

# State tracking through database
cursor.execute("""
    INSERT INTO actions (day, phase, actor_name, action_type, content)
    VALUES (?, ?, ?, ?, ?)
""", (day, phase, actor, action, content))
```

**Pattern**: Use database for complex state that needs querying, shared store for simple passing.

**pflow Applicability**:
- **Helps Task 24 (Caching)**: Pattern for persistent state
- **Helps Task 23 (Tracing)**: Database pattern for trace storage
- **NOT for MVP**: pflow uses simpler file-based approach

## 8. Critical Patterns for pflow Tasks

### Pattern-to-Task Mapping

| Pattern | Helps pflow Task | How to Apply |
|---------|------------------|--------------|
| **Single-Purpose Node** | Task 11-14, 25-28 (All nodes) | Each node does ONE thing well |
| **Shared Store Context** | Task 9 (Proxy), Task 3 (Hello World) | Pass all data through shared dict |
| **Flow Factories** | Task 4 (IR Converter) | Create flows programmatically |
| **Async LLM Pattern** | Task 15 (LLM Client), Task 12 (LLM Node) | Async wrapper with retries |
| **YAML Structured Output** | Task 17 (Workflow Gen), Task 18 (Prompts) | Deterministic LLM responses |
| **Parallel Batch Flow** | Future: Async execution | Pattern for concurrent nodes |
| **Parameter Injection** | Task 22 (Named Workflows) | Dynamic params at runtime |
| **Three-Phase Lifecycle** | All node tasks | Clean prep/exec/post separation |

### High-Priority Task Insights

**Task 5 (Node Discovery)**:
- Scan for classes inheriting from AsyncNode/BaseNode
- Look for standard prep/exec/post methods
- Extract docstrings for metadata

**Task 9 (Shared Store & Proxy)**:
- Simple dict passing works for most cases
- Complex state benefits from structured context
- Proxy only needed for key conflicts

**Task 12 (LLM Node)**:
- Use YAML for structured output
- Comprehensive prompt templates
- Validation prevents non-deterministic failures

**Task 17 (LLM Workflow Generation)**:
- Factory functions for flow creation
- Parameter lists for batch processing
- Structured prompts yield better workflows

## 9. Deterministic Execution Strategies

The project achieves determinism despite LLM variability through:

1. **Structured Output Enforcement**: YAML parsing ensures consistent format
2. **Comprehensive Validation**: Every LLM output validated before use
3. **Retry Logic**: Built-in retries handle transient failures
4. **State Isolation**: Each node execution has clean context
5. **Explicit Side Effects**: All mutations in post phase

**pflow Implementation**:
- Enforce structured output in all LLM interactions
- Validate early and fail fast with clear errors
- Use retry decorators from pocketflow
- Keep nodes pure except in post phase

## 10. Lessons for pflow MVP

### Do's:
1. **Keep nodes simple**: One purpose, clear interface
2. **Use shared store liberally**: Pass everything through it
3. **Structure LLM outputs**: YAML/JSON for determinism
4. **Validate aggressively**: Catch errors early
5. **Log comprehensively**: Every decision traceable

### Don'ts:
1. **Don't over-engineer**: Simple dict passing works
2. **Don't hide state**: Everything in shared store
3. **Don't trust LLM output**: Always validate
4. **Don't mix concerns**: UI separate from logic

### Implementation Priority:
1. Start with simple single-purpose nodes (Task 11-14)
2. Build basic flow execution (Task 3)
3. Add LLM integration with structure (Task 12, 15)
4. Layer on workflow generation (Task 17)
5. Optimize with caching/tracing later (Task 23-24)

## Conclusion

The Danganronpa Simulator demonstrates that complex AI-driven applications can be built with simple, deterministic components when properly orchestrated. The patterns here - particularly around node design, state management, and LLM integration - provide a proven template for pflow's implementation. The key insight is that **simplicity at the node level enables sophistication at the flow level**, which aligns perfectly with pflow's vision of deterministic workflow compilation.
