# Task 17 Architecture Review: Parameter Discovery Design Update

After reviewing the architecture file and our discussion about parameter discovery design, I've identified a fundamental improvement needed in how ParameterDiscoveryNode works. The current design has it returning a simple list of values, but it should extract parameters WITH names from the natural language query.

## Architectural Improvement Needed

### Current Design Issue
The current ParameterDiscoveryNode returns a list:
```python
# Input: "fix issue 1234 in repo pflow"
# Output: ["1234", "pflow"]  # Just values, no context
```

This creates unnecessary complexity:
- ValidatorNode can't properly validate templates without knowing parameter names
- GeneratorNode has to guess which value maps to which parameter
- Type inconsistency between list and dict throughout the flow

### Improved Design
ParameterDiscoveryNode should extract named parameters from the start:
```python
# Input: "fix github issue 1234 in the pflow repo"
# Output: {
#     "issue_number": "1234",
#     "repo_name": "pflow"
# }
```

## Required Updates

### 1. Update ParameterDiscoveryNode Implementation

**Location**: Lines 356-393

**Change**: Update the node to extract parameters with intelligent naming:
```python
class ParameterDiscoveryNode(Node):
    """Extract named parameters from natural language BEFORE workflow generation.

    This node discovers concrete values WITH their contextual names, providing
    a proper parameter dictionary for the generator to use.
    """
    def exec(self, user_input):
        # Extract parameters with names using LLM
        prompt = f"""
        Extract parameters with appropriate names from: {user_input}

        Examples:
        - "fix issue 1234" → {{"issue_number": "1234"}}
        - "analyze sales data from yesterday" → {{"data_type": "sales", "date": "2024-01-14"}}
        - "deploy version 2.1.0 to staging" → {{"version": "2.1.0", "environment": "staging"}}

        Return as JSON object with descriptive parameter names.
        """

        discovered_params = self.llm.extract(prompt, schema=dict[str, str])
        return discovered_params

    def post(self, shared, prep_res, exec_res):
        shared["discovered_params"] = exec_res  # Now a proper dict
        return "generate"
```

### 2. Update ParameterMappingNode

**Location**: Lines 411 and 423

**Change**: Update to expect dict instead of list:
- Line 411: `discovered_values = shared.get("discovered_params", {})`
- Remove the conditional logic that treats discovered_values as a list
- Simplify the mapping logic since we already have named parameters

### 3. Update ValidatorNode

**Location**: Lines 532-558

**Change**: Use consistent naming and remove type conversion:
```python
def prep(self, shared):
    return {
        "workflow": shared.get("generated_workflow", {}),
        "discovered_params": shared.get("discovered_params", {}),  # Already a dict
        "registry": shared.get("registry")
    }

def exec(self, prep_res):
    # 1. Structure validation
    validate_ir(workflow)

    # 2. Full template validation - no conversion needed
    errors = TemplateValidator.validate_workflow_templates(
        workflow,
        prep_res["discovered_params"],  # Already in correct format
        prep_res["registry"]
    )
```

### 4. Update Flow Documentation

**Location**: Various sections mentioning discovered_values as a list

**Change**: Update all references to show discovered parameters as a dictionary with proper names.

### 5. Update Shared State Example

**Location**: Lines 623-651

**Change**: Update to show discovered_params as a dict:
```python
# Discovery phase
"discovered_params": {
    "issue_number": "123",
    "repo_name": "pflow"
},
```

## Benefits of This Design

1. **Consistency**: Same dict type flows through the entire system
2. **Clarity**: Parameter names are discovered once and used throughout
3. **Validation**: ValidatorNode can properly validate templates
4. **Simplicity**: No type conversions or guessing of parameter mappings
5. **Context Preservation**: The semantic meaning from natural language is preserved

## Additional Recommendations

1. **Rename consistently**: Use `discovered_params` throughout instead of `discovered_values`
2. **Update comments**: Remove all mentions of list-to-dict conversion
3. **Simplify helper methods**: ParameterMappingNode's logic becomes much simpler

## Conclusion

This design change makes the architecture much cleaner by having ParameterDiscoveryNode do intelligent extraction with naming from the start. All the context needed for parameter naming IS in the query, and this approach leverages that fact. The workflow generator can then use these pre-named parameters directly, eliminating type mismatches and complex mapping logic.

This aligns better with the principle that each node should do one thing well - ParameterDiscoveryNode discovers parameters (with names), not just values.
