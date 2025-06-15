# Type-Safe Action Flows: Making the Architecture Rigid

*This document explores how to add type safety and compile-time checks to the unified flow action routing pattern.*

---

## The Type Safety Challenge

With the current design, several things can go wrong at runtime:
1. Missing action implementation in ExecuteNode
2. Incorrect parameter types passed to actions
3. Mismatched input/output schemas
4. No compile-time verification of action completeness

## Solution 1: Protocol-Based Type Safety

### Using Python Protocols for Action Implementations

```python
from typing import Protocol, Dict, Any, List, runtime_checkable
from abc import ABC, abstractmethod
import inspect

@runtime_checkable
class ActionImplementation(Protocol):
    """Protocol that all action implementations must follow."""

    def get_schema(self) -> Dict[str, Any]:
        """Return the tool schema for this action."""
        ...

    def execute(self, **kwargs) -> Any:
        """Execute the action with given parameters."""
        ...

class GetIssueAction:
    """Implementation for get-issue action."""

    def get_schema(self) -> Dict[str, Any]:
        return {
            "name": "get-issue",
            "description": "Get issue details",
            "inputSchema": {
                "properties": {
                    "repo": {"type": "string"},
                    "issue": {"type": "integer"}
                },
                "required": ["repo", "issue"]
            }
        }

    def execute(self, repo: str, issue: int) -> Dict[str, Any]:
        # Actual implementation
        return {"number": issue, "title": "Example", "repo": repo}

class TypeSafeExecuteNode(Node):
    """Execute node with compile-time action verification."""

    def __init__(self, actions: Dict[str, ActionImplementation]):
        super().__init__()
        self.actions = actions

        # Verify all actions implement the protocol
        for name, action in actions.items():
            if not isinstance(action, ActionImplementation):
                raise TypeError(f"Action {name} does not implement ActionImplementation protocol")

    def exec(self, prep_res):
        action_name, params = prep_res

        if action_name not in self.actions:
            raise ValueError(f"No implementation for action: {action_name}")

        action = self.actions[action_name]
        return action.execute(**params)

# Usage - type checker will verify completeness
def create_github_flow():
    actions = {
        "get-issue": GetIssueAction(),
        "create-issue": CreateIssueAction(),  # Must implement ActionImplementation
    }

    get_tools = GitHubGetToolsNode(actions)  # Pass actions for consistency
    decide = GitHubDecideNode()
    execute = TypeSafeExecuteNode(actions)

    get_tools >> decide >> execute
    return Flow(start=get_tools)
```

## Solution 2: Enum-Based Action Registry

### Using Enums for Compile-Time Action Verification

```python
from enum import Enum, auto
from typing import Dict, Type, Callable

class GitHubAction(Enum):
    """All available GitHub actions."""
    GET_ISSUE = "get-issue"
    CREATE_ISSUE = "create-issue"
    LIST_PRS = "list-prs"
    CREATE_PR = "create-pr"

class ActionRegistry:
    """Type-safe action registry."""

    def __init__(self):
        self._implementations: Dict[GitHubAction, Callable] = {}
        self._schemas: Dict[GitHubAction, Dict] = {}

    def register(self, action: GitHubAction, schema: Dict, implementation: Callable):
        """Register an action with its schema and implementation."""
        self._implementations[action] = implementation
        self._schemas[action] = schema

    def get_implementation(self, action: GitHubAction) -> Callable:
        if action not in self._implementations:
            raise NotImplementedError(f"Action {action} not implemented")
        return self._implementations[action]

    def get_all_schemas(self) -> List[Dict]:
        """Get all registered schemas for GetToolsNode."""
        return list(self._schemas.values())

    def verify_complete(self):
        """Verify all enum actions have implementations."""
        missing = []
        for action in GitHubAction:
            if action not in self._implementations:
                missing.append(action)

        if missing:
            raise NotImplementedError(f"Missing implementations for: {missing}")

# Build registry with compile-time verification
def build_github_registry() -> ActionRegistry:
    registry = ActionRegistry()

    # Register each action
    registry.register(
        GitHubAction.GET_ISSUE,
        schema={
            "name": "get-issue",
            "inputSchema": {"properties": {"repo": {"type": "string"}, "issue": {"type": "integer"}}}
        },
        implementation=lambda repo, issue: {"number": issue, "repo": repo}
    )

    registry.register(
        GitHubAction.CREATE_ISSUE,
        schema={
            "name": "create-issue",
            "inputSchema": {"properties": {"repo": {"type": "string"}, "title": {"type": "string"}}}
        },
        implementation=lambda repo, title, body: {"number": 123, "title": title}
    )

    # This will raise if any action is missing
    registry.verify_complete()

    return registry
```

