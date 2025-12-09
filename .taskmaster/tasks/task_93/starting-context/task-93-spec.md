# Feature: setup_mintlify_docs

## Objective

Configure Mintlify documentation platform for pflow user-facing docs.

## Requirements

- Must create `docs/` folder with ~22 MDX pages in monorepo
- Must create `docs.json` with two-tab navigation structure
- Must create `docs/CLAUDE.md` with writing guidelines
- Must document core nodes only: file, llm, http, shell, claude-code, mcp
- Must use Mintlify MDX format with YAML frontmatter
- Must follow sentence case headings and second-person voice

## Scope

- Does not document planner internals (lives in `architecture/`)
- Does not document IR schema details (agents handle this)
- Does not document git, github, test, echo nodes
- Does not write for AI agent audience (they use `pflow instructions`)
- Does not create separate documentation repository
- Does not duplicate README or architecture content

## Inputs

- `existing_readme`: str — Current README.md content for migration
- `existing_docs`: list[str] — Current files in docs/ folder
- `mintlify_reference`: dict — Contains `starter_kit_path`, `llms_full_path`
- `codebase_research`: dict — Contains CLI structure, node interfaces, env vars

## Outputs

Returns: `docs/` folder containing:
- `docs.json` — Mintlify configuration with navigation, theme, branding
- `CLAUDE.md` — Writing guidelines for AI agents editing docs
- `index.mdx` — Homepage with value proposition
- `quickstart.mdx` — First workflow tutorial
- `installation.mdx` — pip install steps
- `guides/*.mdx` — 4 how-to guide pages
- `integrations/*.mdx` — 3 AI tool setup pages
- `reference/cli/*.mdx` — 5 CLI command reference pages
- `reference/nodes/*.mdx` — 7 node reference pages
- `reference/environment.mdx` — Environment variables reference

Side effects:
- Mintlify dashboard connection required post-creation
- Auto-deployment configured on push to main

## Structured Formats

```json
{
  "docs_structure": {
    "root_files": ["docs.json", "CLAUDE.md", "index.mdx", "quickstart.mdx", "installation.mdx", "favicon.svg"],
    "guides": ["using-pflow.mdx", "adding-mcp-servers.mdx", "configuration.mdx", "debugging.mdx"],
    "integrations": ["overview.mdx", "claude-desktop.mdx", "cursor.mdx"],
    "reference_cli": ["index.mdx", "workflows.mdx", "registry.mdx", "mcp.mdx", "settings.mdx"],
    "reference_nodes": ["index.mdx", "file.mdx", "llm.mdx", "http.mdx", "shell.mdx", "claude-code.mdx", "mcp.mdx"],
    "reference_other": ["environment.mdx"]
  },
  "frontmatter_schema": {
    "title": { "type": "string", "required": true },
    "description": { "type": "string", "required": true }
  },
  "docs_json_schema": {
    "tabs": ["Documentation", "Reference"],
    "theme": "string",
    "name": "pflow",
    "colors": { "primary": "string", "light": "string", "dark": "string" }
  }
}
```

## State/Flow Changes

- `empty` → `scaffolded` when folder structure created
- `scaffolded` → `content_ready` when all MDX files have content
- `content_ready` → `validated` when `mint dev` runs without errors
- `validated` → `deployed` when Mintlify dashboard connected and deployed

## Constraints

- Total page count: ~22 pages
- Node.js v20.17.0+ required for Mintlify CLI
- All MDX files must have `title` and `description` frontmatter
- All headings must use sentence case
- All code blocks must have language tags
- All internal links must use relative paths
- All CLI examples must be runnable
- Icons must be from Lucide library (lucide.dev)

## Rules

1. Create `docs.json` with `tabs` array containing "Documentation" and "Reference" tabs.
2. Create `docs/CLAUDE.md` containing terminology table, writing standards, component guide.
3. Create `index.mdx` with frontmatter containing `title` and `description`.
4. Create `quickstart.mdx` with step-by-step first workflow tutorial.
5. Create `installation.mdx` with `pip install pflow-cli` instructions.
6. Create `guides/using-pflow.mdx` documenting day-to-day CLI usage patterns.
7. Create `guides/adding-mcp-servers.mdx` documenting MCP server integration.
8. Create `guides/configuration.mdx` documenting API keys and settings.
9. Create `guides/debugging.mdx` documenting traces and troubleshooting.
10. Create `integrations/overview.mdx` explaining AI tool integration options.
11. Create `integrations/claude-desktop.mdx` with MCP config JSON snippet.
12. Create `integrations/cursor.mdx` with Cursor MCP setup instructions.
13. Create `reference/cli/index.mdx` with CLI command structure overview.
14. Create `reference/cli/workflows.mdx` documenting `pflow [request]` and `pflow workflow`.
15. Create `reference/cli/registry.mdx` documenting `pflow registry` subcommands.
16. Create `reference/cli/mcp.mdx` documenting `pflow mcp` subcommands.
17. Create `reference/cli/settings.mdx` documenting `pflow settings` subcommands.
18. Create `reference/nodes/index.mdx` with node system overview.
19. Create `reference/nodes/file.mdx` documenting read-file, write-file, copy-file, move-file, delete-file.
20. Create `reference/nodes/llm.mdx` documenting llm node parameters and usage.
21. Create `reference/nodes/http.mdx` documenting http node parameters and usage.
22. Create `reference/nodes/shell.mdx` documenting shell node parameters and usage.
23. Create `reference/nodes/claude-code.mdx` documenting claude-code node parameters and usage.
24. Create `reference/nodes/mcp.mdx` explaining MCP bridge node concept.
25. Create `reference/environment.mdx` listing all environment variables.
26. Use sentence case for all headings in all MDX files.
27. Use second-person voice in all prose content.
28. Include language tag on every code block.
29. Use relative paths for all internal links.
30. Verify all CLI examples are runnable before publishing.

