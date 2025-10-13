# Task 83: Pre-Release Security and Code Quality Audit

## ID
83

## Title
Pre-Release Security and Code Quality Audit

## Description
Conduct a comprehensive security audit and code cleanup before open sourcing pflow and publishing to PyPI. This includes scanning for accidentally committed secrets, removing sensitive information, and cleaning up embarrassing code/comments to ensure professional quality for public release.

## Status
not started

## Dependencies
None

## Priority
high

## Details
Before pflow can be safely open sourced on GitHub and published to PyPI, we must ensure the codebase contains no sensitive information and meets professional quality standards. This task involves two main areas:

### 1. Security Audit

**CRITICAL**: Scan the **ENTIRE** git history (all ~1200+ commits). Once the repository is open sourced, anyone can access every commit ever made. Even if secrets were removed in recent commits, they remain visible in git history forever.

Scan for:

- **API Keys and Tokens**: OpenAI keys (sk-), GitHub tokens (ghp_), AWS keys (AKIA), Anthropic keys, etc.
- **Credentials**: Passwords, database connection strings, authentication secrets
- **Infrastructure Details**: Internal URLs, server addresses, proprietary endpoints
- **Customer/User Data**: Any test data containing real user information
- **Environment Variables**: Check for hardcoded secrets that should be in .env

**Why Entire History Matters:**
```bash
# Once open sourced, ANYONE can do this:
git clone https://github.com/yourname/pflow
git log -p | grep "sk-"  # Find secrets from ANY commit
```

Old commits are permanent. A secret from commit #45 two years ago is still valid and exploitable.

**Audit Locations:**
- Current working files (all source code)
- **Complete git commit history** - ALL commits, not just recent ones
- Configuration files (pyproject.toml, .env.example, etc.)
- Test files and fixtures
- Documentation and example files

### 2. Code Quality Cleanup
Review and clean up:

- **Embarrassing Comments**: TODOs with personal notes, profanity, frustrated comments
- **Debug Code**: Leftover print statements, commented-out debug blocks
- **Incomplete Features**: Half-finished code that should be removed or completed
- **Poor Naming**: Variables like `foo`, `temp`, `asdf` that made it to main
- **Dead Code**: Unused functions, imports, or files
- **Documentation Quality**: Ensure all public APIs have proper docstrings

### Key Areas to Focus On

Based on the codebase structure:

1. **Planning System** (`src/pflow/planning/`) - May contain API keys in test prompts
2. **MCP Integration** (`src/pflow/mcp/`, `src/pflow/mcp_server/`) - Check for server URLs and tokens
3. **Node Implementations** (`src/pflow/nodes/`) - GitHub/Slack nodes may have test credentials
4. **Examples Directory** (`examples/`) - Often contains real API keys for testing
5. **Git History** - Previous commits may have exposed secrets

### Recommended Audit Approach

#### Phase 1: Automated Full History Scan (PRIMARY METHOD)

**Use gitleaks** - Optimized for scanning entire git histories efficiently:

```bash
# Install gitleaks
brew install gitleaks

# Scan ENTIRE git history (all ~1200+ commits)
# This takes ~30 seconds and finds secrets in any commit
gitleaks detect --verbose --report-path=.taskmaster/tasks/task_83/secrets-audit.json

# Review findings
cat .taskmaster/tasks/task_83/secrets-audit.json | jq '.'

# For each finding, check:
# - Which commit introduced it
# - Whether it's still valid (needs rotation)
# - How to remediate
```

**Alternative: truffleHog** (if gitleaks not available):
```bash
pip install truffleHog
truffleHog git file://. --json > .taskmaster/tasks/task_83/secrets-audit.json
```

#### Phase 2: Current Code Validation (QUICK CHECK)

```bash
# Verify current working directory is clean
grep -r "sk-\|ghp_\|AKIA" . --exclude-dir=.git --exclude-dir=.venv --exclude-dir=node_modules -i

# Check specific patterns
grep -r "api.*key\|secret\|token\|password" src/ examples/ -i | grep -v "\.md:" | head -20
```

#### Phase 3: Code Quality Checks (MANUAL)

```bash
# Find embarrassing comments
grep -r "TODO.*fuck\|shit\|damn\|stupid" . -i
grep -r "FIXME.*hack\|wtf\|asap" . -i

# Find debug code
grep -r "print(" src/pflow/ | grep -v "# debug" | grep -v "def print"
grep -r "console.log\|debugger" .

# Find poor naming
grep -r "def foo\|def bar\|def test_asdf\|variable.*temp.*=" . -i
```

