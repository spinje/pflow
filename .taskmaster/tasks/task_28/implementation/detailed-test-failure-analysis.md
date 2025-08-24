# Detailed Test Failure Analysis for Workflow Generator

## Failed Test 1: `data_analysis_pipeline` ❌

### What We're Sending
**User Input**: "Read sales data from data/2024-sales.csv, filter for Q4 records where revenue > 10000, analyze trends with AI, generate visualization code, and save both the analysis report and code to outputs folder"

**Discovered Parameters**:
- input_file: "data/2024-sales.csv"
- output_dir: "outputs"
- revenue_threshold: "10000"

### What We're Expecting
- **Node count**: 5-6 nodes
- **Expected flow**: read-file → filter-data → llm (analyze) → llm (generate viz) → write-file → write-file
- **Must have inputs**: input_file, output_dir, revenue_threshold
- **Must NOT have inputs**: data, filtered_data, analysis, visualization (these are node outputs)

### What Failed
**Error**: "Branching detected: node 'filter_q4_high_revenue' has 2 outgoing edges"

**This means**: The LLM created a workflow where the filter node connects to TWO different nodes simultaneously, creating a branch. This violates the LINEAR workflow constraint.

### Why This Test Matters
We're testing that the generator understands:
1. Multiple outputs need separate write-file nodes
2. Data flows linearly through transformations
3. User doesn't provide the data or analysis - only the starting file and output location

---

## Failed Test 2: `output_mapping_fix` ❌

### What We're Sending
**User Input**: "Generate and save a report"

**Discovered Parameters**:
- report_type: "monthly"
- output_path: "reports/monthly.md"

**Validation Errors** (this is a retry test):
- "Workflow output 'report_path' must have 'description' and 'source' fields"

### What We're Expecting
- **Node count**: 2-3 nodes (simple workflow)
- **Expected flow**: llm → write-file
- **Must fix**: Output structure to include both description and source fields
- **Purpose**: Test if the generator can FIX validation errors on retry

### What Failed
**Error**: "Too many nodes: 6 > 3"

**This means**: Instead of fixing the simple 2-node workflow, the LLM regenerated a much more complex 6-node workflow.

### Why This Test Matters
We're testing validation error recovery - can the LLM:
1. Parse the specific error about output structure
2. Fix JUST that issue without regenerating everything
3. Keep the workflow simple as originally intended

---

## Failed Test 3: `multi_output_workflow` ❌

### What We're Sending
**User Input**: "Analyze project structure, generate documentation for each module, create an index file linking all docs, and generate a summary report"

**Discovered Parameters**:
- project_path: "src/"
- docs_output: "docs/api/"

### What We're Expecting
- **Node count**: 5-8 nodes
- **Expected flow**: analyze-structure → llm (docs) → write-file → llm (index) → write-file → llm (summary) → write-file
- **Multiple outputs**: Documentation, index, AND summary (3 different files)

### What Failed
**Error**: "Too many nodes: 9 > 8"

**This means**: The LLM generated 9 nodes when we expected maximum 8. It's being thorough but exceeding our limit.

### Why This Test Matters
We're testing complex workflows with multiple outputs to ensure:
1. Each distinct output gets its own write-file node
2. The workflow handles multiple parallel outputs from single analysis
3. No shortcuts or combining multiple outputs into one node

---

## Failed Test 4: `multi_source_weekly_report` ❌

### What We're Sending
**User Input**: "Create comprehensive weekly report: fetch last 50 closed issues, fetch last 50 merged PRs, get commit statistics for the week, analyze trends across all data, generate trend visualizations, create executive summary, write detailed report to reports/weekly/, write summary to reports/summary.md, commit all reports, and send notification to Slack"

**Discovered Parameters**:
- issue_limit: "50"
- pr_limit: "50"
- report_dir: "reports/weekly/"
- summary_file: "reports/summary.md"
- slack_channel: "#weekly-updates"

