# MCP Tools Layer Integration Flow Diagram

**Visual representation of how tools, services, utils, and resources work together**

## Request Flow: workflow_execute

```
┌─────────────────────────────────────────────────────────────────┐
│                    1. MCP Client (Claude Desktop)                │
│                    Sends: workflow, parameters                   │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    2. Tools Layer (async)                        │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ @mcp.tool()                                               │  │
│  │ async def workflow_execute(workflow, parameters):         │  │
│  │     def _sync_execute():                                  │  │
│  │         return ExecutionService.execute_workflow(...)     │  │
│  │                                                            │  │
│  │     return await asyncio.to_thread(_sync_execute)         │  │
│  └───────────────────────────────────────────────────────────┘  │
│                    Async/Sync Bridge                             │
└────────────────────────────┬────────────────────────────────────┘
                             │ (thread pool)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   3. Services Layer (sync)                       │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ class ExecutionService(BaseService):                      │  │
│  │     @classmethod                                          │  │
│  │     @ensure_stateless                                     │  │
│  │     def execute_workflow(cls, workflow, parameters):      │  │
│  │         # Step 1: Resolve workflow                        │  │
│  │         workflow_ir, error, source = resolve_workflow(...) ◄─┼─┐
│  │                                                            │  │ │
│  │         # Step 2: Validate parameters                     │  │ │
│  │         is_valid, error = validate_execution_parameters(◄─┼─┼─┤
│  │                                                            │  │ │
│  │         # Step 3: Create fresh instances                  │  │ │
│  │         workflow_manager = WorkflowManager()              │  │ │
│  │         metrics_collector = MetricsCollector()            │  │ │
│  │                                                            │  │ │
│  │         # Step 4: Execute (with agent defaults)           │  │ │
│  │         result = execute_workflow(                        │  │ │
│  │             workflow_ir=workflow_ir,                      │  │ │
│  │             execution_params=parameters,                  │  │ │
│  │             enable_repair=False,  # Agent default         │  │ │
│  │             output=NullOutput(),  # Agent default         │  │ │
│  │         )                                                  │  │ │
│  │                                                            │  │ │
│  │         # Step 5: Format result using shared formatter    │  │ │
│  │         from pflow.execution.formatters.success_formatter │  │ │
│  │         formatted = format_execution_success(...)     ◄───┼─┼─┤
│  │         return formatted                                   │  │ │
│  └───────────────────────────────────────────────────────────┘  │ │
└────────────────────────────┬────────────────────────────────────┘ │
                             │                                       │
                             ▼                                       │
┌─────────────────────────────────────────────────────────────────┐ │
│                   4. Utils Layer (called by services)            │ │
│  ┌─────────────────────────────────────────────────────────┐    │ │
│  │ resolver.py                                             │ ◄──┼─┘
│  │   resolve_workflow() → (workflow_ir, error, source)    │    │
│  │   - Try as dict ("direct")                             │    │
│  │   - Try as library name ("library")                    │    │
│  │   - Try as file path ("file")                          │    │
│  │   - Return suggestions if not found                    │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ validation.py                                           │ ◄──┼─┐
│  │   validate_execution_parameters() → (is_valid, error)  │    │ │
│  │   - Check parameter names (shell-safe)                 │    │ │
│  │   - Check size (1MB limit)                             │    │ │
│  │   - Check for code injection patterns                  │    │ │
│  └─────────────────────────────────────────────────────────┘    │ │
│                                                                   │ │
│  ┌─────────────────────────────────────────────────────────┐    │ │
│  │ errors.py                                               │    │ │
│  │   sanitize_parameters() → sanitized_dict               │    │ │
│  │   - Redact SENSITIVE_KEYS (15 patterns)                │    │ │
│  │   - Truncate very long strings                         │    │ │
│  │   - Recursively sanitize nested dicts                  │    │ │
│  └─────────────────────────────────────────────────────────┘    │ │
└────────────────────────────┬────────────────────────────────────┘ │
                             │                                       │
                             ▼                                       │
┌─────────────────────────────────────────────────────────────────┐ │
│                   5. Core pflow (sync)                           │ │
│  ┌─────────────────────────────────────────────────────────┐    │ │
│  │ core/workflow_manager.py                                │    │ │
│  │   WorkflowManager.exists(), .load_ir()                  │    │ │
│  └─────────────────────────────────────────────────────────┘    │ │
│                                                                   │ │
│  ┌─────────────────────────────────────────────────────────┐    │ │
│  │ execution/workflow_execution.py                         │    │ │
│  │   execute_workflow() → ExecutionResult                  │    │ │
│  └─────────────────────────────────────────────────────────┘    │ │
│                                                                   │ │
│  ┌─────────────────────────────────────────────────────────┐    │ │
│  │ execution/formatters/success_formatter.py               │ ◄──┼─┘
│  │   format_execution_success() → formatted_dict           │    │
│  │   format_success_as_text() → formatted_string           │    │
│  │   (Used by both CLI and MCP for consistency)            │    │
│  └─────────────────────────────────────────────────────────┘    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                   6. Response to MCP Client                      │
│                   Formatted text with execution results          │
└─────────────────────────────────────────────────────────────────┘
```

