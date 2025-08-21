# Component Browsing Test Suite Redesign Plan

## Context & Key Insights

### ComponentBrowsingNode Receives Two Types of Requests

**Type 1: Failed Path A Discovery (60% of real usage)**
- Vague requests with clear domain context that couldn't match existing workflows
- Example: `"generate changelog"` → no existing workflow found → ComponentBrowsingNode gets original vague input
- **Challenge**: Must select broad domain-relevant components from minimal context

**Type 2: Explicit Path B Creation (40% of real usage)**
- Detailed workflow requirements from users creating new workflows from scratch
- Example: `"create changelog from 20 GitHub issues, write to CHANGELOG.md, commit and open PR"`
- **Easier**: Clear requirements guide specific component selection

### ComponentBrowsingNode's Role
- **Smart curator**: Select components to make downstream jobs easier
- **Domain-aware**: Understand workflow domains (GitHub, data processing, automation)
- **Over-inclusive within domain**: Better to include extra relevant components than miss critical ones
- **Excludes irrelevant domains**: Don't select file operations for GitHub API tasks

## Current Test Suite Problems

❌ **Too Basic**: "copy files from src to dest" - not workflow-worthy, too simple
❌ **Wrong Complexity**: Simple file operations don't represent real workflow creation
❌ **Missing Domain Context**: Don't test domain-based component selection
❌ **Ignores North Star**: Don't use established north star examples as reference
❌ **Poor Path A/B Mix**: Don't reflect the reality that most requests come from failed discovery

## Redesigned Test Strategy

### Domain-Driven Test Design

**1. GitHub Automation Domain (Primary - Complex)**
- **North Star Reference**: Changelog generation, issue triage, release automation
- **Components Available**: `github-list-issues`, `github-create-pr`, `github-get-issue`, `git-*`, `llm`, `write-file`
- **Vague → Explicit Spectrum**: "generate changelog" → full north star changelog workflow

**2. Data Processing Domain (Secondary - Medium)**
- **North Star Reference**: CSV analysis, report generation, data transformation
- **Components Available**: `read-file`, `write-file`, `llm` (no GitHub/Git)
- **Vague → Explicit Spectrum**: "analyze data" → "analyze CSV files from data/ folder, generate insights"

**3. Automation Domain (Tertiary - Simple)**
- **North Star Reference**: Simple file processing, basic automation
- **Components Available**: Various combinations depending on automation type
- **Vague → Explicit Spectrum**: "automate tasks" → specific automation workflows

### Test Categories (12 total tests)

#### GitHub Domain Tests (5 tests)
1. **`changelog_vague`** (Failed Discovery)
   - Input: `"generate changelog"`
   - Expected: `[github-list-issues, llm, write-file, git-commit, github-create-pr]`
   - Must NOT: `[delete-file, move-file]` (irrelevant to changelog domain)
   - Why: Tests domain-aware selection from vague failed discovery

2. **`changelog_explicit`** (Direct Creation)
   - Input: `"create changelog from last 20 GitHub issues, write to CHANGELOG.md, commit changes, open PR titled 'Release v1.3'"`
   - Expected: `[github-list-issues, llm, write-file, git-checkout, git-commit, github-create-pr]`
   - Must NOT: `[delete-file, move-file]`
   - Why: Tests explicit north star example component selection

3. **`issue_triage_vague`** (Failed Discovery)
   - Input: `"triage issues"`
   - Expected: `[github-list-issues, llm, write-file]`
   - Must NOT: `[git-push, delete-file]`
   - Why: Tests medium complexity GitHub workflow domain

4. **`issue_analysis_explicit`** (Direct Creation)
   - Input: `"analyze the last 50 open GitHub issues, categorize by priority and type, write report to triage/report-2025-08-21.md"`
   - Expected: `[github-list-issues, llm, write-file]`
   - Must NOT: `[github-create-pr, git-push]` (no PR needed for analysis)
   - Why: Tests explicit medium complexity workflow

5. **`github_simple`** (Direct Creation)
   - Input: `"get details for GitHub issue 1234 and summarize it"`
   - Expected: `[github-get-issue, llm, write-file]`
   - Must NOT: `[git-commit, github-create-pr]` (simple read operation)
   - Why: Tests simple GitHub workflow

