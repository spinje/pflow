# Workflow Generator Test Improvements TODO

## Current State
- **Test Accuracy**: 100% (13/13 tests passing)
- **Approach**: Tests validate workflow quality, not compliance with discovered params
- **Validation**: Uses production WorkflowValidator with mock registry for future nodes

## Outstanding Issues to Address

### 1. Mock Nodes That Should Be Real
These nodes are currently mocked but should be implemented as they're basic operations:

#### GitHub Operations
- **`github-list-prs`** - Should be trivial, nearly identical to `github-list-issues`
- **`github-get-latest-tag`** - Basic GitHub API call
- **`github-create-release`** - Standard GitHub operation

#### Git Operations
- **`git-tag`** - Basic git command, we have git-commit, git-checkout, git-log
  - **UPDATE**: `git-get-latest-tag` has been implemented! Other tag operations (create, list, push) still need implementation

### 2. Vague Mock Nodes That Need Rethinking
These nodes are too generic and should be replaced with more specific operations:

#### Replace with Specific Nodes
- **`fetch-data`** → Should be `http-get` or `api-call` with specific purpose
- **`fetch-profile`** → Should be `github-get-user` or similar specific API
- **`filter-data`** → Could be `jq-filter`, `json-filter`, or multiple LLM calls
- **`validate-links`** → Could be specific tool or LLM with validation prompt

#### Future Claude-Code Nodes (Keep as Mocks)
These represent future agentic capabilities and should remain as mocks:
- **`analyze-code`** - Future claude-code node for code analysis
- **`analyze-structure`** - Future claude-code node for project structure analysis
- **`build-project`** - CI/CD operation, out of MVP scope

#### External Integrations (Keep as Mocks)
These are out of scope for MVP:
- **`slack-notify`** - External service integration
- **`run-migrations`** - Database operations
- **`backup-database`** - Database operations
- **`verify-data`** - Could be claude-code or specific validator

### 3. Test Cases That Don't Align with North Star Examples
Current tests use contrived scenarios. Should replace with real workflows from `docs/vision/north-star-examples.md`:

#### Priority Replacements
1. Replace vague data processing tests with **Issue Triage Report** (north star example)
2. Replace generic analysis tests with **Weekly Project Summary** (north star example)
3. Keep **Changelog Pipeline** - already aligns with north star

### 4. Parameter Discovery Philosophy
**Current Approach (Correct)**:
- `discovered_params` are hints, not requirements
- Generator has freedom to create better parameter structures
- Tests validate workflow quality, not parameter compliance

**No changes needed** - this is working as intended.

### 5. Output Field Name Knowledge
**Currently Fixed**:
- Added output names to context for all nodes
- Generator knows what each node outputs

**Potential Improvement**:
- Consider adding output descriptions for clarity
- Example: `Outputs: issues (array of GitHub issue objects)`

### 6. Future Claude-Code Node Design
**Current Understanding**:
- There will be ONE `claude-code` node type
- It takes `prompt`, `context`, and optionally `output_schema`
- It can return any structured data based on the schema
- `analyze-code`, `analyze-structure` etc. are just claude-code with different prompts

**Action**: Document this clearly in the test file comments

## Recommended Priority

### Phase 1: Implement Missing Basic Nodes (High Impact)
1. `github-list-prs` - Needed for north star examples
2. `github-get-latest-tag` - Common in release workflows
3. `git-tag` - Basic git operation

### Phase 2: Replace Vague Tests (Medium Impact)
1. Update test cases to use north star workflows
2. Remove reliance on vague nodes like `fetch-data`
3. Use specific, realistic node combinations

### Phase 3: Document Future Architecture (Low Impact, High Clarity)
1. Add comments explaining claude-code node concept
2. Document why certain nodes are mocked
3. Explain the validation approach

## Summary

The tests are currently passing at 100% with a pragmatic approach:
- Mock registry for future/external nodes
- Real nodes where they exist
- Validation of workflow quality over parameter compliance

The main improvements needed are:
1. Implementing a few missing basic nodes
2. Replacing vague test scenarios with north star examples
3. Better documentation of the mock vs real node strategy

The validation approach is solid and should not be changed - testing workflow quality over compliance is the right philosophy.