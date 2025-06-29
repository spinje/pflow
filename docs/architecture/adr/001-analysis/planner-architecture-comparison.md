# Planner Implementation: PocketFlow vs Traditional

## Context
Implementing pflow's workflow planner that takes natural language or CLI syntax and compiles it to executable workflows.

## Option A: PocketFlow-based Planner

```python
# planner_flow.py
from pocketflow import Node, Flow

class ParseInputNode(Node):
    """Parse natural language or CLI syntax"""
    def exec(self, shared):
        input_text = shared["input_text"]

        if ">>" in input_text:
            # CLI syntax
            shared["syntax_type"] = "cli"
            shared["tokens"] = self._parse_cli_syntax(input_text)
            return "cli_flow"
        else:
            # Natural language
            shared["syntax_type"] = "natural"
            shared["nl_query"] = input_text
            return "natural_flow"

    def _parse_cli_syntax(self, text):
        # Tokenize CLI syntax
        return text.split(">>")

class NaturalLanguagePlannerNode(Node):
    """Use LLM to understand intent and plan workflow"""
    def __init__(self, llm_client):
        super().__init__(max_retries=3)  # Built-in retry!
        self.llm = llm_client

    def exec(self, shared):
        query = shared["nl_query"]
        available_nodes = shared["available_nodes"]

        # Use LLM to plan
        plan = self.llm.plan_workflow(query, available_nodes)
        shared["workflow_plan"] = plan
        return "validate"

    def exec_fallback(self, shared):
        # Graceful degradation
        shared["error"] = "Could not understand request. Please use CLI syntax."
        return "error"

class CLIParserNode(Node):
    """Parse CLI syntax into workflow structure"""
    def exec(self, shared):
        tokens = shared["tokens"]
        workflow_plan = []

        for token in tokens:
            node_spec = self._parse_token(token.strip())
            workflow_plan.append(node_spec)

        shared["workflow_plan"] = workflow_plan
        return "validate"

class ValidateWorkflowNode(Node):
    """Validate workflow against registry"""
    def __init__(self, registry):
        super().__init__()
        self.registry = registry

    def exec(self, shared):
        plan = shared["workflow_plan"]
        errors = []

        for node_spec in plan:
            if not self.registry.has_node(node_spec["name"]):
                errors.append(f"Unknown node: {node_spec['name']}")

        if errors:
            shared["validation_errors"] = errors
            return "error"

        return "generate"

class GenerateIRNode(Node):
    """Generate JSON IR from validated plan"""
    def exec(self, shared):
        plan = shared["workflow_plan"]

        # Convert to pflow JSON IR format
        ir = {
            "version": "1.0",
            "nodes": [],
            "connections": []
        }

        for i, node_spec in enumerate(plan):
            ir["nodes"].append({
                "id": f"node_{i}",
                "type": node_spec["name"],
                "config": node_spec.get("config", {})
            })

            if i > 0:
                ir["connections"].append({
                    "from": f"node_{i-1}",
                    "to": f"node_{i}"
                })

        shared["workflow_ir"] = ir
        return "success"

class ErrorHandlerNode(Node):
    """Format and display errors"""
    def exec(self, shared):
        if "validation_errors" in shared:
            print("Validation errors:")
            for error in shared["validation_errors"]:
                print(f"  - {error}")
        elif "error" in shared:
            print(f"Error: {shared['error']}")
        return "end"

# Build the planner flow
def create_planner_flow(llm_client, registry):
    flow = Flow()

    # Create nodes
    parse = ParseInputNode()
    nl_planner = NaturalLanguagePlannerNode(llm_client)
    cli_parser = CLIParserNode()
    validate = ValidateWorkflowNode(registry)
    generate = GenerateIRNode()
    error = ErrorHandlerNode()

    # Connect nodes with action-based transitions
    flow.add_nodes(parse, nl_planner, cli_parser, validate, generate, error)

    parse - "natural_flow" >> nl_planner
    parse - "cli_flow" >> cli_parser

    nl_planner - "validate" >> validate
    nl_planner - "error" >> error

    cli_parser - "validate" >> validate

    validate - "generate" >> generate
    validate - "error" >> error

    generate - "success" >> flow.end
    error - "end" >> flow.end

    return flow

# Usage
planner = create_planner_flow(llm_client, registry)
result = planner.run({"input_text": "analyze sentiment of tweets and save to file"})
workflow_ir = result.get("workflow_ir")
```

