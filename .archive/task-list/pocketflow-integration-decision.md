# PocketFlow Integration Decision

## Decision: Use PocketFlow Directly Without Wrapper Classes

After deep analysis of both pocketflow and pflow requirements, we've decided to:

1. **Remove task #30** - No wrapper classes needed
2. **Use pocketflow directly** - Import and inherit as intended
3. **Focus on what pflow uniquely adds** - CLI, registry, IR compilation

## Key Changes Made

### 1. Removed Task #30
- Eliminated proposed `PflowNode` and `PflowFlow` wrapper classes
- These wrappers added zero value and unnecessary complexity

### 2. Updated Task #2: Shared Store Validation
- Changed from creating a `SharedStore` class to simple validation functions
- PocketFlow already provides the dict pattern - we just need validators:
  - `validate_reserved_keys(shared)`
  - `validate_natural_patterns(shared)`
  - `resolve_template_variables(text, shared)`

### 3. Updated Task #21: IR Compiler
- Clarified it compiles JSON IR to `pocketflow.Flow`, not reimplementing execution
- PocketFlow's `Flow` class IS the execution engine
- Focus on IR→Flow conversion and template resolution

### 4. Updated All Node Tasks
- All nodes now explicitly inherit from `pocketflow.Node`
- Use the standard prep→exec→post pattern directly
- No abstraction layers between nodes and framework

## Implementation Pattern

```python
# Direct usage - simple and clear
from pocketflow import Node, Flow

class ReadFileNode(Node):
    def prep(self, shared):
        return shared.get("file_path")

    def exec(self, file_path):
        with open(file_path) as f:
            return f.read()

    def post(self, shared, prep_res, exec_res):
        shared["content"] = exec_res
        return "default"
```

## Benefits

1. **Simpler code** - No unnecessary abstraction layers
2. **Clearer architecture** - Direct use of proven patterns
3. **Less maintenance** - Fewer classes to maintain
4. **Better performance** - No wrapper overhead
5. **Easier onboarding** - Developers learn one framework, not two

## Principle

> "We're building a CLI tool, not a framework on top of a framework"

PocketFlow is already well-designed. We should use it as intended rather than wrapping it. pflow adds value through orthogonal features: CLI interface, node registry, JSON IR, and template resolution.
