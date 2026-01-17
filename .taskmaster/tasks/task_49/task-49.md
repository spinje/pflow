# Task 49: Prepare and Publish `pflow` to PyPI

## ID

49

## Title

Package and Publish pflow to PyPI with Trusted Publishers (GitHub Actions OIDC)

## Description

Package the existing pflow CLI for distribution on PyPI using modern Python packaging practices. This involves finalizing package metadata, setting up reproducible builds, configuring GitHub Actions for automated releases via OIDC Trusted Publishers, and establishing a clear release workflow. The codebase is mature and functional - this task focuses on packaging and distribution, not new development.

## Status
not started

## Dependencies

* **Task 83**: Security audit completed (no secrets/credentials in code or git history)
* PyPI/TestPyPI accounts with 2FA enabled
* GitHub repository with Actions enabled and ability to create tags/releases
* Decision on final package name (`pflow` vs `pflow-cli`)
* License decision (recommend MIT or Apache-2.0)

## Priority

high

## Details

### Current State Assessment

**What Already Exists:**
- ✅ Working CLI with Click framework (~3000+ lines)
- ✅ Mature codebase with 10+ commands (execute, validate, save, registry, mcp, etc.)
- ✅ Build system configured (hatchling)
- ✅ Entry point defined: `pflow = "pflow.cli:cli_main"`
- ✅ Dependencies declared (9 core packages: click, pydantic, llm, anthropic, mcp, etc.)
- ✅ Test suite with 3000+ tests
- ✅ Python 3.10+ support
- ✅ `src/pflow/` package layout
- ✅ Includes bundled `pocketflow` framework

**What Needs Work:**
- ❌ Package name decision (check PyPI availability)
- ❌ LICENSE file missing
- ❌ Version management strategy (currently hardcoded `0.0.1`)
- ❌ PyPI metadata incomplete (description, keywords, URLs)
- ❌ CHANGELOG.md doesn't exist
- ❌ Release automation not configured
- ❌ Installation documentation for end users

### Critical Pre-Flight Decisions

#### Decision 1: Package Name on PyPI

**Check availability first:**
```bash
# Check if 'pflow' is available
curl -s https://pypi.org/pypi/pflow/json | jq .info.name
# If 404: available
# If 200: taken
```

**Option A: Use `pflow` (preferred)**
- Simplest for users
- No import namespace confusion
- Requires name to be available on PyPI

**Option B: Use `pflow-cli`**
- Fallback if `pflow` is taken
- Distribution name: `pflow-cli`
- Import name stays: `pflow` (no code changes!)
- Console script stays: `pflow`
- Users install: `uv tool install pflow-cli`

**Decision:** [TO BE DETERMINED - check availability first]

#### Decision 2: License

**Current state:** No LICENSE file

**Recommendation:** MIT or Apache-2.0
- MIT: Simple, permissive, most popular
- Apache-2.0: Similar to MIT but with patent protection

**Required actions:**
1. Add LICENSE file to repo root
2. Update pyproject.toml: `license = {text = "MIT"}`  # or "Apache-2.0"
3. Add license classifier

#### Decision 3: Version Management

**Current:** Hardcoded `version = "0.0.1"`

**Option A: Keep manual versioning** (simpler)
```toml
[project]
version = "0.1.0"  # Update manually before each release
```

**Option B: Use hatch-vcs** (automated from git tags)
```toml
[project]
dynamic = ["version"]

[tool.hatch.version]
source = "vcs"
```

**Recommendation:** Start with Option A (manual), migrate to Option B later

### Implementation Checklist

#### Phase 1: Prepare Metadata

**1. Add LICENSE file**
```bash
# Choose license and add file
# Example for MIT:
curl -s https://opensource.org/licenses/MIT > LICENSE
# Edit to add your name and year
```

**2. Update pyproject.toml metadata**

Current minimal metadata needs expansion:

