# Discovery Prompt Test Improvements Analysis

## Current Test Coverage Assessment

### What We Have
The current discovery prompt tests (`test_discovery_prompt.py`, `test_path_a_reuse.py`) cover:

1. **Basic functionality**:
   - Simple workflow matching ("I want to read a file and analyze its contents")
   - Model configuration changes
   - Error handling with invalid models

2. **Edge cases**:
   - Workflow file not found after LLM match
   - Corrupted workflow JSON handling (bug documented)
   - Vague requests ("Do something with the thing using the stuff")

3. **Sample workflows tested**:
   - `read-and-analyze-file`
   - `process-csv-data`
   - `github-issue-tracker`

### Critical Gaps Identified

Based on the North Star examples and real-world usage patterns, we're missing tests for:

## 1. Ambiguous Reuse Decisions (The Hard Cases)

These are scenarios where it's genuinely difficult to determine if we should reuse or create new:

### A. Version/Variant Scenarios
**User has "generate-changelog" workflow, but asks for slightly different version:**

```python
# Existing workflow: "generate-changelog"
# - Takes last 20 closed issues
# - Writes to CHANGELOG.md
# - Creates PR

# Test Case 1: Minor parameter difference
"generate a changelog for version 1.4"  # Should REUSE - just different version param

# Test Case 2: Significant structural difference
"generate a changelog from merged PRs instead of closed issues"  # Should CREATE NEW - different data source

# Test Case 3: Output format difference
"generate a changelog and display it in the console"  # Ambiguous - could reuse with modification or create new

# Test Case 4: Subset of functionality
"generate a changelog for the last 20 closed issues"  # Should REUSE - missing PR creation step is OK
```

### B. Generalization vs Specialization
**User has general workflow, asks for specific case (or vice versa):**

```python
# Existing workflow: "analyze-csv-files"
# - Reads all CSV files from folder
# - Combines and analyzes them

# Test Case 1: More specific request
"analyze sales.csv from the reports folder"  # Should REUSE - specific instance of general workflow

# Test Case 2: More general request
"process data files"  # Ambiguous - CSV is subset of data files

# Test Case 3: Different file type
"analyze JSON files from the data folder"  # Should CREATE NEW - different file type
```

### C. Workflow Composition Scenarios
**User request could be satisfied by combining existing workflows:**

```python
# Existing workflows: "fetch-github-issues", "generate-report"

# Test Case 1: Combined functionality
"fetch github issues and generate a report"  # Should CREATE NEW - not a single workflow

# Test Case 2: Extended workflow
"fetch github issues, generate a report, and email it"  # Should CREATE NEW - extends beyond existing
```

## 2. North Star Workflow Evolution Tests

Based on the examples, test the progression from specific to general requests:

### Initial Creation vs Reuse Pattern

```python
def test_north_star_changelog_evolution():
    """Test the full lifecycle of the changelog workflow from creation to reuse."""

    # Phase 1: Initial specific request (should CREATE)
    first_request = """generate a changelog for version 1.3 from the last 20 closed
                       issues from github, generating a changelog from them and then
                       writing it to versions/1.3/CHANGELOG.md and checkout a new
                       branch called create-changelog-version-1.3 and committing
                       the changes."""
    # Expected: CREATE NEW workflow

    # Phase 2: Slightly different parameters (should REUSE)
    second_request = "generate a changelog for version 1.4"
    # Expected: REUSE with different params

    # Phase 3: Vague request (should REUSE)
    third_request = "create changelog"
    # Expected: REUSE with high confidence

    # Phase 4: Significantly different structure (should CREATE)
    fourth_request = "generate changelog from git commits instead of github issues"
    # Expected: CREATE NEW - different data source
```

## 3. Confidence Threshold Edge Cases

Test scenarios where confidence should be borderline:

```python
def test_confidence_threshold_scenarios():
    """Test cases that should produce medium confidence (0.6-0.8)."""

    # Existing: "generate-issue-triage-report"
    # - Fetches last 50 open issues
    # - Categorizes by priority
    # - Writes to file

    test_cases = [
        {
            "request": "create a bug report",
            "expected_confidence": 0.6,  # Similar but not exact
            "expected_decision": "not_found"  # Below threshold
        },
        {
            "request": "triage open github issues",
            "expected_confidence": 0.85,  # Very close match
            "expected_decision": "found_existing"
        },
        {
            "request": "analyze github issues",
            "expected_confidence": 0.7,  # Generic analysis vs specific triage
            "expected_decision": "not_found"
        }
    ]
```