## Pattern Layers

```
┌─────────────────────────────────────────────────────────────────┐
│                         TOOLS LAYER                              │
│  Responsibility: Async/sync bridge, parameter descriptions       │
│  Pattern: @mcp.tool() + asyncio.to_thread()                     │
│  Output: Return result directly to MCP protocol                  │
├─────────────────────────────────────────────────────────────────┤
│                        SERVICES LAYER                            │
│  Responsibility: Business logic, stateless operations            │
│  Pattern: @classmethod + @ensure_stateless + fresh instances    │
│  Output: Return formatted strings/dicts (via shared formatters) │
├─────────────────────────────────────────────────────────────────┤
│                         UTILS LAYER                              │
│  Responsibility: Security, validation, resolution                │
│  Pattern: Pure functions, no state                              │
│  Output: Return validated/resolved/sanitized data               │
├─────────────────────────────────────────────────────────────────┤
│                       RESOURCES LAYER                            │
│  Responsibility: Provide read-only data to agents               │
│  Pattern: @mcp.resource() + return content                      │
│  Output: Return markdown/text content directly                  │
├─────────────────────────────────────────────────────────────────┤
│                        CORE PFLOW                                │
│  Responsibility: Workflow engine, execution, validation          │
│  Pattern: Sync classes, shared formatters (CLI/MCP parity)      │
│  Output: Return execution results, validation results           │
└─────────────────────────────────────────────────────────────────┘
```

## Data Flow: registry_discover (LLM-powered discovery)

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. Agent calls registry_discover(task="I need to...")           │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. Tools Layer: async def registry_discover(task)               │
│    └─> await asyncio.to_thread(_sync_discover)                  │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. Services Layer: DiscoveryService.discover_components(task)   │
│    ┌────────────────────────────────────────────────────────┐   │
│    │ # Fresh instances                                      │   │
│    │ node = ComponentBrowsingNode()                         │   │
│    │ workflow_manager = WorkflowManager()                   │   │
│    │                                                         │   │
│    │ # Build shared store context                           │   │
│    │ shared = {                                             │   │
│    │     "user_input": task,                                │   │
│    │     "workflow_manager": workflow_manager,              │   │
│    │     "current_date": datetime.now().strftime(...)      │   │
│    │ }                                                       │   │
│    │                                                         │   │
│    │ # Run planning node (LLM-powered selection)            │   │
│    │ action = node.run(shared)                              │   │
│    │                                                         │   │
│    │ # Extract planning context (markdown formatted)        │   │
│    │ planning_context = shared.get("planning_context")      │   │
│    │ return planning_context                                │   │
│    └────────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. Core pflow: ComponentBrowsingNode (planning system)          │
│    ┌────────────────────────────────────────────────────────┐   │
│    │ def run(self, shared):                                 │   │
│    │     # Build registry context                           │   │
│    │     registry = Registry()                              │   │
│    │     registry_metadata = registry.load()                │   │
│    │                                                         │   │
│    │     # Call LLM to select relevant nodes               │   │
│    │     selected_nodes = self._llm_select_nodes(...)       │   │
│    │                                                         │   │
│    │     # Build planning context using shared formatter    │   │
│    │     from pflow.planning.context_builder import \       │   │
│    │         build_planning_context                         │   │
│    │                                                         │   │
│    │     context = build_planning_context(                  │   │
│    │         selected_node_ids=selected_nodes,              │   │
│    │         registry_metadata=registry_metadata            │   │
│    │     )                                                   │   │
│    │                                                         │   │
│    │     shared["planning_context"] = context               │   │
│    │     return "success"                                   │   │
│    └────────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. Response: Markdown formatted planning context with:          │
│    - Selected node specifications                               │
│    - Input/output interfaces                                    │
│    - Usage examples                                             │
│    - Template variable paths available                          │
└─────────────────────────────────────────────────────────────────┘
```

## Stateless Pattern Enforcement

```
┌─────────────────────────────────────────────────────────────────┐
│                    Request 1 (Thread A)                          │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ ExecutionService.execute_workflow()                       │  │
│  │   ├─> workflow_manager = WorkflowManager()  # Fresh      │  │
│  │   ├─> metrics = MetricsCollector()          # Fresh      │  │
│  │   └─> result = execute_workflow(...)                     │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                             ║
                             ║ (Parallel execution)
                             ║
