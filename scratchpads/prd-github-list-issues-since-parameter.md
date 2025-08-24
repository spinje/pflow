# Product Requirements Document: Add `--since` Parameter to `github-list-issues`

## Executive Summary

Add date filtering capability to the `github-list-issues` node to enable workflows that process issues created or updated after a specific date. This enhancement is critical for the "Weekly Project Summary" north star example and improves many time-based workflows.

## Problem Statement

### Current Limitation
The `github-list-issues` node can filter by state (open/closed/all) and limit count, but cannot filter by date. This prevents users from creating workflows that:
- Generate weekly/monthly summaries
- Process issues since last release
- Create time-based reports
- Monitor recent activity

### User Impact
Without date filtering, users must:
1. Fetch ALL issues (up to limit)
2. Parse dates in LLM or post-processing
3. Manually filter out old issues
4. Waste API calls and processing time

## Solution Overview

Add a `since` parameter that leverages GitHub CLI's existing `--search` capability with date queries. The implementation will:
1. Accept multiple date formats (ISO dates, relative dates, tags)
2. Build proper GitHub search syntax internally
3. Maintain backward compatibility
4. Follow existing node patterns exactly

## Technical Specification

### Interface Changes

```python
"""
List GitHub repository issues.

Interface:
- Reads: shared["repo"]: str  # Repository in owner/repo format (optional, default: current repo)
- Reads: shared["state"]: str  # Issue state: open, closed, all (optional, default: open)
- Reads: shared["limit"]: int  # Maximum issues to return (optional, default: 30)
- Reads: shared["since"]: str  # Filter issues created after this date (optional)
    # Accepts: ISO date (2025-08-20), relative (7 days ago), or YYYY-MM-DD
- Writes: shared["issues"]: list[dict]  # Array of issue objects
    - number: int  # Issue number
    - title: str  # Issue title
    - state: str  # Issue state (OPEN, CLOSED)
    - author: dict  # Issue author information
        - login: str  # Username
    - labels: list[dict]  # Issue labels
        - name: str  # Label name
    - createdAt: str  # Creation timestamp
    - updatedAt: str  # Last update timestamp
- Actions: default (always)
"""
```

### Implementation Details

#### 1. Parameter Extraction (in `prep()`)
```python
def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
    # ... existing auth check and repo/state/limit extraction ...

    # Extract since with fallback
    since = shared.get("since") or self.params.get("since")

    # Validate and normalize if provided
    if since:
        # Convert relative dates to ISO format
        normalized_since = self._normalize_date(since)
    else:
        normalized_since = None

    return {
        "repo": repo,
        "state": state,
        "limit": limit,
        "since": normalized_since
    }
```

#### 2. Date Normalization Helper
```python
def _normalize_date(self, date_str: str) -> str:
    """Convert various date formats to GitHub search format (YYYY-MM-DD).

    Supports:
    - ISO dates: 2025-08-20, 2025-08-20T10:30:00
    - Relative: "7 days ago", "1 week ago", "yesterday"
    - Date only: 2025-08-20

    Returns:
        String in YYYY-MM-DD format for GitHub search
    """
    import re
    from datetime import datetime, timedelta

    date_str = date_str.strip()

    # Already in YYYY-MM-DD format
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        return date_str

    # ISO datetime - extract date part
    if re.match(r'^\d{4}-\d{2}-\d{2}T', date_str):
        return date_str[:10]

    # Relative dates
    if "ago" in date_str.lower() or date_str.lower() == "yesterday":
        return self._parse_relative_date(date_str)

    # Try parsing as various formats
    for fmt in ["%Y/%m/%d", "%m/%d/%Y", "%d-%m-%Y"]:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    # If we can't parse it, let GitHub handle it
    # (might be a tag or other GitHub-specific format)
    return date_str
```