### What We're Expecting
- **Node count**: 8-11 nodes
- **Must have inputs**: issue_limit, pr_limit, report_dir, summary_file, slack_channel
- This is an ULTRA-COMPLEX workflow combining multiple data sources

### What Failed
**Errors**:
1. "Missing required input: report_dir"
2. "Branching detected: node 'create_executive_summary' has 2 outgoing edges"

**This means**:
1. The LLM didn't declare report_dir as an input (even though it was in discovered_params)
2. The executive summary node connects to multiple nodes (branching)

### Why This Test Matters
This tests the limits - can the generator handle:
1. Multiple data sources (issues, PRs, commits)
2. Multiple analyses and outputs
3. Complex 10+ step workflows
4. Keeping everything linear

---

## Failed Test 5: `fix_validation_errors` ❌

### What We're Sending
**User Input**: "Generate changelog from GitHub issues"

**Discovered Parameters**:
- repository: "anthropic/pflow"
- limit: "20"

**Validation Errors** (retry test):
- "Template variable ${repository} not defined in inputs"
- "Node type 'github_commits' not found - did you mean 'github-list-commits'?"
- "Declared input 'output_file' never used as template variable"

### What We're Expecting
- **Node count**: 3-4 nodes (simple workflow)
- **Must fix**:
  1. Add 'repository' to inputs
  2. Correct the node type name
  3. Remove unused 'output_file' input

### What Failed
**Errors**:
1. "Too many nodes: 10 > 4"
2. "Missing required input: repository"
3. "Branching detected: node 'generate_changelog_content' has 2 outgoing edges"

**This means**: The LLM completely regenerated a 10-node workflow instead of fixing the 3-4 node one, and still didn't add 'repository' to inputs!

### Why This Test Matters
Critical test for error recovery - can the generator:
1. Parse specific validation errors
2. Make surgical fixes
3. NOT regenerate from scratch

---

## Failed Test 6: `full_release_pipeline` ❌

### What We're Sending
**User Input**: "Create a complete release pipeline: get the latest tag from GitHub, list all commits and issues since that tag, generate a comprehensive changelog, create release notes, write both to files, commit changes, create a PR for review, create a GitHub release after approval, and notify the #releases Slack channel about the new release"

This is the MOST COMPLEX test - a full 10+ step release automation.

### What We're Expecting
- **Node count**: 8-12 nodes
- Full pipeline from tag → commits/issues → changelog → release → notification

### What Failed
**Errors**:
1. "Branching detected: node 'get_latest_tag' has 2 outgoing edges"
2. "Branching detected: node 'generate_changelog' has 2 outgoing edges"

**This means**: Multiple nodes are creating branches, violating the linear constraint.

### Why This Test Matters
This is the ultimate test - a real-world release pipeline that developers actually need.

---

## Key Patterns in Failures

### 1. **Branching Problem** (4/6 failures)
The LLM creates non-linear workflows where one node connects to multiple next nodes. This suggests:
- The linear constraint isn't strong enough in the prompt
- OR the LLM naturally wants to parallelize for efficiency
- OR our test detection is too strict

### 2. **Node Count Issues** (3/6 failures)
Either too many or too few nodes suggests:
- The complexity guide isn't precise enough
- OR these workflows genuinely need more nodes than we expect
- OR the LLM is adding unnecessary steps

### 3. **Validation Recovery Failure** (2/6 failures)
Instead of fixing, the LLM regenerates, suggesting:
- The validation error patterns aren't clear enough
- OR the LLM's instinct is to start fresh
- OR our expectations are unrealistic

### 4. **Missing Inputs** (2/6 failures)
Not declaring required inputs suggests:
- The input rules aren't clear enough
- OR the LLM is confused about what's user-provided vs generated

## Questions to Consider

1. **Is linear-only too restrictive?** Real workflows often have parallel paths
2. **Are our node count expectations realistic?** Maybe 10+ nodes is normal for complex tasks
3. **Is validation recovery achievable?** Models might not be good at surgical fixes
4. **Are these tests too ambitious?** 10+ node workflows are genuinely complex