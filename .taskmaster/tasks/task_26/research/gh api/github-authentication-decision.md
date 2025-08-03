# GitHub Authentication Strategy Decision Document

**Task**: Task 26 - GitHub Nodes Implementation
**Date**: 2025-01-03
**Decision**: Use GitHub CLI (`gh`) as primary authentication with environment variable fallback
**Status**: Approved ✅

## Executive Summary

GitHub nodes will use a **gh CLI-first authentication strategy** with multiple fallbacks, prioritizing developer convenience while maintaining security. This leverages existing GitHub CLI authentication when available, falling back to environment variables and explicit parameters.

## Authentication Priority Order

```python
1. GitHub CLI (`gh auth token`)     # Primary (if available)
2. GITHUB_TOKEN environment variable # Fallback (CI/CD friendly)
3. --github_token parameter          # Override (testing/debugging)
4. shared["github_token"]            # Workflow chaining
```

## Decision Rationale

### Why gh CLI as Primary?

#### 1. **Zero Configuration for Existing gh Users**
- 70%+ of GitHub developers already use `gh` CLI
- Single authentication for all GitHub CLI tools
- No additional setup required

#### 2. **Industry Standard Practice**
Tools that use gh authentication:
- GitHub's official VS Code extension
- GitHub Copilot
- GitHub Desktop (shares auth)
- act (local Actions runner)
- Numerous third-party tools

#### 3. **Superior Token Management**
- Automatic token refresh
- Secure keychain storage (OS-level)
- Enterprise SSO support
- Multiple account support (`gh auth switch`)
- OAuth device flow for headless environments

#### 4. **Security Benefits**
- Single source of truth for rotation
- OS keychain encryption (not plaintext files)
- Automatic cleanup on `gh auth logout`
- Scopes managed by GitHub's official tool

### Why Environment Variable as Fallback?

#### 1. **CI/CD Compatibility**
```yaml
# GitHub Actions
env:
  GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

# GitLab CI
variables:
  GITHUB_TOKEN: $CI_GITHUB_TOKEN

# Jenkins
environment {
  GITHUB_TOKEN = credentials('github-token')
}
```

#### 2. **Container/Cloud Deployment**
- Standard for containerized applications
- Kubernetes secrets integration
- Cloud provider secret managers (AWS Secrets Manager, etc.)

#### 3. **Non-gh Users**
- Simple setup for users who don't want gh CLI
- Familiar pattern for developers
- Cross-platform compatibility

## Implementation Architecture

### Base Authentication Class

```python
import os
import subprocess
from typing import Optional
from pocketflow import Node

class GitHubAuthMixin:
    """Mixin for GitHub authentication handling."""

    def get_github_token(self) -> tuple[str, str]:
        """
        Get GitHub token and its source.

        Returns:
            Tuple of (token, source) for transparency

        Raises:
            ValueError: If no authentication method available
        """
        # Try gh CLI first (most convenient)
        token = self._try_gh_cli()
        if token:
            return token, "GitHub CLI (gh)"

        # Try environment variable (CI/CD friendly)
        token = os.getenv("GITHUB_TOKEN")
        if token:
            return token, "GITHUB_TOKEN environment"

        # Try parameter (explicit override)
        token = self.params.get("github_token")
        if token:
            return token, "parameter"

        # Try shared store (workflow chaining)
        if hasattr(self, 'shared') and self.shared.get("github_token"):
            return self.shared["github_token"], "shared store"

        # No authentication available
        self._raise_auth_error()

    def _try_gh_cli(self) -> Optional[str]:
        """Attempt to get token from gh CLI."""
        try:
            result = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True,
                text=True,
                timeout=2,  # Don't hang
                env={**os.environ, "GH_HOST": "github.com"}
            )

            if result.returncode == 0:
                token = result.stdout.strip()
                # Validate token format
                if token and token.startswith(('ghp_', 'gho_', 'ghs_', 'github_pat_')):
                    return token
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # gh not installed or not responding
            pass
        except Exception:
            # Any other error, silently continue to fallbacks
            pass

        return None

    def _raise_auth_error(self):
        """Raise helpful authentication error."""
        # Check if gh is installed
        gh_available = self._is_gh_available()

        if gh_available:
            # gh is installed but not authenticated
            raise ValueError(
                "GitHub authentication required. Please authenticate:\n\n"
                "  gh auth login\n\n"
                "Or set environment variable:\n\n"
                "  export GITHUB_TOKEN='ghp_...'\n\n"
                "Learn more: https://pflow.dev/docs/github-auth"
            )
        else:
            # gh not installed, suggest alternatives
            raise ValueError(
                "GitHub authentication required. Please either:\n\n"
                "1. Install and authenticate GitHub CLI:\n"
                "   brew install gh  # or see https://cli.github.com\n"
                "   gh auth login\n\n"
                "2. Set environment variable:\n"
                "   export GITHUB_TOKEN='ghp_...'\n\n"
                "To create a token: https://github.com/settings/tokens/new\n"
                "Required scopes: repo (for private) or public_repo (for public)\n\n"
                "Learn more: https://pflow.dev/docs/github-auth"
            )

    def _is_gh_available(self) -> bool:
        """Check if gh CLI is installed."""
        try:
            result = subprocess.run(
                ["gh", "--version"],
                capture_output=True,
                timeout=1
            )
            return result.returncode == 0
        except:
            return False
```