#### 3. Command Building (in `exec()`)
```python
def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
    """Execute GitHub CLI call with optional date filtering."""

    # Build base command
    cmd = ["gh", "issue", "list", "--json", "number,title,state,author,labels,createdAt,updatedAt"]

    # Add repo if specified
    if prep_res["repo"]:
        cmd.extend(["--repo", prep_res["repo"]])

    # Handle date filtering via search
    if prep_res["since"]:
        # Build search query combining state and date
        search_parts = []

        # Add date filter
        search_parts.append(f"created:>{prep_res['since']}")

        # Add state filter if not "all"
        if prep_res["state"] != "all":
            search_parts.append(f"is:{prep_res['state']}")

        search_query = " ".join(search_parts)
        cmd.extend(["--search", search_query])
    else:
        # Use traditional state flag when no date filter
        cmd.extend(["--state", prep_res["state"]])

    # Add limit
    cmd.extend(["--limit", str(prep_res["limit"])])

    # Execute command - NO try/except! Let exceptions bubble for retry
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        shell=False,  # CRITICAL: Security requirement
        timeout=30,
    )

    # ... rest of existing exec() code ...
```

### Backward Compatibility

The change is **fully backward compatible**:
- `since` parameter is optional
- When not provided, behavior is identical to current implementation
- Existing workflows continue to work unchanged
- No breaking changes to output format

### Error Handling

New error cases to handle in `exec_fallback()`:

```python
def exec_fallback(self, prep_res: dict[str, Any], exc: Exception) -> None:
    error_msg = str(exc)

    # ... existing error handlers ...

    # New error cases
    elif "Invalid query" in error_msg and prep_res.get("since"):
        raise ValueError(
            f"Invalid date format '{prep_res['since']}'. "
            f"Use ISO date (2025-08-20), relative date (7 days ago), or YYYY-MM-DD format."
        )
    elif "could not parse" in error_msg.lower():
        raise ValueError(
            f"GitHub couldn't parse the date '{prep_res['since']}'. "
            f"Try using YYYY-MM-DD format (e.g., 2025-08-20)."
        )
```

## Usage Examples

### Basic Date Filtering
```python
# Last week's issues
shared = {"since": "7 days ago", "limit": 50}

# Issues since specific date
shared = {"since": "2025-08-20", "state": "closed"}

# Issues created yesterday
shared = {"since": "yesterday", "state": "all"}
```

### Workflow Examples
```bash
# Weekly summary workflow
github-list-issues --since="7 days ago" --state=all >>
llm --prompt="Summarize this week's activity: ${issues}"

# Issues since last release (future enhancement with git-tag)
git-log --limit=1 --format="%aI" --grep="release" >>
github-list-issues --since="${commits[0].date}" >>
llm --prompt="Generate release notes from ${issues}"
```

## Testing Strategy

### Unit Tests

1. **Test date normalization**:
   - ISO dates: `2025-08-20`, `2025-08-20T10:30:00Z`
   - Relative dates: `7 days ago`, `1 week ago`, `yesterday`
   - Edge cases: empty string, invalid formats

2. **Test command building**:
   - With since only
   - With since + state
   - With since + state + repo
   - Without since (backward compatibility)

3. **Test error handling**:
   - Invalid date format
   - GitHub API errors with dates
   - Rate limiting

### Integration Tests

```python
@pytest.mark.skipif(not os.environ.get("RUN_GITHUB_TESTS"))
def test_since_parameter_filtering():
    """Test that since parameter actually filters issues."""
    node = ListIssuesNode()

    # Get all issues
    shared_all = {"limit": 10, "repo": "python/cpython"}
    node.run(shared_all)
    all_issues = shared_all["issues"]

    # Get recent issues
    shared_recent = {"limit": 10, "repo": "python/cpython", "since": "30 days ago"}
    node.run(shared_recent)
    recent_issues = shared_recent["issues"]

    # Verify filtering worked
    assert len(recent_issues) <= len(all_issues)

    # Verify all recent issues are actually recent
    cutoff = datetime.now() - timedelta(days=30)
    for issue in recent_issues:
        created = datetime.fromisoformat(issue["createdAt"].replace("Z", "+00:00"))
        assert created > cutoff
```

### Manual Testing Checklist

- [ ] Test with ISO date: `2025-08-20`
- [ ] Test with relative date: `7 days ago`
- [ ] Test with `yesterday`
- [ ] Test with invalid date format
- [ ] Test combining with state filter
- [ ] Test with custom repo
- [ ] Verify backward compatibility (no since parameter)
- [ ] Test with date far in future (no results)
- [ ] Test with very old date (many results)