## Option B: Traditional Implementation

```python
# planner.py
from typing import Dict, List, Optional
from dataclasses import dataclass
import json

@dataclass
class WorkflowPlan:
    nodes: List[Dict]
    connections: List[Dict]

class WorkflowPlanner:
    def __init__(self, llm_client, registry):
        self.llm_client = llm_client
        self.registry = registry

    def plan(self, input_text: str) -> Dict:
        """Main entry point for planning"""
        try:
            # Parse input
            syntax_type, parsed = self._parse_input(input_text)

            # Generate plan based on syntax type
            if syntax_type == "cli":
                plan = self._plan_from_cli(parsed)
            else:
                plan = self._plan_from_natural_language(parsed)

            # Validate
            validation_errors = self._validate_plan(plan)
            if validation_errors:
                raise ValidationError(validation_errors)

            # Generate IR
            return self._generate_ir(plan)

        except Exception as e:
            return self._handle_error(e)

    def _parse_input(self, input_text: str):
        """Determine input type and parse accordingly"""
        if ">>" in input_text:
            tokens = input_text.split(">>")
            return "cli", tokens
        else:
            return "natural", input_text

    def _plan_from_cli(self, tokens: List[str]) -> WorkflowPlan:
        """Parse CLI syntax into workflow plan"""
        nodes = []
        for token in tokens:
            node_spec = self._parse_cli_token(token.strip())
            nodes.append(node_spec)

        connections = [
            {"from": i, "to": i+1}
            for i in range(len(nodes)-1)
        ]

        return WorkflowPlan(nodes, connections)

    def _plan_from_natural_language(self, query: str) -> WorkflowPlan:
        """Use LLM to plan workflow from natural language"""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                available_nodes = self.registry.list_nodes()
                plan = self.llm_client.plan_workflow(query, available_nodes)
                return self._parse_llm_response(plan)
            except Exception as e:
                if attempt == max_retries - 1:
                    raise PlanningError("Could not understand request")
                continue

    def _validate_plan(self, plan: WorkflowPlan) -> List[str]:
        """Validate workflow against registry"""
        errors = []
        for node in plan.nodes:
            if not self.registry.has_node(node["name"]):
                errors.append(f"Unknown node: {node['name']}")
        return errors

    def _generate_ir(self, plan: WorkflowPlan) -> Dict:
        """Generate JSON IR from validated plan"""
        ir = {
            "version": "1.0",
            "nodes": [],
            "connections": []
        }

        for i, node_spec in enumerate(plan.nodes):
            ir["nodes"].append({
                "id": f"node_{i}",
                "type": node_spec["name"],
                "config": node_spec.get("config", {})
            })

        for conn in plan.connections:
            ir["connections"].append({
                "from": f"node_{conn['from']}",
                "to": f"node_{conn['to']}"
            })

        return ir

    def _handle_error(self, error: Exception) -> Dict:
        """Format error response"""
        if isinstance(error, ValidationError):
            return {
                "error": "validation",
                "details": error.errors
            }
        else:
            return {
                "error": "planning",
                "message": str(error)
            }

# Usage
planner = WorkflowPlanner(llm_client, registry)
result = planner.plan("analyze sentiment of tweets and save to file")
```

## Detailed Comparison

### PocketFlow Approach - PROS

1. **Built-in Retry/Fallback**
   - Automatic retry for LLM calls (huge win for reliability)
   - `exec_fallback` for graceful degradation
   - No manual retry loop code needed

2. **Visual Control Flow**
   - Flow structure is immediately visible in code
   - `parse - "natural_flow" >> nl_planner` is self-documenting
   - Easy to see all possible paths