## Edge Cases

- MDX file missing frontmatter → Page fails to render; must add frontmatter.
- Heading uses title case → Fails style validation; convert to sentence case.
- CLI example contains placeholder text → Fails verification; use real commands.
- Internal link uses absolute URL → Fails validation; convert to relative path.
- Content documents planner internals → Out of scope; link to `architecture/` instead.
- Content contains emoji → Fails style check; remove emoji.
- Code block missing language tag → Fails validation; add language tag.
- Node not in core list documented → Out of scope; remove or add note about `pflow registry list`.

## Error Handling

- `mint dev` fails → Check Node.js version ≥20.17.0, verify `docs.json` syntax.
- Broken internal link → Run `mint broken-links` to identify, fix path.
- Frontmatter parse error → Verify YAML syntax, check for special characters in title/description.
- Missing required file → Create file from template, add to navigation in `docs.json`.

## Non-Functional Criteria

- `mint dev` starts in <10 seconds on standard hardware
- All pages load in <2 seconds in local preview
- `mint broken-links` returns 0 broken links
- All 22 pages render without console errors

## Examples

### Valid docs.json structure

```json
{
  "$schema": "https://mintlify.com/schema/docs.json",
  "name": "pflow",
  "theme": "mint",
  "colors": {
    "primary": "#0D9373",
    "light": "#07C983",
    "dark": "#0D9373"
  },
  "favicon": "/favicon.svg",
  "navigation": {
    "tabs": [
      {
        "tab": "Documentation",
        "groups": [
          {
            "group": "Getting started",
            "pages": ["index", "quickstart", "installation"]
          }
        ]
      },
      {
        "tab": "Reference",
        "groups": [
          {
            "group": "CLI commands",
            "pages": ["reference/cli/index"]
          }
        ]
      }
    ]
  }
}
```

### Valid MDX frontmatter

```yaml
---
title: "Quickstart"
description: "Run your first pflow workflow in 2 minutes"
---
```

### Valid heading (sentence case)

```markdown
## Getting started
## Basic usage
## Common use cases
```

### Invalid heading (title case)

```markdown
## Getting Started
## Basic Usage
## Common Use Cases
```

## Test Criteria

1. `docs.json` exists and contains `tabs` array with exactly 2 entries.
2. `docs/CLAUDE.md` exists and contains "Terminology" section.
3. `index.mdx` exists with `title` and `description` in frontmatter.
4. `quickstart.mdx` exists with step-by-step instructions.
5. `installation.mdx` exists with `pip install pflow-cli` command.
6. `guides/using-pflow.mdx` exists with CLI usage content.
7. `guides/adding-mcp-servers.mdx` exists with MCP content.
8. `guides/configuration.mdx` exists with settings content.
9. `guides/debugging.mdx` exists with trace content.
10. `integrations/overview.mdx` exists with integration overview.
11. `integrations/claude-desktop.mdx` exists with MCP config JSON.
12. `integrations/cursor.mdx` exists with Cursor setup content.
13. `reference/cli/index.mdx` exists with CLI overview.
14. `reference/cli/workflows.mdx` documents `pflow workflow` commands.
15. `reference/cli/registry.mdx` documents `pflow registry` commands.
16. `reference/cli/mcp.mdx` documents `pflow mcp` commands.
17. `reference/cli/settings.mdx` documents `pflow settings` commands.
18. `reference/nodes/index.mdx` exists with node overview.
19. `reference/nodes/file.mdx` documents 5 file nodes.
20. `reference/nodes/llm.mdx` documents llm node.
21. `reference/nodes/http.mdx` documents http node.
22. `reference/nodes/shell.mdx` documents shell node.
23. `reference/nodes/claude-code.mdx` documents claude-code node.
24. `reference/nodes/mcp.mdx` explains MCP bridge concept.
25. `reference/environment.mdx` lists `ANTHROPIC_API_KEY`, `PFLOW_*` vars.
26. All MDX files use sentence case headings (no capital after first word except proper nouns).
27. All prose uses "you" not "users" or "the user".
28. All code blocks have language tag (bash, json, yaml, mdx, etc.).
29. All internal links use relative paths (no `https://`).
30. `pflow --version` command in installation.mdx is runnable.
31. No MDX file contains emoji characters.
32. `mint dev` runs without errors.
33. `mint broken-links` returns 0 broken links.
34. No MDX file documents git, github, test, or echo nodes.

