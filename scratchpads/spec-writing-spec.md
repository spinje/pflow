# Feature: Write_Executable_Specification

## Objective
Create deterministic specification document for code implementation.

## Inputs
- `feature_request`: str - Natural language description of desired functionality
- `codebase_context`: dict
  - `relevant_files`: list[str] - Paths to files that will be modified or referenced
  - `existing_patterns`: list[str] - Current code patterns to follow
  - `constraints`: list[str] - Technical or architectural limitations

## Outputs
- Returns: Markdown document with exactly these sections in order:
  1. `# Feature: <extracted_feature_name>`
  2. `## Objective`
  3. `## Requirements`
  4. `## Scope`
  5. `## Inputs`
  6. `## Outputs`
  7. `## Rules`
  8. `## Edge Cases`
  9. `## Test Criteria`
  10. `## Notes (Why)`

## Rules
### 1. Extract Feature Name
- Convert feature_request to snake_case noun
- Max 30 characters
- Example: "add caching to API calls" → "api_call_cache"

### 2. Write Objective Section
- Single sentence, max 15 words
- Format: "Verb noun that achieves outcome"
- No conjunctions (and, or, but)

### 3. Define Requirements Section
- List what must exist or be true before implementation
- One requirement per line
- Format: "- Thing that exists/is available"
- No conditional requirements ("if X then need Y")
- Include: dependencies, permissions, data sources

### 4. Define Scope Section
- List what this feature does NOT do
- One exclusion per line
- Format: "- Does not [verb] [noun]"
- Include: related features explicitly excluded
- No positive statements about what it does do

### 5. Define Inputs Section
- List each parameter with:
  - `name`: type - Description
- Use Python type hints syntax
- Include all required inputs first, optional last
- No prose between items

### 6. Define Outputs Section
- Start with "Returns: " or "Side effects: "
- Specify exact type or structure
- Include all possible output states
- No ambiguous terms ("appropriate", "correct", "optimal")

### 7. Write Rules Section
- Number each rule
- Each rule = single testable assertion
- Format: "If X then Y" or "Do Z"
- No rules combining multiple behaviors with "and"
- Order by execution sequence

### 8. List Edge Cases
- One edge case per line
- Format: "Condition → behavior"
- Cover: empty inputs, None values, type mismatches, boundary conditions
- No explanations why edge case matters

### 9. Create Test Criteria
- Number each test
- Each test has:
  - Setup conditions
  - Expected output
- Minimum 1 test per rule
- Minimum 1 test per edge case
- Use concrete values, not variables

### 10. Add Notes Section
- Explain design decisions only
- No implementation hints
- Each note = one line
- Start with dash (-)

## Edge Cases
- feature_request contains multiple unrelated features → reject with error
- codebase_context missing required keys → use empty defaults
- feature_request under 5 words → require more detail
- feature_request over 200 words → extract core feature only
- Conflicting constraints in context → list conflicts in Notes

## Test Criteria
1. Validate structure
   - Input: Any valid spec
   - Output: All 10 sections present in correct order

2. Test rule atomicity
   - Input: Spec with "Do X and Y" rule
   - Output: Validation fails - rules must be singular

3. Test input completeness
   - Input: Spec missing parameter types
   - Output: Validation fails - all inputs need types

4. Test edge case format
   - Input: Edge case with explanation
   - Output: Validation fails - edge cases are conditions only

5. Test objective brevity
   - Input: Objective with 20 words
   - Output: Validation fails - max 15 words

6. Test requirements format
   - Input: Requirement with conditional "if X then Y"
   - Output: Validation fails - no conditionals in requirements

7. Test scope negativity
   - Input: Scope item "Handles user authentication"
   - Output: Validation fails - scope must be negative statements

8. Test requirements presence
   - Input: Feature with no prerequisites
   - Output: Requirements section contains "- None" only

9. Test scope presence
   - Input: Feature that could be confused with related features
   - Output: Scope section has at least 2 exclusions

## Notes (Why)
- Rigid structure enables consistent parsing
- Type annotations prevent ambiguity
- Numbered rules enable precise error messages
- Separation of behavior (Rules) from rationale (Notes) maintains clarity