3. **Testability**
   - Each node is independently testable
   - Can test individual transitions
   - Mock shared store for isolated testing

4. **Extensibility**
   - Add new parsing modes by adding nodes and transitions
   - No need to modify existing code
   - New features = new nodes

5. **Error Handling**
   - Centralized error handling through transitions
   - All errors flow to error handler node
   - Consistent error formatting

6. **State Management**
   - Shared store provides clear state boundaries
   - Easy to debug by inspecting shared store
   - No hidden state in class instances

7. **Composability**
   - This planner flow could be embedded in larger flows
   - Could have different planner variants as separate flows
   - Reuse nodes across different planning strategies

### PocketFlow Approach - CONS

1. **Learning Curve**
   - Developers need to understand PocketFlow patterns
   - Mental shift from imperative to flow-based thinking

2. **Debugging**
   - Stack traces go through PocketFlow orchestration
   - Need to understand flow execution model

3. **Simple Operations**
   - Some operations might feel over-engineered as nodes
   - E.g., string splitting as a full node

### Traditional Approach - PROS

1. **Familiarity**
   - Standard Python patterns everyone knows
   - Easier onboarding for new developers
   - Direct execution flow

2. **IDE Support**
   - Better autocomplete and type checking
   - Easier to navigate with "Go to Definition"

3. **Compact for Simple Logic**
   - One-line operations stay one line
   - Less boilerplate for trivial operations

### Traditional Approach - CONS

1. **Manual Everything**
   - Retry logic manually implemented
   - Error handling scattered throughout
   - State management via instance variables

2. **Hidden Control Flow**
   - Nested if/else blocks hide paths
   - Exception handling obscures flow
   - Hard to see all possible execution paths

3. **Testing Complexity**
   - Need to mock multiple methods
   - Complex setup for integration tests
   - Harder to test error paths

4. **Modification Friction**
   - Adding new parsing mode requires modifying existing methods
   - Changes ripple through the codebase
   - Risk of breaking existing functionality

5. **No Built-in Resilience**
   - Every retry/fallback manually coded
   - Inconsistent error handling patterns
   - Easy to miss edge cases

## Initial Verdict

After deep analysis, **PocketFlow is actually the better choice** for the planner because:

1. **Planners are inherently flow-based** - parsing → planning → validation → generation
2. **Reliability is crucial** - built-in retry/fallback for LLM calls is huge
3. **Multiple paths are common** - natural language vs CLI syntax routing
4. **State needs to be explicit** - shared store makes data flow visible
5. **Extensibility matters** - we'll add more planning strategies over time

The "overhead" I was worried about is negligible (simple method calls), while the benefits are substantial (retry, routing, testability).

## Comprehensive Architecture Analysis: Where PocketFlow Fits

### Understanding PocketFlow's True Nature

After examining the 100-line implementation, PocketFlow is:
- **A pattern**, not a framework
- **Zero runtime overhead** - just method calls and a while loop
- **Built-in resilience** - retry/fallback in 8 lines
- **Explicit state flow** - shared dictionary passed between nodes
- **Visual control flow** - `>>` and `-` operators make flow obvious

### Architecture Decision Framework

**USE POCKETFLOW when the component has:**
1. **Multiple discrete steps** with data flow between them
2. **External dependencies** that might fail (APIs, file I/O, network)
3. **Multiple execution paths** (branching, error handling)
4. **State that accumulates** through the process
5. **Retry/fallback requirements**
6. **Benefits from visual flow representation**

**USE TRADITIONAL CODE when the component is:**
1. **Pure computation** with no external dependencies
2. **Single-purpose utilities** (validators, formatters)
3. **Data structures** (schemas, registries)
4. **Simple transformations** with no failure modes
5. **Performance-critical** inner loops

### Real Task Analysis: PocketFlow vs Traditional

#### Task 4: IR-to-PocketFlow Compiler