```toml
[project]
name = "pflow"  # or "pflow-cli" if pflow is taken
version = "0.1.0"
description = "Workflow compiler that transforms natural language into deterministic, executable workflows with AI-powered planning and MCP integration"
readme = {file = "README.md", content-type = "text/markdown"}
requires-python = ">=3.10,<4.0"
license = {text = "MIT"}  # or "Apache-2.0"
authors = [
    {name = "Andreas Falcone", email = "pflow-cli@gmail.com"}
]
keywords = ["workflow", "automation", "cli", "ai", "mcp", "llm"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",  # Update based on license choice
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Software Development :: Libraries :: Python Modules",
    "Topic :: System :: Shells",
    "Environment :: Console",
    "Typing :: Typed",
]

[project.urls]
Homepage = "https://github.com/spinje/pflow"
Repository = "https://github.com/spinje/pflow"
Documentation = "https://spinje.github.io/pflow/"
Issues = "https://github.com/spinje/pflow/issues"
Changelog = "https://github.com/spinje/pflow/blob/main/CHANGELOG.md"

# Keep all existing dependencies unchanged
dependencies = [
    "click",
    "jsonschema>=4.20.0",
    "llm>=0.27.1",
    "llm-anthropic==0.19",
    "anthropic>=0.40.0",
    "pydantic",
    "mcp[cli]>=1.17.0",
    "requests>=2.32.5",
    "claude-code-sdk>=0.0.21",
]
```

**3. Create CHANGELOG.md**

```markdown
# Changelog

All notable changes to pflow will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - YYYY-MM-DD

### Added
- Initial public release
- Natural language workflow planning with LLM
- 19 core nodes (file, git, github, http, llm, shell)
- 43 MCP server tools integration
- Workflow validation and execution
- Registry system for node discovery
- MCP server for AI agent integration
- Template variable system for data flow

[Unreleased]: https://github.com/spinje/pflow/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/spinje/pflow/releases/tag/v0.1.0
```

#### Phase 2: Build & Test Locally

**1. Clean build environment**
```bash
# Remove old build artifacts
rm -rf dist/ build/ *.egg-info/

# Create clean virtualenv
uv venv .venv-packaging
source .venv-packaging/bin/activate

# Install build tools
uv pip install build twine
```

**2. Build distributions**
```bash
# Build wheel and source distribution
python -m build

# Should create:
# dist/pflow-0.1.0-py3-none-any.whl
# dist/pflow-0.1.0.tar.gz
```

**3. Validate package**
```bash
# Check metadata and README rendering
twine check dist/*

# Should output: Checking dist/... PASSED
```

**4. Test installation locally**
```bash
# Create isolated test environment
uv venv .venv-test
source .venv-test/bin/activate

# Install from wheel
uv pip install dist/pflow-0.1.0-py3-none-any.whl

# Smoke test
pflow --version
pflow registry list
pflow --help

# Test import
python -c "import pflow; print(pflow.__version__)"

# Cleanup
deactivate
rm -rf .venv-test
```

#### Phase 3: Test on TestPyPI

**1. Register on TestPyPI**
- Create account at https://test.pypi.org/account/register/
- Enable 2FA
- Create API token (for manual testing only)

**2. Upload to TestPyPI (manual first time)**
```bash
# Upload
twine upload --repository testpypi dist/*

# Will prompt for credentials or use API token
```

**3. Test install from TestPyPI**
```bash
# New environment
uv venv .venv-testpypi
source .venv-testpypi/bin/activate

# Install from TestPyPI
# Note: --index-url for TestPyPI, --extra-index-url for dependencies from real PyPI
uv pip install --index-url https://test.pypi.org/simple/ \
               --extra-index-url https://pypi.org/simple/ \
               pflow==0.1.0

# Test it works
pflow --version
pflow --help

# Cleanup
deactivate
rm -rf .venv-testpypi
```

#### Phase 4: Set Up Trusted Publishers (OIDC)

**Why Trusted Publishers?**
- No API tokens/passwords in GitHub secrets
- More secure (OIDC authentication)
- Auditable releases
- PyPI best practice

**1. Configure TestPyPI Trusted Publisher**
1. Go to https://test.pypi.org/manage/account/publishing/
2. Add a new pending publisher:
   - PyPI Project Name: `pflow` (or `pflow-cli`)
   - Owner: `spinje`
   - Repository: `pflow`
   - Workflow: `publish.yml`
   - Environment: `testpypi` (optional but recommended)

**2. Configure PyPI Trusted Publisher**
1. Go to https://pypi.org/manage/account/publishing/
2. Same settings as above but with environment: `pypi`

**3. Create GitHub Actions workflow**

Create `.github/workflows/publish.yml`:

```yaml
name: Build and Publish to PyPI

on:
  push:
    tags:
      - 'v[0-9]+.[0-9]+.[0-9]+'          # v0.1.0, v1.2.3
      - 'v[0-9]+.[0-9]+.[0-9]+-rc.[0-9]+' # v0.1.0-rc.1

permissions:
  id-token: write   # Required for OIDC
  contents: read    # Required for checkout

jobs:
  build:
    name: Build distribution
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Full history for potential version derivation

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install build dependencies
        run: |
          python -m pip install --upgrade pip
          python -m pip install build twine

      - name: Build distribution
        run: python -m build

      - name: Check distribution
        run: twine check dist/*

      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: dist-packages
          path: dist/
          retention-days: 5

  publish-testpypi:
    name: Publish to TestPyPI
    needs: build
    runs-on: ubuntu-latest
    if: contains(github.ref, '-rc.')
    environment:
      name: testpypi
      url: https://test.pypi.org/project/pflow/
    permissions:
      id-token: write

    steps:
      - name: Download artifacts
        uses: actions/download-artifact@v4
        with:
          name: dist-packages
          path: dist/

      - name: Publish to TestPyPI
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          repository-url: https://test.pypi.org/legacy/

  publish-pypi:
    name: Publish to PyPI
    needs: build
    runs-on: ubuntu-latest
    if: "!contains(github.ref, '-rc.')"
    environment:
      name: pypi
      url: https://pypi.org/project/pflow/
    permissions:
      id-token: write

    steps:
      - name: Download artifacts
        uses: actions/download-artifact@v4
        with:
          name: dist-packages
          path: dist/

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
```

**4. Configure GitHub Environments**

In GitHub repo settings → Environments:

1. Create `testpypi` environment
   - Add protection rule: Require approval (optional)

2. Create `pypi` environment
   - Add protection rule: Require approval (recommended)

#### Phase 5: Release Process

**Standard Release Workflow:**

```bash
# 1. Ensure Task 83 (security audit) is complete
# 2. Ensure all tests pass
make test

# 3. Update version in pyproject.toml
# [project]
# version = "0.1.0"

# 4. Update CHANGELOG.md
# - Move items from [Unreleased] to [0.1.0]
# - Add release date

# 5. Commit version bump
git add pyproject.toml CHANGELOG.md
git commit -m "chore: bump version to 0.1.0"
git push

# 6. Create and push release candidate tag
git tag v0.1.0-rc.1
git push origin v0.1.0-rc.1

# GitHub Actions will:
# - Build distributions
# - Publish to TestPyPI
# - Available at: https://test.pypi.org/project/pflow/

# 7. Test RC from TestPyPI
uv venv .venv-rc-test
source .venv-rc-test/bin/activate
uv pip install --index-url https://test.pypi.org/simple/ \
               --extra-index-url https://pypi.org/simple/ \
               pflow==0.1.0rc1

# Run smoke tests
pflow --version
pflow registry list
# ... test critical functionality

# 8. If tests pass, create final release tag
git tag v0.1.0
git push origin v0.1.0

# GitHub Actions will:
# - Build distributions
# - Publish to PyPI
# - Available at: https://pypi.org/project/pflow/

# 9. Create GitHub Release
# Go to: https://github.com/spinje/pflow/releases/new
# - Tag: v0.1.0
# - Title: "pflow 0.1.0"
# - Description: Copy from CHANGELOG.md
# - Attach: dist/pflow-0.1.0.tar.gz and dist/pflow-0.1.0-py3-none-any.whl
```

#### Phase 6: Documentation

**Update README.md with installation instructions:**

```markdown
## Installation

### For End Users (Recommended)

Install using `uv` (fastest):

\`\`\`bash
# Install pflow CLI tool
uv tool install pflow

# Or if you prefer pipx:
pipx install pflow
\`\`\`

### For Development

\`\`\`bash
# Clone repository
git clone https://github.com/spinje/pflow.git
cd pflow

# Install in editable mode with dev dependencies
uv pip install -e ".[dev]"
\`\`\`

### Claude Desktop Configuration

To use pflow with Claude Desktop, add to your config:

\`\`\`json
{
  "mcpServers": {
    "pflow": {
      "command": "pflow",
      "args": ["mcp", "serve"]
    }
  }
}
\`\`\`

**Troubleshooting:** If Claude Desktop can't find `pflow`, use the full path:
\`\`\`bash
which pflow  # Find the path
\`\`\`
Then use that path in the config: `"command": "/Users/username/.local/bin/pflow"`
```

### Versioning Strategy

**Semantic Versioning (SemVer):**
- `0.y.z` = Pre-1.0 (breaking changes allowed in minor versions)
- `1.0.0` = First stable release (API stability commitment)
- `x.Y.z` = Minor version (new features, backwards compatible)
- `x.y.Z` = Patch version (bug fixes only)

**Version 0.1.0 Checklist:**
- [ ] All tests passing
- [ ] Security audit (Task 83) complete
- [ ] Documentation up to date
- [ ] LICENSE file added
- [ ] CHANGELOG.md created
- [ ] Package name decided
- [ ] PyPI accounts created
- [ ] Trusted Publishers configured
- [ ] Local build tested
- [ ] TestPyPI tested
- [ ] GitHub Actions workflow added