## Notes (Why)

- Monorepo approach enables atomic doc+code updates in single PR
- Core nodes only keeps docs focused on base capabilities before MCP expansion
- Sentence case matches Mintlify conventions and improves readability
- Second-person voice creates direct, actionable documentation
- CLAUDE.md ensures AI agents follow consistent style when editing
- Two-tab navigation separates learning (Documentation) from lookup (Reference)

## Compliance Matrix

| Rule # | Covered By Test Criteria # |
|--------|---------------------------|
| 1 | 1 |
| 2 | 2 |
| 3 | 3 |
| 4 | 4 |
| 5 | 5 |
| 6 | 6 |
| 7 | 7 |
| 8 | 8 |
| 9 | 9 |
| 10 | 10 |
| 11 | 11 |
| 12 | 12 |
| 13 | 13 |
| 14 | 14 |
| 15 | 15 |
| 16 | 16 |
| 17 | 17 |
| 18 | 18 |
| 19 | 19 |
| 20 | 20 |
| 21 | 21 |
| 22 | 22 |
| 23 | 23 |
| 24 | 24 |
| 25 | 25 |
| 26 | 26 |
| 27 | 27 |
| 28 | 28 |
| 29 | 29 |
| 30 | 30, 32, 33 |

| Edge Case | Covered By Test Criteria # |
|-----------|---------------------------|
| Missing frontmatter | 3, 4, 5 (all verify frontmatter exists) |
| Title case heading | 26 |
| Placeholder CLI example | 30 |
| Absolute URL internal link | 29 |
| Planner internals documented | 34 (implicit via scope) |
| Emoji in content | 31 |
| Missing language tag | 28 |
| Non-core node documented | 34 |

## Versioning & Evolution

- **Version:** 1.0.0
- **Changelog:**
  - **1.0.0** — Initial specification for Mintlify documentation setup. Defines 22-page structure, writing guidelines, component usage, and validation criteria.

## Epistemic Appendix

### Assumptions & Unknowns

- Assumes Node.js v20.17.0+ available on development machine
- Assumes Mintlify dashboard account will be created separately
- Assumes `pflow-cli` package name for pip install (not yet published)
- Unknown: Exact Mintlify theme colors (using placeholder green values)
- Unknown: Logo/favicon assets (must be created separately)

### Conflicts & Resolutions

- README.md vs docs: README is marketing-focused; docs are usage-focused. Resolution: Migrate value prop to index.mdx, but rewrite for documentation style.
- docs/CLAUDE.md vs mintlify-docs-spec.md: CLAUDE.md is for AI agents editing docs; spec is for task implementation. Resolution: Both coexist with different purposes.

### Decision Log / Tradeoffs

- **Monorepo vs separate repo**: Chose monorepo for atomic updates and version sync. Tradeoff: Larger repo, but docs stay in sync with code.
- **Core nodes only**: Chose to document 6 node categories, skip git/github. Tradeoff: Less complete, but focused on universal capabilities.
- **22 pages vs minimal**: Chose comprehensive structure. Tradeoff: More work upfront, but better long-term maintainability.
- **Two tabs**: Chose Documentation + Reference split. Tradeoff: Slightly more navigation, but clearer mental model.

### Ripple Effects / Impact Map

- Affects: `docs/` folder (new)
- Affects: `.gitignore` (may need node_modules exclusion for mint CLI)
- Affects: `README.md` (may add link to docs site)
- Does not affect: `src/`, `tests/`, `architecture/`

### Residual Risks & Confidence

- Risk: Mintlify CLI version changes may break local preview. Mitigation: Pin version or document minimum version.
- Risk: Content may become stale as pflow evolves. Mitigation: Update policy in CLAUDE.md.
- Risk: ~22 pages is significant content creation effort. Mitigation: Can scaffold structure first, fill content incrementally.
- Confidence: High for structure and rules. Medium for exact content until written.

### Epistemic Audit (Checklist Answers)

1. **Assumptions not explicit**: Node.js version, Mintlify account, pip package name, logo assets.
2. **What breaks if wrong**: Wrong Node version → CLI fails. Wrong package name → install instructions fail.
3. **Elegance vs robustness**: Chose robustness (explicit 30 rules) over elegance (fewer, vaguer rules).
4. **Rule/Test mapping complete**: Yes, all 30 rules have corresponding tests; all 8 edge cases covered.
5. **Ripple effects**: Minimal—only affects docs/ folder, no code changes.
6. **Remaining uncertainty**: Medium confidence on content quality until written; high confidence on structure.