**PocketFlow Implementation**:
```python
class LoadIRNode(Node):
    """Load and parse JSON IR"""
    def exec(self, shared):
        ir_path = shared["ir_path"]
        with open(ir_path) as f:
            shared["ir_json"] = json.load(f)
        return "validate"

    def exec_fallback(self, shared, exc):
        shared["error"] = f"Failed to load IR: {exc}"
        return "error"

class ValidateIRNode(Node):
    """Validate IR against schema"""
    def __init__(self, schema):
        super().__init__(max_retries=1)
        self.schema = schema

    def exec(self, shared):
        ir = shared["ir_json"]
        try:
            validate_against_schema(ir, self.schema)
            shared["validated_ir"] = ir
            return "resolve_nodes"
        except ValidationError as e:
            shared["validation_errors"] = e.errors
            return "error"

class ResolveNodesNode(Node):
    """Dynamically import node classes from registry"""
    def __init__(self, registry):
        super().__init__(max_retries=3)  # Imports can be flaky
        self.registry = registry

    def exec(self, shared):
        ir = shared["validated_ir"]
        node_instances = {}

        for node_spec in ir["nodes"]:
            node_type = node_spec["type"]
            metadata = self.registry.get(node_type)

            if not metadata:
                shared["missing_node"] = node_type
                return "node_not_found"

            # Dynamic import
            module = importlib.import_module(metadata["module"])
            node_class = getattr(module, metadata["class_name"])

            # Verify inheritance
            if not issubclass(node_class, BaseNode):
                shared["invalid_node"] = node_type
                return "invalid_node"

            node_instances[node_spec["id"]] = node_class()

        shared["node_instances"] = node_instances
        return "build_flow"

class BuildFlowNode(Node):
    """Construct PocketFlow with connections"""
    def exec(self, shared):
        ir = shared["validated_ir"]
        nodes = shared["node_instances"]

        flow = Flow()

        # Add all nodes
        for node_id, node in nodes.items():
            flow.add_node(node)

        # Connect based on edges
        for edge in ir.get("edges", []):
            from_node = nodes[edge["from"]]
            to_node = nodes[edge["to"]]
            action = edge.get("action", "default")

            from_node - action >> to_node

        # Set start node
        if "start_node" in ir:
            flow.start(nodes[ir["start_node"]])

        shared["compiled_flow"] = flow
        return "success"

# Build compiler flow
def create_compiler_flow(schema, registry):
    flow = Flow()

    load = LoadIRNode()
    validate = ValidateIRNode(schema)
    resolve = ResolveNodesNode(registry)
    build = BuildFlowNode()
    error = ErrorHandlerNode()

    flow.add_nodes(load, validate, resolve, build, error)

    load - "validate" >> validate
    load - "error" >> error

    validate - "resolve_nodes" >> resolve
    validate - "error" >> error

    resolve - "build_flow" >> build
    resolve - "node_not_found" >> error
    resolve - "invalid_node" >> error

    build - "success" >> flow.end

    return flow
```

**Benefits of PocketFlow here**:
- ✅ Clear separation of concerns
- ✅ Built-in error handling at each step
- ✅ Automatic retry for flaky imports
- ✅ Visual flow makes debugging easy
- ✅ Each step independently testable

**Traditional Implementation**:
```python
def compile_ir_to_flow(ir_path, schema, registry):
    try:
        # Load IR
        with open(ir_path) as f:
            ir_json = json.load(f)
    except Exception as e:
        raise CompilerError(f"Failed to load IR: {e}")

    # Validate
    try:
        validate_against_schema(ir_json, schema)
    except ValidationError as e:
        raise CompilerError(f"Invalid IR: {e.errors}")

    # Resolve nodes
    node_instances = {}
    for node_spec in ir_json["nodes"]:
        node_type = node_spec["type"]
        metadata = registry.get(node_type)

        if not metadata:
            raise CompilerError(f"Unknown node: {node_type}")

        # Dynamic import with retries
        for attempt in range(3):
            try:
                module = importlib.import_module(metadata["module"])
                node_class = getattr(module, metadata["class_name"])
                break
            except ImportError as e:
                if attempt == 2:
                    raise CompilerError(f"Failed to import {node_type}: {e}")
                time.sleep(0.5)

        if not issubclass(node_class, BaseNode):
            raise CompilerError(f"Invalid node class: {node_type}")

        node_instances[node_spec["id"]] = node_class()

    # Build flow
    flow = Flow()
    # ... connection logic ...

    return flow
```