## Solution 3: Type-Safe Action Dispatch with TypedDict

### Using TypedDict for Parameter Validation

```python
from typing import TypedDict, Union, Literal, overload
from typing_extensions import NotRequired

class GetIssueParams(TypedDict):
    repo: str
    issue: int

class CreateIssueParams(TypedDict):
    repo: str
    title: str
    body: str
    labels: NotRequired[List[str]]

ActionParams = Union[GetIssueParams, CreateIssueParams]

class TypedExecuteNode(Node):
    """Execute node with typed parameter handling."""

    @overload
    def execute_action(self, action: Literal["get-issue"], params: GetIssueParams) -> Dict: ...

    @overload
    def execute_action(self, action: Literal["create-issue"], params: CreateIssueParams) -> Dict: ...

    def execute_action(self, action: str, params: ActionParams) -> Dict:
        """Type-safe action execution."""
        if action == "get-issue":
            # Type checker knows params is GetIssueParams here
            return self._get_issue(params["repo"], params["issue"])
        elif action == "create-issue":
            # Type checker knows params is CreateIssueParams here
            return self._create_issue(params["repo"], params["title"], params["body"])
        else:
            raise ValueError(f"Unknown action: {action}")
```

## Solution 4: Metaclass-Based Validation

### Using Metaclasses for Automatic Verification

```python
from typing import Dict, Set, Callable

class ActionMeta(type):
    """Metaclass that verifies all declared actions are implemented."""

    def __new__(cls, name, bases, attrs):
        # Get declared actions
        declared_actions = attrs.get('ACTIONS', {})

        # Find implemented action methods
        implemented = set()
        for attr_name, attr_value in attrs.items():
            if attr_name.startswith('_execute_') and callable(attr_value):
                action_name = attr_name.replace('_execute_', '').replace('_', '-')
                implemented.add(action_name)

        # Verify all declared actions are implemented
        declared_set = set(declared_actions.keys())
        missing = declared_set - implemented
        extra = implemented - declared_set

        if missing:
            raise NotImplementedError(
                f"Class {name} missing implementations for actions: {missing}"
            )

        if extra:
            raise ValueError(
                f"Class {name} has implementations for undeclared actions: {extra}"
            )

        return super().__new__(cls, name, bases, attrs)

class GitHubExecuteNode(Node, metaclass=ActionMeta):
    """Execute node with automatic verification."""

    ACTIONS = {
        "get-issue": {...},
        "create-issue": {...},
        "list-prs": {...}
    }

    def _execute_get_issue(self, repo: str, issue: int) -> Dict:
        return {"number": issue}

    def _execute_create_issue(self, repo: str, title: str, body: str) -> Dict:
        return {"number": 123}

    # If _execute_list_prs is missing, class creation will fail!
```

## Solution 5: Complete Type-Safe Flow Architecture

### Combining All Approaches

