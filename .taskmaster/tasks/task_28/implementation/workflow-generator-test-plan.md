# Workflow Generator Test Plan - Quality Over Quantity

## Core Insight: What Makes Workflow Generation HARD

After deep analysis, the hardest challenges are:
1. **Template Variable Semantics**: Distinguishing `${user_input}` from `${node.output}`
2. **Complex Data Flow**: 4-6 nodes with proper output→input chaining
3. **Namespacing Compliance**: Output mapping with `source` field
4. **Validation Recovery**: Fixing errors on retry attempts
5. **Purpose Quality**: Contextual, specific purposes (not generic)

## Test Design Philosophy

### What We're Testing
- **Correctness**: Does it generate valid, executable workflows?
- **Data Flow**: Do nodes properly chain outputs to inputs?
- **Template Usage**: No hardcoding, proper variable references?
- **Structural Validity**: Passes IR validation?
- **Recovery**: Can it fix validation errors?

### What We're NOT Testing
- Exact JSON formatting
- Specific field ordering
- Confidence scores
- Internal reasoning
- Prompt text itself

## The 10 HARD Test Cases

### Category 1: Complex Multi-Node Workflows (4 tests)

#### Test 1: `changelog_pipeline` (6 nodes)
**User Input**: "Create a comprehensive changelog by fetching the last 30 closed issues from anthropic/pflow, analyze them with AI to categorize by type (bug/feature/docs), generate a formatted changelog with sections, save it to CHANGELOG.md, commit the changes, and create a PR"

**Why Hard**:
- 6 nodes with complex data flow
- Multiple template variables (repo, issue_count, file_path)
- Node outputs feed into next nodes
- Mix of GitHub, LLM, file, and git operations

**Must Generate**:
```
github-list-issues → llm-categorize → llm-format → write-file → git-commit → github-create-pr
```

**Critical Validations**:
- `${fetch_issues.issues}` → llm input (NOT user input)
- `${categorize.response}` → format input
- `${format_changelog.response}` → file content
- All user inputs declared (repo_owner, repo_name, issue_count, changelog_path)

#### Test 2: `data_analysis_pipeline` (5 nodes)
**User Input**: "Read sales data from data/2024-sales.csv, filter for Q4 records where revenue > 10000, analyze trends with AI, generate visualization code, and save both the analysis report and code to outputs folder"

**Why Hard**:
- CSV → filter → analyze → generate → save pattern
- Node output transformation between steps
- Multiple outputs from single workflow
- Parameter extraction from file paths

**Must Generate**:
```
read-file → filter-data → llm-analyze → llm-generate-viz → write-file (x2)
```

**Critical Validations**:
- `${read_data.content}` used by filter
- `${filter.output}` used by analysis
- Two write operations with different content sources

#### Test 3: `release_automation` (5 nodes)
**User Input**: "Generate release notes from git log since tag v1.2.0, create GitHub release with the notes, build the project, upload artifacts to the release, and notify slack channel #releases"

**Why Hard**:
- Git → GitHub → build → upload flow
- External service integration (Slack)
- Artifact handling between nodes
- Tag/version parameter usage

**Must Generate**:
```
git-log → llm-notes → github-create-release → build-project → github-upload-assets
```

#### Test 4: `migration_workflow` (4 nodes)
**User Input**: "Backup production database to backups/2024-01-15/prod.sql, run migration scripts from migrations folder, verify data integrity, and generate migration report"

**Why Hard**:
- Critical operations requiring careful sequencing
- Path construction from parameters
- Verification step depends on migration output
- Report generation from verification results

### Category 2: Template Variable Confusion Tests (3 tests)

#### Test 5: `content_generation_trap`
**User Input**: "Generate a blog post about Python testing best practices, review it for technical accuracy, then save the final content to blog/testing-guide.md"

**Why Hard**:
- Classic trap: "content" seems like user input but is generated
- Must NOT declare "content" in inputs
- Must use `${generate_post.response}` for file content

**Critical Validation**:
- "content" NOT in inputs section
- `${generate_post.response}` used in write-file params

#### Test 6: `parameter_vs_output`
**User Input**: "Fetch user profile for user_id 12345, extract their preferences, generate personalized recommendations based on preferences, and email the recommendations to their address"

**Why Hard**:
- user_id is user input
- preferences are node output
- email address is extracted from profile (node output)
- Tempting to declare preferences/email as inputs