**Verdict: PocketFlow wins** - Multiple steps, external dependencies, clear error paths

#### Task 5: Node Discovery (Filesystem Scanning)

**Traditional Implementation is Better**:
```python
class NodeScanner:
    def __init__(self):
        self.discovered_nodes = {}

    def scan_directory(self, directory: Path) -> Dict[str, NodeMetadata]:
        """Scan directory for BaseNode subclasses"""
        for py_file in directory.rglob("*.py"):
            if py_file.name.startswith("_"):
                continue

            module_path = self._file_to_module(py_file)

            try:
                module = importlib.import_module(module_path)

                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, BaseNode) and obj != BaseNode:
                        node_name = self._get_node_name(obj)
                        self.discovered_nodes[node_name] = {
                            "module": module_path,
                            "class_name": name,
                            "docstring": obj.__doc__,
                            "file_path": str(py_file)
                        }
            except Exception as e:
                logger.warning(f"Failed to scan {py_file}: {e}")
                continue

        return self.discovered_nodes
```

**Why traditional is better here**:
- ✅ Single cohesive operation (directory traversal)
- ✅ No complex state flow between steps
- ✅ Performance matters (many files)
- ✅ Simple error handling (skip bad files)
- ❌ PocketFlow would add unnecessary ceremony

**Verdict: Traditional wins** - Single operation, no complex flow

#### Task 8: Shell Integration

**PocketFlow Implementation**:
```python
class DetectStdinNode(Node):
    """Check if stdin has piped data"""
    def exec(self, shared):
        if not sys.stdin.isatty():
            shared["has_stdin"] = True
            return "read_stdin"
        else:
            shared["has_stdin"] = False
            return "no_stdin"

class ReadStdinNode(Node):
    """Read piped stdin content"""
    def __init__(self):
        super().__init__(max_retries=3)

    def exec(self, shared):
        try:
            # Read with timeout
            content = self._read_with_timeout(sys.stdin, timeout=5)
            shared["stdin"] = content
            return "process_stdin"
        except TimeoutError:
            return "timeout"

    def exec_fallback(self, shared, exc):
        shared["stdin_error"] = "Failed to read stdin"
        return "error"

class StreamLargeStdinNode(Node):
    """Handle large stdin with streaming"""
    def exec(self, shared):
        stdin_size = shared.get("stdin_size_hint", 0)

        if stdin_size > 1_000_000:  # 1MB
            # Stream in chunks
            chunks = []
            for chunk in self._stream_stdin():
                chunks.append(chunk)
                if len(chunks) > 1000:
                    shared["stdin_chunks"] = chunks
                    return "process_chunks"

            shared["stdin"] = "".join(chunks)

        return "process_complete"

# Shell integration flow
def create_shell_flow():
    flow = Flow()

    detect = DetectStdinNode()
    read = ReadStdinNode()
    stream = StreamLargeStdinNode()

    flow.add_nodes(detect, read, stream)

    detect - "read_stdin" >> read
    detect - "no_stdin" >> flow.end

    read - "process_stdin" >> check_size
    read - "timeout" >> timeout_handler
    read - "error" >> error_handler

    # ... more complex flow for different stdin scenarios
```

**Benefits of PocketFlow**:
- ✅ Multiple paths (stdin/no stdin/timeout)
- ✅ Retry logic for flaky stdin
- ✅ Clear flow for different scenarios
- ✅ Streaming vs batch decision flow

**Verdict: PocketFlow wins** - Multiple paths, I/O operations, timeout handling

#### Task 9: Proxy Pattern (NodeAwareSharedStore)

