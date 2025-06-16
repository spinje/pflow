# Template Variable System ($variable) Analysis Across pflow Docs

## Summary of Findings

The template variable system (`$variable` syntax) is mentioned across multiple documents but lacks a single, authoritative definition. This creates redundancy and potential confusion about where this concept is formally specified.

## 1. Where is it Formally Defined?

**No single canonical definition exists.** The concept is scattered across multiple documents without a clear "source of truth."

## 2. Template Variable Mentions by Document

### architecture.md
- **Lines 210-278**: Most comprehensive explanation found
- **Context**: CLI Layer section (5.1.2 Template Resolution System)
- **Content**:
  - Explains template variables as shared store lookups
  - Shows examples: `$code_report → shared["code_report"]`
  - Details the resolution process and error handling
  - Provides workflow examples with template variables

### planner.md
- **Lines 79-89, 246-348**: Extensive coverage
- **Context**: Natural Language Path responsibilities
- **Content**:
  - Emphasizes template string composition as a core planner responsibility
  - Shows template variable dependency tracking
  - Provides detailed examples of template string generation
  - Includes JSON response format for template composition

### cli-runtime.md
- **Lines 479-532**: Brief mention
- **Context**: Template Resolution section
- **Content**:
  - References that template variables exist
  - Points to other documents for details
  - No substantial new information

### shared-store.md
- **Lines 35-88**: Good practical explanation
- **Context**: Template Variable Resolution section
- **Content**:
  - Explains the pattern with examples
  - Shows how variables create dependencies between nodes
  - Discusses missing input handling

### prd.md
- **Lines 57-67**: Very brief mention
- **Context**: Template variables in CLI commands
- **Content**:
  - Shows template variables in examples
  - No detailed explanation

## 3. Inconsistencies Found

1. **Depth of Coverage**: Some documents provide extensive detail (architecture.md, planner.md) while others barely mention it (prd.md)

2. **Conceptual Ownership**:
   - architecture.md treats it as a CLI feature
   - planner.md treats it as a planning/composition feature
   - shared-store.md treats it as a data flow pattern

3. **Examples Vary**: Different documents use different examples, making it unclear which are canonical

## 4. Recommendations

### 4.1 Logical Home for the Concept

**Recommendation**: Create a dedicated section in `shared-store.md` as the canonical definition.

**Rationale**:
- Template variables are fundamentally about data flow between nodes via the shared store
- The shared store document already discusses data flow patterns
- It's a natural fit conceptually

### 4.2 Canonical Definition Structure

```markdown
## Template Variable System

### Overview
Template variables provide dynamic content substitution in node inputs using the `$variable` syntax. At runtime, `$variable` is replaced with the value from `shared["variable"]`.

### Syntax
- Format: `$variable_name`
- Resolution: `$variable_name` → `shared["variable_name"]`
- Context: Used in CLI flags and node input templates

### Examples
[Include 2-3 canonical examples]

### Variable Dependencies
[Explain how variables create execution order dependencies]

### Error Handling
[What happens when a variable is not found]
```

### 4.3 Documents That Should Link to Canonical Source

1. **architecture.md** (Lines 210-278)
   - Replace detailed explanation with brief summary
   - Add: "For complete template variable documentation, see [shared-store.md#template-variable-system]"

2. **planner.md** (Lines 79-89, 246-348)
   - Keep planner-specific aspects (template composition)
   - Add link to canonical definition for syntax/resolution details

3. **cli-runtime.md** (Lines 479-532)
   - Remove redundant explanation
   - Simply reference the canonical source

4. **prd.md**
   - Add brief explanation with link to canonical source
   - Ensure consistency in examples

### 4.4 Unique Value by Document

Each document should only explain aspects unique to its context:

- **shared-store.md**: Canonical syntax, resolution, and data flow
- **architecture.md**: How CLI layer handles template parsing
- **planner.md**: How planner generates template strings and tracks dependencies
- **cli-runtime.md**: Runtime resolution implementation details
- **prd.md**: High-level product perspective only

## 5. Implementation Steps

1. **Write canonical definition** in shared-store.md
2. **Update architecture.md** to link to canonical source
3. **Update planner.md** to focus on generation, not syntax
4. **Update cli-runtime.md** to remove redundancy
5. **Add brief explanation to prd.md** with link
6. **Ensure all examples are consistent** across documents

This consolidation will improve documentation clarity and reduce maintenance burden while ensuring users can find authoritative information about template variables in one place.