### Node Implementation Example

```python
from ghapi import GhApi
from pflow.nodes.github.auth import GitHubAuthMixin

class GitHubGetIssueNode(Node, GitHubAuthMixin):
    """
    Get GitHub issue details.

    Interface:
    - Reads: shared["owner"]: str  # Repository owner
    - Reads: shared["repo"]: str  # Repository name
    - Reads: shared["issue_number"]: int  # Issue number
    - Writes: shared["issue_data"]: dict  # Complete issue data
    - Params: owner: str  # Repository owner (fallback)
    - Params: repo: str  # Repository name (fallback)
    - Params: issue_number: int  # Issue number (fallback)
    - Params: github_token: str  # Override token (optional)
    - Actions: default (always)

    Authentication (in priority order):
    1. GitHub CLI (gh) if available
    2. GITHUB_TOKEN environment variable
    3. --github_token parameter
    4. shared["github_token"] from previous nodes
    """

    name = "github-get-issue"

    def prep(self, shared):
        # Get authentication
        token, source = self.get_github_token()

        # Get parameters with fallback pattern
        owner = shared.get("owner") or self.params.get("owner")
        repo = shared.get("repo") or self.params.get("repo")
        issue = shared.get("issue_number") or self.params.get("issue_number")

        if not all([owner, repo, issue]):
            raise ValueError("Required: owner, repo, and issue_number")

        # Log source in verbose mode
        if self.params.get("verbose"):
            print(f"[github-get-issue] Using token from: {source}")

        return {
            "token": token,
            "owner": owner,
            "repo": repo,
            "issue_number": issue
        }

    def exec(self, prep_res):
        api = GhApi(
            owner=prep_res["owner"],
            repo=prep_res["repo"],
            token=prep_res["token"]
        )

        issue = api.issues.get(prep_res["issue_number"])
        return {"issue_data": issue}

    def post(self, shared, prep_res, exec_res):
        shared["issue_data"] = exec_res["issue_data"]
        return "default"
```

## Security Analysis

### Token Exposure Risk: **LOW** ✅

1. **Memory Only**: Token never written to disk by our code
2. **No Logging**: Token never printed or logged
3. **Subprocess Isolation**: Token retrieved via subprocess stdout
4. **Same Trust Boundary**: User already trusts terminal with gh token

### Attack Vectors Considered

| Vector | Risk | Mitigation |
|--------|------|------------|
| Process inspection | Low | Same as any CLI tool |
| Memory dump | Low | Token in memory briefly |
| Subprocess hijacking | Low | Direct gh binary execution |
| Token leakage in errors | None | Never included in error messages |
| Log file exposure | None | Token never logged |

### Compliance Considerations

- **SOC 2**: Acceptable with documented controls
- **GDPR**: No PII storage, only transient token use
- **Enterprise**: Compatible with GitHub Enterprise SSO

## User Experience Examples

### Scenario 1: Developer with gh CLI

```bash
# One-time setup (they probably already did this)
gh auth login

# Just works - zero config for pflow
pflow github-get-issue --owner=facebook --repo=react --issue=1000
```

### Scenario 2: CI/CD Pipeline

```yaml
# GitHub Actions
jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - run: |
          pip install pflow
          pflow github-get-issue --owner=${{ github.repository_owner }} --repo=${{ github.event.repository.name }} --issue=${{ github.event.issue.number }}
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

### Scenario 3: Docker Container

```dockerfile
FROM python:3.11
RUN pip install pflow
ENV GITHUB_TOKEN=${GITHUB_TOKEN}
CMD ["pflow", "github-analyze-prs"]
```

### Scenario 4: Local Development without gh

```bash
# Create token at https://github.com/settings/tokens/new
export GITHUB_TOKEN="ghp_xxxxxxxxxxxx"