## Performance Considerations

- **No additional API calls**: Uses same single `gh issue list` call
- **Search query overhead**: Minimal (~10ms) on GitHub's servers
- **Client-side filtering eliminated**: More efficient than fetching all and filtering
- **Rate limit friendly**: Reduces unnecessary data transfer

## Security Considerations

- **No shell injection**: Continues using `shell=False` pattern
- **Input validation**: Dates are normalized/validated before use
- **No sensitive data**: Date parameters are not sensitive
- **Existing auth model**: No changes to authentication flow

## Migration Path

1. **Phase 1**: Deploy updated node with since parameter
2. **Phase 2**: Update documentation with examples
3. **Phase 3**: Update planner prompts to use since when appropriate
4. **Phase 4**: Create example workflows showcasing the feature

## Success Metrics

- **Enables north star example**: Weekly Project Summary workflow
- **Reduces API calls**: Fewer issues fetched for time-based queries
- **Improves performance**: Less data to process in downstream nodes
- **User satisfaction**: Time-based workflows become trivial

## Alternative Approaches Considered

### 1. Client-side Filtering (Rejected)
- Fetch all issues and filter by date in Python
- ❌ Inefficient: Wastes API calls and bandwidth
- ❌ Limited: Still capped by limit parameter

### 2. Separate Node `github-list-recent-issues` (Rejected)
- Create dedicated node for date filtering
- ❌ Redundant: Duplicates 90% of existing code
- ❌ Confusing: Users need to choose between two similar nodes

### 3. Add `created_after` and `updated_after` (Rejected)
- Support both created and updated date filters
- ❌ Complex: Increases interface complexity
- ❌ YAGNI: Can add `updated_after` later if needed
- Note: Could extend with `filter_by: created|updated` in future

### 4. Use GitHub Search API Directly (Rejected)
- Make raw API calls instead of using `gh` CLI
- ❌ Dependencies: Would need Python GitHub library
- ❌ Auth complexity: Need to handle tokens directly
- ❌ Inconsistent: Breaks pattern with other GitHub nodes

## Implementation Checklist

- [ ] Update `ListIssuesNode.prep()` to extract `since` parameter
- [ ] Add `_normalize_date()` helper method
- [ ] Update `exec()` to build search query when `since` provided
- [ ] Add date-specific error handling in `exec_fallback()`
- [ ] Update docstring with new parameter documentation
- [ ] Write unit tests for date normalization
- [ ] Write unit tests for command building with dates
- [ ] Write integration test with real GitHub API
- [ ] Update node documentation
- [ ] Test backward compatibility
- [ ] Add usage examples to docs

## Timeline

- **Implementation**: 2-3 hours
- **Testing**: 1-2 hours
- **Documentation**: 30 minutes
- **Total**: ~4-5 hours

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| GitHub changes search syntax | High | Use standard format, add tests |
| Relative date parsing complexity | Medium | Start simple, extend based on usage |
| Time zone confusion | Low | Document UTC assumption |
| Breaking existing workflows | High | Extensive backward compat testing |

## Open Questions

1. Should we support `until` parameter as well?
   - Decision: No, YAGNI. Can add later if needed.

2. Should we support filtering by updated date?
   - Decision: No, start with created date only. Can add `filter_by` parameter later.

3. Should we handle time zones explicitly?
   - Decision: Use GitHub's default (UTC) and document it.

## Appendix: GitHub Search Syntax

GitHub's search query syntax for dates:
- `created:>YYYY-MM-DD` - Created after date
- `created:>=YYYY-MM-DD` - Created on or after date
- `created:YYYY-MM-DD..YYYY-MM-DD` - Created between dates
- `updated:>YYYY-MM-DD` - Updated after date

Combined with state:
- `created:>2025-08-20 is:open` - Open issues created after date
- `created:>2025-08-20 is:closed` - Closed issues created after date

Reference: https://docs.github.com/en/search-github/searching-on-github/searching-issues-and-pull-requests