**Must Distinguish**:
- Inputs: user_id only
- Node outputs: profile, preferences, email, recommendations

#### Test 7: `nested_references`
**User Input**: "Read configuration from config.yaml, use the API endpoint from config to fetch data, process the data according to rules in config, and save to the output path specified in config"

**Why Hard**:
- Config values are node outputs, not user inputs
- Multiple values extracted from single node output
- Nested access patterns (config.api_endpoint, config.output_path)

### Category 3: Validation Recovery Tests (3 tests)

#### Test 8: `fix_validation_errors`
**Context**: Retry attempt with validation errors:
- "Template variable ${repository} not defined in inputs"
- "Node type 'github_commits' not found - did you mean 'github-list-commits'?"
- "Declared input 'output_file' never used as template variable"

**Why Hard**:
- Must parse and fix multiple error types
- Correct node type names
- Add missing inputs
- Remove unused inputs

#### Test 9: `output_mapping_fix`
**Context**: Retry with error: "Workflow output 'changelog' must have 'description' and 'source' fields"

**Previous attempt** had:
```json
"outputs": {
  "changelog": "${save_file.written}"  // WRONG
}
```

**Must Fix To**:
```json
"outputs": {
  "changelog": {
    "description": "Generated changelog file path",
    "source": "${save_file.written}"
  }
}
```

#### Test 10: `purpose_quality_enforcement`
**Context**: Retry with feedback: "Node purposes too generic: 'Process data', 'Use LLM', 'Write file'"

**Why Hard**:
- Must generate specific, contextual purposes
- Each purpose must explain role in THIS workflow
- 10-200 character limit
- No generic descriptions

## Expected Outcomes

Each test should validate:

### Structural Validity
- [ ] Valid IR structure with all required fields
- [ ] Correct node types from registry
- [ ] Linear workflow (no branching)
- [ ] All edges properly defined

### Template Variable Correctness
- [ ] User inputs declared in "inputs" section
- [ ] Node outputs NOT declared as inputs
- [ ] All template variables used
- [ ] No hardcoded values

### Data Flow Integrity
- [ ] Each node's output properly referenced by consumers
- [ ] Correct use of `${node_id.output_key}` pattern
- [ ] Workflow outputs have "source" field

### Purpose Quality
- [ ] Every node has a purpose field
- [ ] Purposes are specific to workflow context
- [ ] 10-200 characters
- [ ] Not generic placeholders

## Test Implementation Strategy

### 1. Parametrized Structure
```python
@dataclass
class WorkflowTestCase:
    name: str
    user_input: str
    discovered_params: dict
    planning_context: str
    browsed_components: dict
    validation_errors: Optional[List[str]]  # For retry tests
    expected_nodes: List[str]  # Node types in order
    min_nodes: int
    max_nodes: int
    must_have_inputs: List[str]
    must_not_have_inputs: List[str]
    node_output_refs: List[str]  # Expected ${node.output} patterns
    category: str
    why_hard: str
```

### 2. Validation Functions
```python
def validate_workflow(workflow: dict, test_case: WorkflowTestCase) -> tuple[bool, str]:
    """Comprehensive validation of generated workflow."""
    # Check structural validity
    # Verify template usage
    # Validate data flow
    # Check purpose quality
    # Return (passed, failure_reason)
```

### 3. Parallel Execution
- Use pytest.mark.parametrize
- Each test case is independent
- Real-time failure reporting via file
- Support for parallel workers

## Success Metrics

- **Quality**: Each test validates a genuinely hard problem
- **Coverage**: All major failure modes covered
- **Performance**: <15 seconds with parallel execution
- **Cost**: <$0.02 per full test run
- **Clarity**: Clear failure messages explaining what went wrong

## Why These Tests Matter

These aren't toy examples - they represent real developer workflows:
- **Changelog generation**: Every project needs this
- **Data analysis**: Common business requirement
- **Release automation**: Critical DevOps task
- **Database migration**: High-stakes operation
- **Content generation**: Increasingly common use case

By testing these complex scenarios, we ensure the workflow generator can handle real-world requirements, not just simple demos.

## Implementation Priority

1. **First**: Implement test framework with parametrization
2. **Second**: Add the 4 complex workflow tests
3. **Third**: Add template confusion tests
4. **Fourth**: Add validation recovery tests
5. **Finally**: Run full suite and refine based on results

This approach ensures we have working tests quickly, then progressively add harder cases.