**Traditional Implementation is Better**:
```python
class NodeAwareSharedStore:
    """Proxy for transparent key mapping around collisions"""

    def __init__(self, shared: dict, current_node: str, mappings: dict):
        self._shared = shared
        self._current_node = current_node
        self._mappings = mappings.get(current_node, {})

    def __getitem__(self, key: str) -> Any:
        # Check if key needs mapping
        mapped_key = self._mappings.get("inputs", {}).get(key, key)

        if mapped_key not in self._shared:
            raise KeyError(f"Required key '{key}' not found in shared store")

        return self._shared[mapped_key]

    def __setitem__(self, key: str, value: Any) -> None:
        # Map output keys
        mapped_key = self._mappings.get("outputs", {}).get(key, key)
        self._shared[mapped_key] = value

    def get(self, key: str, default=None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

def detect_collisions(node_interfaces: List[NodeInterface]) -> List[Collision]:
    """Detect key collisions between nodes"""
    key_usage = defaultdict(list)

    for interface in node_interfaces:
        for key in interface.outputs:
            key_usage[key].append((interface.node_name, "output"))
        for key in interface.inputs:
            key_usage[key].append((interface.node_name, "input"))

    collisions = []
    for key, usages in key_usage.items():
        outputs = [u for u in usages if u[1] == "output"]
        if len(outputs) > 1:
            collisions.append(Collision(key, outputs))

    return collisions
```

**Why traditional is better**:
- ✅ Pure data structure with no external dependencies
- ✅ Performance-critical (called on every key access)
- ✅ Simple, focused responsibility
- ❌ No benefit from flow structure

**Verdict: Traditional wins** - Pure computation, performance matters

#### Task 17: LLM-based Workflow Generation

**PocketFlow Implementation**:
```python
class ParseUserInputNode(Node):
    """Initial parsing of user request"""
    def exec(self, shared):
        user_input = shared["user_input"]

        # Detect input type
        if ">>" in user_input:
            shared["input_type"] = "cli_syntax"
            shared["needs_parsing"] = True
            return "parse_cli"
        elif user_input.startswith('"') and user_input.endswith('"'):
            shared["input_type"] = "natural_language"
            shared["query"] = user_input.strip('"')
            return "generate_context"
        else:
            # Ambiguous - could be either
            shared["input_type"] = "ambiguous"
            return "classify_input"

class ClassifyInputNode(Node):
    """Use simple heuristics to classify ambiguous input"""
    def exec(self, shared):
        user_input = shared["user_input"]

        # Check if it contains known node names
        if any(node in user_input for node in shared["known_nodes"]):
            shared["input_type"] = "cli_syntax"
            return "parse_cli"
        else:
            shared["input_type"] = "natural_language"
            shared["query"] = user_input
            return "generate_context"

class GenerateContextNode(Node):
    """Build context with available nodes for LLM"""
    def __init__(self, context_builder):
        super().__init__()
        self.context_builder = context_builder

    def exec(self, shared):
        registry = shared["registry"]
        context = self.context_builder.build_context(registry)
        shared["llm_context"] = context
        return "plan_workflow"

class PlanWorkflowNode(Node):
    """Generate workflow using LLM"""
    def __init__(self, llm_client):
        super().__init__(max_retries=3, wait=2)
        self.llm = llm_client

    def exec(self, shared):
        prompt = self._build_prompt(
            shared["query"],
            shared["llm_context"],
            shared.get("previous_error")
        )

        response = self.llm.generate(prompt)

        try:
            workflow_json = self._extract_json(response)
            shared["generated_workflow"] = workflow_json
            return "validate_workflow"
        except JSONParseError:
            shared["parse_error"] = "LLM response was not valid JSON"
            return "retry_with_correction"

    def exec_fallback(self, shared, exc):
        shared["llm_error"] = f"Failed to generate workflow: {exc}"
        return "fallback_to_template"

class ValidateWorkflowNode(Node):
    """Validate generated workflow"""
    def __init__(self, validator):
        super().__init__()
        self.validator = validator

    def exec(self, shared):
        workflow = shared["generated_workflow"]

        validation_result = self.validator.validate(workflow)

        if validation_result.is_valid:
            shared["validated_workflow"] = workflow
            return "check_templates"
        else:
            shared["validation_errors"] = validation_result.errors
            shared["previous_error"] = validation_result.error_summary
            return "retry_with_feedback"

class ResolveTemplatesNode(Node):
    """Check template variables can be resolved"""
    def exec(self, shared):
        workflow = shared["validated_workflow"]
        available_vars = shared.get("available_vars", {})

        unresolved = self._find_unresolved_templates(workflow, available_vars)

        if unresolved:
            shared["unresolved_templates"] = unresolved
            return "prompt_for_values"
        else:
            shared["final_workflow"] = workflow
            return "success"

# Workflow generation flow
def create_workflow_generator_flow(llm_client, context_builder, validator):
    flow = Flow()

    parse = ParseUserInputNode()
    classify = ClassifyInputNode()
    context = GenerateContextNode(context_builder)
    plan = PlanWorkflowNode(llm_client)
    validate = ValidateWorkflowNode(validator)
    resolve = ResolveTemplatesNode()

    flow.add_nodes(parse, classify, context, plan, validate, resolve)

    # Input routing
    parse - "parse_cli" >> cli_parser
    parse - "generate_context" >> context
    parse - "classify_input" >> classify

    classify - "parse_cli" >> cli_parser
    classify - "generate_context" >> context

    # LLM planning flow
    context - "plan_workflow" >> plan

    plan - "validate_workflow" >> validate
    plan - "retry_with_correction" >> plan  # Self-loop with correction
    plan - "fallback_to_template" >> template_selector

    validate - "check_templates" >> resolve
    validate - "retry_with_feedback" >> plan  # Back to planning with error info

    resolve - "success" >> flow.end
    resolve - "prompt_for_values" >> value_prompter

    return flow
```