```python
from dataclasses import dataclass
from typing import Generic, TypeVar, Type
from abc import ABC, abstractmethod

T = TypeVar('T')

@dataclass
class ActionSpec(Generic[T]):
    """Complete specification for an action."""
    name: str
    description: str
    params_type: Type[T]
    input_schema: Dict[str, Any]
    implementation: Callable[[T], Any]

class TypeSafePlatformFlow(ABC):
    """Base class for type-safe platform flows."""

    @abstractmethod
    def get_action_specs(self) -> Dict[str, ActionSpec]:
        """Return all action specifications."""
        pass

    def __init__(self):
        # Verify all specs have implementations
        specs = self.get_action_specs()
        for name, spec in specs.items():
            if not callable(spec.implementation):
                raise TypeError(f"Action {name} missing implementation")

        # Build the flow
        get_tools = self._create_get_tools_node(specs)
        decide = UniversalDecideNode()
        execute = self._create_execute_node(specs)

        get_tools >> decide >> execute
        super().__init__(start=get_tools)

    def _create_get_tools_node(self, specs: Dict[str, ActionSpec]) -> Node:
        """Create tools node from specifications."""

        class ToolsNode(Node):
            def exec(self, prep_res):
                return [
                    {
                        "name": spec.name,
                        "description": spec.description,
                        "inputSchema": spec.input_schema
                    }
                    for spec in specs.values()
                ]

            def post(self, shared, prep_res, exec_res):
                shared["tools"] = exec_res
                shared["tool_map"] = {tool["name"]: tool for tool in exec_res}
                shared["spec_map"] = specs
                return "default"

        return ToolsNode()

    def _create_execute_node(self, specs: Dict[str, ActionSpec]) -> Node:
        """Create type-safe execute node."""

        class ExecuteNode(Node):
            def exec(self, prep_res):
                action_name, params = prep_res

                if action_name not in specs:
                    raise ValueError(f"No spec for action: {action_name}")

                spec = specs[action_name]

                # Validate parameters match expected type
                # In real implementation, use pydantic or similar
                return spec.implementation(params)

        return ExecuteNode()

# Usage with complete type safety
class GitHubFlow(TypeSafePlatformFlow):
    def get_action_specs(self) -> Dict[str, ActionSpec]:
        return {
            "get-issue": ActionSpec(
                name="get-issue",
                description="Get issue details",
                params_type=GetIssueParams,
                input_schema={
                    "properties": {
                        "repo": {"type": "string"},
                        "issue": {"type": "integer"}
                    }
                },
                implementation=self._get_issue
            ),
            "create-issue": ActionSpec(
                name="create-issue",
                description="Create new issue",
                params_type=CreateIssueParams,
                input_schema={
                    "properties": {
                        "repo": {"type": "string"},
                        "title": {"type": "string"},
                        "body": {"type": "string"}
                    }
                },
                implementation=self._create_issue
            )
        }

    def _get_issue(self, params: GetIssueParams) -> Dict:
        return {"number": params["issue"], "repo": params["repo"]}

    def _create_issue(self, params: CreateIssueParams) -> Dict:
        return {"number": 123, "title": params["title"]}
```

## Development-Time Verification

### 1. Pre-commit Hook
```python
# verify_actions.py
def verify_all_platform_flows():
    """Verify all platform flows have complete implementations."""

    for flow_class in get_all_flow_classes():
        if hasattr(flow_class, 'ACTIONS'):
            verify_action_implementations(flow_class)
```

### 2. Test Generation
```python
def generate_action_tests(flow_class):
    """Generate tests for all declared actions."""

    for action_name in flow_class.ACTIONS:
        test_name = f"test_{action_name.replace('-', '_')}"
        test_func = create_action_test(flow_class, action_name)
        setattr(TestClass, test_name, test_func)
```

### 3. Static Analysis with mypy Plugin
```python
# mypy_pflow_plugin.py
def check_action_completeness(ctx):
    """mypy plugin to verify action implementations."""
    # Check that all ACTIONS have corresponding _execute_ methods
```

## Recommended Approach

The best balance of type safety and usability is **Solution 5** with:

1. **ActionSpec dataclass** for complete action specification
2. **Abstract base class** requiring `get_action_specs()`
3. **Automatic verification** in `__init__`
4. **Type-safe parameters** using TypedDict
5. **Development-time checks** via tests and linting

This provides:
- ✅ Compile-time verification of action completeness
- ✅ Type-safe parameter passing
- ✅ Clear error messages for missing implementations
- ✅ IDE support for parameter types
- ✅ Maintainable and extensible architecture

The slight additional complexity is worth it for the type safety guarantees, especially as the number of platforms and actions grows.