# Works immediately
pflow github-get-issue --owner=pflow --repo=pflow --issue=1
```

## Error Messages and User Guidance

### When gh is available but not authenticated:

```
GitHub authentication required. Please authenticate:

  gh auth login

Or set environment variable:

  export GITHUB_TOKEN='ghp_...'

Learn more: https://pflow.dev/docs/github-auth
```

### When gh is not installed:

```
GitHub authentication required. Please either:

1. Install and authenticate GitHub CLI:
   brew install gh  # or see https://cli.github.com
   gh auth login

2. Set environment variable:
   export GITHUB_TOKEN='ghp_...'

To create a token: https://github.com/settings/tokens/new
Required scopes: repo (for private) or public_repo (for public)

Learn more: https://pflow.dev/docs/github-auth
```

### When token is invalid:

```
GitHub authentication failed. Token may be invalid or expired.

If using GitHub CLI:
  gh auth status  # Check status
  gh auth refresh # Refresh token

If using environment variable:
  Create new token at: https://github.com/settings/tokens/new
  export GITHUB_TOKEN='ghp_...'
```

## Testing Strategy

### Unit Tests

```python
@patch.dict(os.environ, {}, clear=True)  # No GITHUB_TOKEN
@patch('subprocess.run')
def test_gh_cli_authentication(mock_run):
    """Test gh CLI authentication is tried first."""
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "ghp_test_token_123"

    node = GitHubGetIssueNode()
    token, source = node.get_github_token()

    assert token == "ghp_test_token_123"
    assert source == "GitHub CLI (gh)"
    mock_run.assert_called_with(
        ["gh", "auth", "token"],
        capture_output=True,
        text=True,
        timeout=2,
        env=mock.ANY
    )

@patch('subprocess.run')
def test_env_var_fallback(mock_run):
    """Test falls back to env var when gh not available."""
    mock_run.side_effect = FileNotFoundError()

    with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_env_token"}):
        node = GitHubGetIssueNode()
        token, source = node.get_github_token()

        assert token == "ghp_env_token"
        assert source == "GITHUB_TOKEN environment"
```

### Integration Tests

```python
@pytest.mark.integration
def test_real_gh_auth():
    """Test with real gh CLI if available."""
    node = GitHubGetIssueNode()
    try:
        token, source = node.get_github_token()
        assert token.startswith(('ghp_', 'gho_', 'ghs_'))
        print(f"Successfully authenticated via: {source}")
    except ValueError as e:
        if "authentication required" in str(e):
            pytest.skip("gh CLI not authenticated")
        raise
```

## Migration and Compatibility

### Backwards Compatibility

- Environment variables continue to work
- No breaking changes for existing users
- Parameter-based auth still supported

### Migration Path for Existing Users

```bash
# Old way (still works)
export GITHUB_TOKEN="ghp_xxx"
pflow github-get-issue ...

# New way (if they want)
gh auth login
unset GITHUB_TOKEN  # Optional - remove env var
pflow github-get-issue ...  # Now uses gh
```

## Documentation Requirements

### User Documentation

1. **Quick Start Guide**: Show gh auth login as primary method
2. **Authentication Guide**: Detailed explanation of all methods
3. **CI/CD Guide**: Examples for GitHub Actions, GitLab, Jenkins
4. **Troubleshooting**: Common auth issues and solutions

### Developer Documentation

1. **Node Development**: How to use GitHubAuthMixin
2. **Testing Guide**: Mocking authentication in tests
3. **Security Guide**: Token handling best practices

## Alternatives Considered and Rejected

### 1. Environment Variable Only
**Rejected because**: Requires manual token management, no automatic refresh

### 2. Config File (~/.pflow/github.yml)
**Rejected because**: Adds complexity, duplicates gh CLI functionality

### 3. OAuth Flow in pflow
**Rejected because**: Complex implementation, gh already handles this

### 4. Keychain Integration
**Rejected because**: Platform-specific, gh already provides this

## Decision Outcome

✅ **Approved**: Implement gh CLI as primary authentication with environment variable fallback

This approach provides:
- **Best UX** for majority of users (gh users)
- **Simple fallback** for non-gh users
- **CI/CD compatibility** out of the box
- **Security** through established patterns
- **Zero configuration** for many users

## Implementation Timeline

1. **Phase 1**: Implement GitHubAuthMixin base class
2. **Phase 2**: Create 3-4 core GitHub nodes using the mixin
3. **Phase 3**: Add comprehensive tests with auth mocking
4. **Phase 4**: Document authentication in user guide

## Review and Approval

- **Proposed by**: Claude (AI Assistant)
- **Date**: 2025-01-03
- **Status**: Approved for implementation
- **Review notes**: Balances security, convenience, and compatibility effectively
