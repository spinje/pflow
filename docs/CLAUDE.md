# pflow documentation guidelines

## Audience and verification

These Mintlify docs are for people who install/configure pflow and want to understand workflows their agents build. Setup pages are procedures; reference pages explain what the agent-created workflow does. AI agents get their own usage instructions through `pflow guide` and MCP resources.

**Never document assumed behavior.** Verify commands and flags against `pflow --help`, the Click decorators in `src/pflow/cli/`, or tools in `src/pflow/mcp_server/tools/`. Test examples: every documented command must be runnable. Use `pflow guide` to check current agent usage. If something cannot be verified, ask the user or mark it as needing verification.

## Navigation and ownership

- `docs.json` owns page navigation, tabs, icons, and external links. Website/Blog links under `_disabled_anchors` and `_disabled_navbar_links` are not rendered.
- Put setup/configuration procedures in guides and integrations; implementation explanations belong in `how-it-works/` or `architecture/`. Do not document planner internals or IR schema here.
- Reference `examples/` for workflow patterns. Link to existing README/architecture explanations instead of duplicating them.

## Terminology

| Term | Use | Don't use |
|------|-----|-----------|
| workflow | A saved, reusable pipeline | flow, pipeline, script |
| node | A single operation in a workflow | step, task, action |
| run (verb) | Execute a workflow | execute, invoke |
| MCP server | External tool provider | MCP tool, MCP plugin |
| shared store | Data passed between nodes | context, state, memory |
| template variable | `${variable}` syntax | placeholder, parameter |

## Writing standards

Write in a direct, technical, second-person voice, as one developer explaining pflow to another. Explain the mechanism or rationale behind rules. Use concrete, verified errors and examples. Recommend the established pattern instead of presenting unnecessary menus, and skip definitions of familiar terms such as JSON, API, and stdin. Avoid marketing, corporate passive voice, repeated conclusions, and generic copy that could describe any product. Use natural sentence lengths; avoid dramatic fragments and long corporate compounds. Keep reference tables scannable, with explanatory voice in introductions, tips, and transitions.

**Banned words and phrases** — never use these:
- powerful, seamless, magic, revolutionary, game-changer, transformative, unlock, empower
- it's worth noting, interestingly, as you may know, let's dive in, at the end of the day, in conclusion
- delve, harness, leverage, utilize, illuminate, facilitate, bolster, streamline, navigate
- workflow orchestration, cognitive automation, composable (as marketing jargon)
- crucial, vital, essential (as standalone evaluations — fine if followed by mechanism)

### Formatting and structure

- Sentence case for headings; no emoji or decorative elements.
- Language tags on every code block (`bash`, `json`, etc.).
- Internal content links use paths such as `/quickstart`, not absolute URLs. External sidebar anchors and navbar links use full URLs.
- Lead with what something does and when it is useful; put the most common needs first.
- Use numbered steps for complex procedures, with prerequisites at the start and observable success criteria.

Every MDX page needs title and description frontmatter; icon is optional:

```yaml
---
title: "Clear, descriptive page title"
description: "Concise summary for SEO/navigation"
icon: "icon-name"
---
```

### Node reference pages

Use this order: what the node does and when it appears; parameters; output; node-specific behavior; runnable `.pflow.md` examples; security when relevant; common errors with their real messages. See `reference/nodes/code.mdx` and `reference/nodes/shell.mdx`.

## Mintlify and MDX gotchas

Follow component patterns in nearby MDX pages. Use Lucide icons, callouts sparingly, and accordions for supplementary detail rather than main features.

Literal pflow templates such as `${input}` belong in inline or fenced code. Bare templates in rendered prose become JavaScript expressions and can crash the page even when `mint validate` passes. When an example contains fenced blocks, give the outer fence more backticks than any nested fence that could close it (typically four around a three-backtick workflow example). `scripts/check_mdx_fences.py` and `tests/test_docs/test_mdx_fences.py` pin this boundary; ordinary JSX braces remain valid.

## Update policy

Update affected docs in the same PR as user-facing behavior changes: CLI flags in their reference page, new core nodes in the node reference, and changed behavior in its guides. Add a `<Warning>` callout for breaking changes.

### Changelog

`changelog.mdx` uses `<Update>` blocks, newest first. Keep `rss: true` in its frontmatter for the generated feed.

- Show main features directly as scannable bullet lists; use accordions for supplementary quick starts, limitations, or next steps.
- State what changed and what features do. Keep it factual; no taglines, marketing copy, or claims about why a feature is great.

Use these tags consistently:

| Tag | When to use |
|-----|-------------|
| `New releases` | Major version releases, new features |
| `Improvements` | Enhancements, performance, UX |
| `Bug fixes` | Bug fixes |
| `Breaking changes` | Changes that require user action |

### Roadmap

`docs/roadmap.mdx` is the public source of truth. Keep it concise, move items as priorities change, and express relative priority without time estimates.

## Local development

```bash
# Install Mintlify CLI
npm i -g mint

# Preview locally at http://localhost:3000
cd docs
mint dev

# Check for broken links
mint broken-links
```
