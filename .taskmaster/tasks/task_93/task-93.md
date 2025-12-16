# Task 93: Set Up Mintlify Documentation

## ID
93

## Title
Set Up Mintlify Documentation

## Description
Configure Mintlify as the documentation platform for pflow's user-facing documentation. The docs will live in the `/docs` folder within the main repo (monorepo approach), enabling AI agents to update documentation atomically alongside code changes.

## Status
in progress

## Specification
See `starting-context/mintlify-docs-spec.md` for complete specification including:
- Documentation structure (~22 pages)
- Navigation configuration
- Content sources
- Depth guidelines
- What to include/exclude

## Dependencies
None - This is a standalone documentation infrastructure task.

## Priority
high

## Details
The current README.md is comprehensive but the `docs/` folder only has sparse placeholder files. We need professional, user-facing documentation using Mintlify as the platform.

### Key Decision: Same Repo (Monorepo) Approach
After evaluating tradeoffs, we chose to keep docs in the same repo because:
- AI agents can update docs atomically with code changes (single PR)
- Guaranteed version sync (docs always match code version)
- Simpler setup and maintenance for solo/small team
- Mintlify fully supports monorepo with `/docs` path configuration

### What Needs to Be Done

1. **Create minimal Mintlify structure in `/docs`**:
   - `docs.json` - Site configuration (navigation, theming, branding)
   - `index.mdx` - Homepage
   - Core documentation pages in `.mdx` format

2. **Configure Mintlify dashboard**:
   - Connect GitHub repo
   - Enable monorepo mode with `/docs` path
   - Set up auto-deployment on push

3. **Migrate/create content from existing sources**:
   - README.md sections → quickstart, why-pflow pages
   - `docs/getting-started.md` → getting-started.mdx
   - `docs/nodes.md` → nodes.mdx
   - `docs/mcp-server.md` → mcp-server.mdx

4. **Keep `architecture/` folder as-is** - that's internal AI agent documentation, not user-facing

### Technical Requirements
- Node.js v20.17.0+ for local preview (`mint dev`)
- Mintlify CLI: `npm i -g mint`
- MDX format for documentation pages

### Reference Materials Downloaded
Research folder contains:
- `llms-full.txt` (920 KB) - Complete Mintlify docs as AI context
- `llms.txt` (18 KB) - Structured index of Mintlify docs
- `starter-reference/` - Mintlify starter kit for inspiration (not to be modified)

> Important: Use subagents to gather information, context, do research and verifying assumptions from these documents while you work, do not read them yourself. Use subagents in PARALELL if you need to answer multiple questions at once. Use ONE function call block to deploy all subagents simultaneously.

### Mintlify Features to Leverage
- Automatic `llms.txt` and `llms-full.txt` generation for AI agents
- Git sync for automatic deployments
- Preview deployments for PRs
- MDX components (cards, tabs, callouts, etc.)

## Test Strategy
This is primarily a documentation/infrastructure task. Validation includes:

- **Local preview**: Run `mint dev` and verify pages render correctly
- **Navigation**: Ensure all pages are accessible via configured navigation
- **Links**: Verify internal and external links work
- **Deployment**: Confirm Mintlify dashboard shows successful deployment
- **Content accuracy**: Review that migrated content matches source intent