### Rollback & Emergency Procedures

**If a release has critical bugs:**

1. **Yank the release** (makes it uninstallable unless pinned):
   ```bash
   # On PyPI website or via API
   # This hides the version but keeps it accessible by exact pin
   ```

2. **Release hotfix version:**
   ```bash
   # Fix bug
   # Bump to 0.1.1
   # Follow release process
   git tag v0.1.1
   git push origin v0.1.1
   ```

3. **Communicate:**
   - Update GitHub release notes
   - Post notice if you have users
   - Update CHANGELOG.md with fix details

### Post-Release Checklist

After successful PyPI publish:

- [ ] Verify package installs: `uv tool install pflow`
- [ ] Check PyPI page renders correctly: https://pypi.org/project/pflow/
- [ ] Create GitHub release with notes
- [ ] Test Claude Desktop integration
- [ ] Update docs with actual PyPI links
- [ ] Announce release (if desired)

### Open Source Considerations

**Before making repository public:**

1. **Security Review (Task 83)**
   - No API keys in code
   - No secrets in git history
   - No sensitive URLs or internal infrastructure details

2. **Legal Review**
   - License file added
   - All dependencies have compatible licenses
   - No proprietary code included

3. **Documentation Quality**
   - README.md is complete
   - Installation instructions clear
   - Basic usage examples provided
   - Contributing guidelines (optional for MVP)

4. **Repository Cleanup**
   - Remove TODO comments with internal names
   - Remove references to internal systems
   - Ensure issue templates are generic

**Recommended Timeline:**

```
Week 1: Preparation
  - Complete Task 83 (security audit)
  - Make naming decisions
  - Add LICENSE file
  - Update pyproject.toml metadata
  - Create CHANGELOG.md

Week 2: Testing
  - Test builds locally
  - Test on TestPyPI
  - Set up Trusted Publishers
  - Configure GitHub Actions

Week 3: Release
  - Make GitHub repository public
  - Release v0.1.0 to PyPI
  - Create GitHub release
  - Update documentation
```

## Test Strategy

### Pre-Release Tests

1. **Build Tests**
   ```bash
   python -m build
   twine check dist/*
   ```
   - Verify: Clean build, no warnings
   - Verify: README renders on PyPI

2. **Installation Tests**
   - Fresh virtualenv install from wheel
   - Fresh virtualenv install from sdist
   - Test on macOS, Linux (Windows optional for MVP)

3. **Smoke Tests**
   ```bash
   pflow --version
   pflow --help
   pflow registry list
   pflow registry search llm
   python -c "import pflow; print(pflow.__version__)"
   ```

4. **Integration Tests**
   - Run existing test suite: `make test`
   - All 3000+ tests must pass

5. **TestPyPI Integration**
   - Install from TestPyPI with RC tag
   - Run full smoke test suite
   - Test MCP server integration

### Post-Release Validation

1. **PyPI Package**
   ```bash
   uv tool install pflow
   pflow --version
   ```

2. **Claude Desktop Integration**
   - Configure with `"command": "pflow"`
   - Test MCP tools are discoverable
   - Test basic workflow execution

3. **Documentation**
   - Verify PyPI page renders correctly
   - Check all links work
   - Verify installation instructions

## Success Criteria

- ✅ Package builds cleanly with no warnings
- ✅ Package installs on fresh system with `uv tool install pflow`
- ✅ All existing tests pass
- ✅ Package metadata complete and accurate
- ✅ README renders correctly on PyPI
- ✅ Trusted Publishers configured for automated releases
- ✅ GitHub Actions workflow successfully publishes to TestPyPI and PyPI
- ✅ MCP integration works for Claude Desktop users
- ✅ Installation documentation clear for end users

## Notes

### Key Differences from Original Task

This updated task reflects the actual state of the pflow codebase:
- Uses Click (not Typer)
- Preserves existing dependencies (not minimal set)
- Acknowledges mature codebase (3000+ LOC, not hello world)
- Focuses on packaging existing code (not creating new structure)
- Uses current entry point `pflow.cli:cli_main`
- Includes pocketflow bundling decision

### Future Enhancements (Post-0.1.0)

- Migrate to hatch-vcs for automated versioning
- Add pre-commit hooks for version consistency
- Set up dependabot for dependency updates
- Create comprehensive CONTRIBUTING.md
- Add issue/PR templates
- Set up branch protection rules
- Consider GitHub Releases automation