**Why PocketFlow is perfect here**:
- ✅ Complex branching logic (CLI vs natural language)
- ✅ LLM calls that need retry
- ✅ Multiple validation and retry loops
- ✅ Clear state accumulation
- ✅ Self-documenting flow

**Verdict: PocketFlow wins big** - This is exactly what PocketFlow excels at

### Architecture Zones in pflow

Based on this analysis, here's how pflow's architecture should be organized:

#### Zone 1: PocketFlow-based Components (Orchestration & I/O)
```
src/pflow/
├── flows/              # All PocketFlow-based orchestration
│   ├── planner/        # Natural language workflow generation
│   │   ├── planner_flow.py
│   │   └── nodes/
│   │       ├── parse_nodes.py
│   │       ├── llm_nodes.py
│   │       └── validation_nodes.py
│   ├── compiler/       # IR to PocketFlow compilation
│   │   ├── compiler_flow.py
│   │   └── nodes/
│   │       ├── loader_nodes.py
│   │       └── builder_nodes.py
│   ├── shell/          # Shell integration flow
│   │   └── shell_flow.py
│   └── discovery/      # Node discovery flow (if complex)
│       └── discovery_flow.py
```

#### Zone 2: Traditional Components (Data & Computation)
```
src/pflow/
├── core/               # Pure data structures and utilities
│   ├── schemas.py      # IR schema definitions
│   ├── proxy.py        # NodeAwareSharedStore
│   └── validators.py   # Pure validation functions
├── registry/           # Registry data management
│   ├── scanner.py      # Filesystem scanning
│   └── metadata.py     # Metadata extraction
├── utils/              # General utilities
│   ├── templates.py    # Template resolution
│   └── formatters.py   # Output formatting
└── cli/                # CLI entry points
    └── main.py         # Click commands (delegates to flows)
```

#### Zone 3: Mixed Components (Platform Nodes)
```
src/pflow/
└── nodes/              # All platform nodes (inherit from BaseNode)
    ├── file/           # File I/O nodes
    ├── github/         # GitHub API nodes
    ├── git/            # Git command nodes
    ├── llm/            # LLM interaction nodes
    └── shell/          # Shell execution nodes
```

### Decision Matrix