┌─────────────────────────────────────────────────────────────────┐
│                    Request 2 (Thread B)                          │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ ExecutionService.execute_workflow()                       │  │
│  │   ├─> workflow_manager = WorkflowManager()  # Fresh      │  │
│  │   ├─> metrics = MetricsCollector()          # Fresh      │  │
│  │   └─> result = execute_workflow(...)                     │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘

No shared state = No race conditions = Thread-safe
```

## Security Validation Flow

```
┌────────────────────────────────────────────────────────────────┐
│              Input: workflow, parameters                        │
└────────────────────┬───────────────────────────────────────────┘
                     │
                     ▼
┌────────────────────────────────────────────────────────────────┐
│ Layer 1: Workflow Resolution (utils/resolver.py)               │
│   ├─> validate_file_path() if path input                       │
│   │   - Block .., ~, null bytes, absolute paths                │
│   └─> resolve to workflow_ir                                   │
└────────────────────┬───────────────────────────────────────────┘
                     │
                     ▼
┌────────────────────────────────────────────────────────────────┐
│ Layer 2: Parameter Validation (utils/validation.py)            │
│   ├─> validate_execution_parameters()                          │
│   │   - Shell-safe parameter names                             │
│   │   - 1MB size limit                                         │
│   │   - Code injection detection                               │
│   └─> validated_params                                         │
└────────────────────┬───────────────────────────────────────────┘
                     │
                     ▼
┌────────────────────────────────────────────────────────────────┐
│ Layer 3: Execute Workflow (core/workflow_execution.py)         │
│   └─> Execute with validated inputs                            │
└────────────────────┬───────────────────────────────────────────┘
                     │
                     ▼
┌────────────────────────────────────────────────────────────────┐
│ Layer 4: Error Sanitization (utils/errors.py)                  │
│   ├─> sanitize_parameters()                                    │
│   │   - Redact SENSITIVE_KEYS                                  │
│   │   - Truncate long strings                                  │
│   └─> Safe output for LLM                                      │
└────────────────────┬───────────────────────────────────────────┘
                     │
                     ▼
┌────────────────────────────────────────────────────────────────┐
│              Safe response to MCP client                        │
└────────────────────────────────────────────────────────────────┘
```

## CLI/MCP Parity via Shared Formatters

```
┌─────────────────────────────────────────────────────────────────┐
│                     CLI Path                                     │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ cli/main.py                                               │  │
│  │   └─> result = execute_workflow(...)                      │  │
│  │       └─> from pflow.execution.formatters.success_formatter│ │
│  │           formatted = format_execution_success(...)       │  │
│  │           click.echo(formatted)  # Print to stdout        │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                             ║
                             ║ (Same formatter)
                             ║
┌─────────────────────────────────────────────────────────────────┐
│                     MCP Path                                     │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ services/execution_service.py                             │  │
│  │   └─> result = execute_workflow(...)                      │  │
│  │       └─> from pflow.execution.formatters.success_formatter│ │
│  │           formatted = format_execution_success(...)       │  │
│  │           return formatted  # Return to MCP client        │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘

Result: Identical output format for both CLI and MCP interfaces
```

## Resource Access Pattern

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. Agent needs instructions for building workflows              │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. Agent reads resource: pflow://instructions                   │
│    (No tool call needed - direct resource access)               │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. Resources Layer: instruction_resources.py                    │
│    ┌────────────────────────────────────────────────────────┐   │
│    │ @mcp.resource("pflow://instructions")                  │   │
│    │ def get_agent_instructions() -> str:                   │   │
│    │     path = ~/.pflow/instructions/AGENT_INSTRUCTIONS.md │   │
│    │     if path.exists():                                  │   │
│    │         return path.read_text()                        │   │
│    │     else:                                              │   │
│    │         return "Run 'pflow workflow list' to..."       │   │
│    └────────────────────────────────────────────────────────┘   │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. Agent receives: 66KB comprehensive guide                     │
│    - 10-step development loop                                   │
│    - Patterns and best practices                                │
│    - Troubleshooting guide                                      │
│    - Real-world examples                                        │
└─────────────────────────────────────────────────────────────────┘
```

This visual complement shows the actual flow of data and control through the integrated layers, making it easier to understand how the architecture works in practice.