#### Data Processing Domain Tests (4 tests)
1. **`data_analysis_vague`** (Failed Discovery)
   - Input: `"analyze data"`
   - Expected: `[read-file, llm, write-file]`
   - Must NOT: `[github-list-issues, git-commit]` (no GitHub/Git needed)
   - Why: Tests vague data processing domain selection

2. **`csv_analysis_explicit`** (Direct Creation)
   - Input: `"read CSV files from data/ folder, analyze sales trends, generate insights report to reports/sales-analysis.md"`
   - Expected: `[read-file, llm, write-file]`
   - Must NOT: `[github-list-issues, git-commit]`
   - Why: Tests explicit data processing workflow

3. **`file_processing_vague`** (Failed Discovery)
   - Input: `"process files"`
   - Expected: `[read-file, write-file, llm]`
   - Must NOT: `[github-create-pr]` (no GitHub API needed)
   - Why: Tests broad file processing selection

4. **`report_generation_explicit`** (Direct Creation)
   - Input: `"read log files from logs/ directory, extract error patterns, generate summary report"`
   - Expected: `[read-file, llm, write-file]`
   - Must NOT: `[github-list-issues, delete-file]`
   - Why: Tests explicit log analysis workflow

#### Edge Cases & Ambiguous Requests (3 tests)
1. **`very_vague_automation`** (Failed Discovery)
   - Input: `"help me automate tasks"`
   - Expected: `[llm]` (minimum - need intelligence to understand what to automate)
   - Must NOT: `[]` (be permissive for very vague requests)
   - Why: Tests extremely vague request handling

2. **`mixed_domain_request`** (Direct Creation)
   - Input: `"analyze GitHub issues and generate local report files"`
   - Expected: `[github-list-issues, llm, write-file]`
   - Must NOT: `[git-commit]` (analysis task, no version control needed)
   - Why: Tests cross-domain component selection

3. **`unclear_intent`** (Failed Discovery)
   - Input: `"do something with data"`
   - Expected: `[read-file, llm, write-file]` (assume file-based data processing)
   - Must NOT: `[]` (should make reasonable assumptions)
   - Why: Tests handling of ambiguous domain requests

## Implementation Plan

### Phase 1: Replace Current Tests (2 hours)
1. Delete all current test cases in `get_test_cases()`
2. Implement the 12 new test cases following the domain-driven design
3. Update test workflows in fixture to support GitHub domain testing
4. Ensure each test has clear rationale and realistic expectations

### Phase 2: Validate Against North Star (1 hour)
1. Cross-check test inputs against north star examples in `docs/vision/north-star-examples.md`
2. Ensure complexity levels match: Primary (5 tests), Secondary (4 tests), Tertiary (3 tests)
3. Verify component expectations match realistic workflow patterns

### Phase 3: Run and Analyze (1 hour)
1. Execute new test suite with current prompt
2. Analyze failure patterns - are they due to prompt issues or unrealistic expectations?
3. Adjust expectations if needed based on real component availability

### Phase 4: Document Rationale (30 min)
1. Update test docstrings to explain the domain-driven approach
2. Document why each test represents realistic ComponentBrowsingNode usage
3. Link to north star examples where applicable

## Success Criteria

**Test Suite Quality**:
- ✅ 60% failed discovery scenarios, 40% explicit creation
- ✅ Domain-driven organization (GitHub, Data, Edge cases)
- ✅ North star complexity levels represented
- ✅ Realistic component selection expectations
- ✅ Clear exclusion logic (what NOT to select)

**Behavioral Testing**:
- ✅ Tests domain-aware component curation
- ✅ Tests over-inclusive within domain, exclusive across domains
- ✅ Tests both vague and explicit input handling
- ✅ Focuses on selection decisions, not confidence scores

**Implementation Readiness**:
- ✅ All test cases follow `test_discovery_prompt.py` pattern exactly
- ✅ Real-time failure reporting for parallel execution
- ✅ Proper parametrization for accuracy measurement
- ✅ Clear documentation of why each test matters

This redesigned test suite will properly validate ComponentBrowsingNode's role as a smart domain-aware component curator, reflecting real usage patterns and north star workflow complexity.