| Component | PocketFlow? | Why |
|-----------|------------|-----|
| Planner | ✅ Yes | Multiple paths, LLM retry, complex state |
| IR Compiler | ✅ Yes | Multi-step process, import failures |
| Shell Integration | ✅ Yes | I/O operations, timeouts, branching |
| Node Discovery | ❌ No | Single operation, performance matters |
| Proxy/SharedStore | ❌ No | Pure data structure, performance critical |
| Validators | ❌ No | Pure functions, no external deps |
| Template Resolver | ❌ No | Simple string manipulation |
| Metadata Extractor | ❌ No | Pure parsing, no flow needed |
| CLI Commands | ❌ No | Simple delegation to flows |
| Platform Nodes | ✅ Yes | Already BaseNode, external I/O |

### Key Insights

1. **PocketFlow for Orchestration**: Any component that orchestrates multiple operations should use PocketFlow

2. **Traditional for Pure Logic**: Data structures, pure computations, and utilities stay traditional

3. **The 3-Step Rule**: If it has 3+ steps with data flow between them, consider PocketFlow

4. **External Dependencies Rule**: If it touches external systems (files, APIs, network), PocketFlow's retry mechanism is valuable

5. **Performance Rule**: Hot paths (like proxy key access) should avoid any overhead

6. **Testability Bonus**: PocketFlow nodes are individually testable, making complex flows easier to verify

### Final Architecture Recommendation

**Core Principle**: Use PocketFlow as the "nervous system" of pflow - it handles all the coordination, I/O, and error-prone operations. Use traditional code as the "muscles" - pure computation and data manipulation.

This gives us:
- **Reliability**: Built-in retry/fallback for all I/O operations
- **Clarity**: Visual flows for complex orchestration
- **Performance**: No overhead for pure computations
- **Testability**: Isolated nodes for complex operations
- **Maintainability**: Clear separation of concerns

## Critical Architecture Decision

Based on this comprehensive analysis, the answer to your original question is nuanced:

### YES, We Are Underutilizing PocketFlow

But not in the way you might think. We should use PocketFlow for:

1. **All Major pflow Operations** that have multiple steps:
   - Workflow planning (Task 17)
   - IR compilation (Task 4)
   - Shell integration (Task 8)
   - Workflow execution with tracing (Task 23)
   - Approval and storage flows (Task 20)

2. **Any Operation with External Dependencies**:
   - File I/O operations
   - API calls (LLM, GitHub)
   - User interaction flows
   - Import/discovery operations

3. **Complex Control Flow**:
   - Error handling and retry
   - Branching logic
   - Validation chains

### NO, We Should Not Use PocketFlow Everywhere

Keep traditional code for:

1. **Pure Utilities**:
   - String manipulation
   - Data validation
   - Schema definitions
   - Template resolution

2. **Performance-Critical Code**:
   - SharedStore proxy (called on every key access)
   - JSON parsing
   - Path manipulations

3. **Simple Data Structures**:
   - Registry storage
   - Configuration objects
   - CLI argument parsing

### The Hidden Insight

Your instinct was correct - we were thinking too traditionally. PocketFlow's 100-line implementation means it's not a "framework" we're committing to, it's a **pattern** that makes our code more reliable and maintainable.

**The real architecture insight**: pflow itself is a compiler that produces PocketFlow flows. Using PocketFlow internally to build this compiler is not circular - it's **leveraging the same pattern at different abstraction levels**.

It's like how compilers are often written in the language they compile (bootstrapping). We're using the flow pattern to build a tool that helps users create flows.

### Recommended Next Steps

1. **Refactor the planner** (Task 17) to use PocketFlow immediately - it's the perfect fit
2. **Build the IR compiler** (Task 4) as a PocketFlow - multi-step with error handling
3. **Keep traditional code for** Task 5 (scanner), Task 9 (proxy), Task 6 (schemas)
4. **Use PocketFlow for** any new component that orchestrates multiple operations

This hybrid approach gives us the best of both worlds: reliability and clarity where it matters, simplicity and performance where it counts.
