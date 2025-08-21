"""Alternative context formatting options for discovery."""


def format_option_1_current():
    """Current improved format with markdown headers."""
    return """
### 1. `generate-changelog`
Generate changelog from GitHub issues and create PR for release updates.

**Capabilities:**
- GitHub integration
- Issue fetching
- Changelog generation
- Pull request creation

**Keywords:** `changelog github issues release`

**Use Cases:**
- Release preparation
- Version updates
"""


def format_option_2_compact():
    """More compact format with inline metadata."""
    return """
**1. `generate-changelog`** - Generate changelog from GitHub issues and create PR
- **Does:** GitHub integration, Issue fetching, Changelog generation, PR creation
- **Keywords:** changelog, github, issues, release, version
- **For:** Release preparation, Version updates
"""


def format_option_3_structured():
    """Structured format with clear sections."""
    return """
## 1. `generate-changelog`
> Generate changelog from GitHub issues and create PR for release updates

**What it does:** GitHub integration • Issue fetching • Changelog generation • PR creation
**Search terms:** changelog, github, issues, release, version
**Best for:** Release preparation, Version updates
"""


def format_option_4_table_like():
    """Table-like format for easy scanning."""
    return """
`generate-changelog`
├─ Description: Generate changelog from GitHub issues and create PR
├─ Capabilities: GitHub, Issues, Changelog, Pull requests
├─ Keywords: changelog github issues release version
└─ Use cases: Release prep, Version updates
"""


def format_option_5_minimal():
    """Minimal format focusing on essentials."""
    return """
`generate-changelog`: Generate changelog from GitHub issues
  → Can: fetch issues, generate changelog, create PR
  → Tags: changelog github issues release
  → For: releases, versions
"""


# My recommendation: Option 2 (compact) or Option 3 (structured)
# Both are readable and provide all needed info without being too verbose