#### Phase 4: High-Risk Areas Review (TARGETED)

Manually review these directories:
```bash
# Examples often have real credentials
ls -la examples/
git log -p -- examples/ | grep -E "sk-|ghp_|api.*key" -i

# Planning prompts may contain test API calls
git log -p -- src/pflow/planning/ | grep -E "sk-|token" -i

# Node implementations for external services
git log -p -- src/pflow/nodes/github/ src/pflow/nodes/git/ | grep "ghp_" -i
```

### Remediation Actions

If secrets are found:

1. **Remove from current code** - Replace with environment variable references
2. **Rotate compromised secrets** - If found in git history, assume compromised and rotate
3. **Update .gitignore** - Ensure patterns are ignored (*.env, credentials.json, etc.)
4. **Consider git history rewrite** - If critical secrets in history, may need git filter-branch/BFG Repo-Cleaner
5. **Document in .env.example** - Show what environment variables are needed

### Verification Steps

Before completing this task:

- [ ] **gitleaks scan completed on ENTIRE git history** (all ~1200+ commits)
- [ ] gitleaks report reviewed and all findings addressed
- [ ] Current working directory scanned with grep (zero findings)
- [ ] Test examples verified to use placeholder credentials (e.g., "sk-xxx", "ghp-placeholder")
- [ ] High-risk directories manually reviewed (examples/, planning/, nodes/)
- [ ] Documentation checked for sensitive info (URLs, server names, etc.)
- [ ] All embarrassing comments removed or improved
- [ ] Dead code removed
- [ ] README updated with environment variable requirements
- [ ] .env.example created with all required variables
- [ ] Any found secrets rotated/invalidated

## Test Strategy

This is primarily a manual audit task with some automated scanning:

### Automated Tests
- **PRIMARY**: Run gitleaks on entire git history (all commits)
  - Expected: Zero findings, or all findings documented as false positives
  - Save report to `.taskmaster/tasks/task_83/secrets-audit.json`
- **SECONDARY**: grep-based validation on current files
  - Expected: Zero matches for secret patterns
- **TERTIARY**: Verify all test files use mock credentials (no real API keys)

### Manual Review
- Review gitleaks report findings in detail
- Manually inspect high-risk directories: `examples/`, `src/pflow/planning/`, `src/pflow/nodes/`
- Spot-check random files for code quality
- Read through ALL files in examples/ directory
- Review all configuration files (pyproject.toml, .env.example, etc.)

### Verification Checklist
Before marking complete, save this checklist to `.taskmaster/tasks/task_83/audit-results.md`:

**Automated Scans:**
- [ ] gitleaks scan on ENTIRE git history: ✅ Zero findings (or all false positives documented)
- [ ] grep scan on current code: ✅ Zero secret patterns found
- [ ] Test files verified: ✅ All use placeholder credentials

**Manual Review:**
- [ ] examples/ directory: ✅ All files reviewed, no real credentials
- [ ] src/pflow/planning/: ✅ No API keys in prompts or tests
- [ ] src/pflow/nodes/: ✅ All external service nodes use env vars
- [ ] Documentation: ✅ No sensitive URLs or infrastructure details
- [ ] Configuration files: ✅ pyproject.toml, .env.example clean

**Code Quality:**
- [ ] Embarrassing comments removed: ✅ All profanity, frustration removed
- [ ] Debug code cleaned: ✅ No stray print() or console.log()
- [ ] Dead code removed: ✅ Unused functions/imports cleaned up

**Documentation:**
- [ ] .gitignore updated: ✅ All sensitive file patterns included
- [ ] .env.example created: ✅ All required env vars documented
- [ ] README updated: ✅ Environment setup instructions added

**Remediation (if secrets found):**
- [ ] Secrets rotated: ✅ All found secrets invalidated and rotated
- [ ] Git history cleaned: ✅ BFG/filter-branch if critical secrets in history

### Success Criteria
Task is complete when:
1. **gitleaks scan of ENTIRE git history shows zero findings** (or all false positives documented)
2. No secrets or sensitive information found in current code
3. All code meets professional quality standards (no embarrassing comments, debug code, or poor naming)
4. Documentation accurately reflects security requirements
5. `.taskmaster/tasks/task_83/audit-results.md` completed with all checkboxes ✅
6. Repository is safe to make public on GitHub
7. Another team member (or user) could safely review the code without finding anything embarrassing or insecure

**Final Validation:**
Before marking task complete, ask: "Would I be comfortable if this entire repository (including all git history) was published on Hacker News front page tomorrow?" If the answer is anything but an enthusiastic YES, the task is not complete.