## 4. Semantic Similarity vs Structural Difference

Test cases where semantic meaning is similar but structure differs:

```python
def test_semantic_vs_structural_matching():
    """Test that discovery considers both meaning and structure."""

    # Existing: "backup-database"
    # - Dumps database
    # - Compresses
    # - Uploads to S3

    test_cases = [
        {
            "request": "save database to cloud",
            "should_match": True,  # Semantically equivalent
        },
        {
            "request": "export database to local file",
            "should_match": False,  # Missing cloud upload step
        },
        {
            "request": "backup files to S3",
            "should_match": False,  # Different source (files vs database)
        }
    ]
```

## 5. Parameter Extraction Hints

Test that discovery considers how easily parameters can be extracted:

```python
def test_parameter_extraction_consideration():
    """Test that discovery factors in parameter extraction difficulty."""

    # Existing: "send-email"
    # Required params: recipient, subject, body

    test_cases = [
        {
            "request": "send email to john@example.com about the meeting",
            "should_reuse": True,  # Clear parameters available
        },
        {
            "request": "send an email",
            "should_reuse": False,  # Missing critical parameters
        },
        {
            "request": "email the team",
            "should_reuse": False,  # Ambiguous recipient
        }
    ]
```

## Implementation Recommendations

### 1. Create Comprehensive Test Fixtures

```python
@pytest.fixture
def north_star_workflows():
    """Create the three north star example workflows."""
    return {
        "generate-changelog": { ... },
        "issue-triage-report": { ... },
        "summarize-issue": { ... }
    }

@pytest.fixture
def ambiguous_test_cases():
    """Test cases with expected confidence ranges."""
    return [ ... ]
```

### 2. Add Behavioral Test Categories

Create new test files in `tests/test_planning/llm/behavior/`:

- `test_discovery_ambiguous_cases.py` - Edge cases where decision is unclear
- `test_discovery_workflow_evolution.py` - Testing workflow lifecycle from creation to reuse
- `test_discovery_confidence_thresholds.py` - Testing confidence scoring accuracy
- `test_discovery_north_star_scenarios.py` - Specific north star workflow tests

### 3. Metrics to Track

For each test case, track:
- **Decision accuracy**: Did it make the right reuse/create decision?
- **Confidence calibration**: Is confidence aligned with decision difficulty?
- **Reasoning quality**: Does the reasoning explain the decision well?
- **Parameter consideration**: Did it consider parameter availability?

### 4. Test Data Structure

```python
class DiscoveryTestCase:
    user_input: str
    existing_workflows: list[dict]
    expected_decision: Literal["found_existing", "not_found"]
    expected_confidence_range: tuple[float, float]  # (min, max)
    expected_workflow_match: Optional[str]
    reasoning_must_mention: list[str]  # Key concepts in reasoning
    difficulty: Literal["easy", "medium", "hard", "ambiguous"]
```

## Priority Test Cases to Implement

### High Priority (Directly from North Star)

1. **Changelog workflow progression** - Full lifecycle test
2. **Issue triage variations** - Different phrasings of same intent
3. **Parameter-driven reuse** - "version 1.3" vs "version 1.4"

### Medium Priority (Common Edge Cases)

4. **Partial workflow matches** - Subset of existing workflow
5. **Workflow extension requests** - Existing + additional steps
6. **File type variations** - CSV vs JSON vs XML processing

### Lower Priority (Advanced Scenarios)

7. **Composite workflows** - Could combine multiple workflows
8. **Domain-specific language** - Technical vs casual descriptions
9. **Negative examples** - Completely unrelated requests

## Success Metrics

After implementing these tests, we should see:

1. **>90% accuracy** on unambiguous cases (easy/medium difficulty)
2. **>70% accuracy** on ambiguous cases (hard difficulty)
3. **Confidence calibration**: High confidence (>0.9) correlates with correct decisions
4. **Reasoning quality**: Mentions key differentiators in edge cases
5. **Performance**: Path A (reuse) triggered for appropriate cases, reducing 20-second generations

## Next Steps

1. Implement test fixtures with north star workflows
2. Create behavioral test file for ambiguous cases
3. Run tests with real LLM to establish baseline
4. Iterate on discovery prompt based on failure patterns
5. Track improvements in accuracy metrics

The goal is to make the discovery prompt sophisticated enough to handle the nuanced decisions that developers face when deciding whether to create new workflows or reuse existing ones.