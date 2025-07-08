# pflow Knowledge Braindump for AI Agent

## Critical Context You Need to Know

### What pflow Really Is

pflow is a workflow compiler that transforms natural language into permanent, deterministic CLI commands. The killer feature is **"find or build"** - when you type `pflow "analyze costs"`, it either finds an existing workflow or builds one for you. This is fundamentally different from other workflow tools.

### The Real Value Proposition

1. **For Humans**: Never lose a script again. Your workflows are always one natural command away.
2. **For AI Agents**: Stop re-reasoning through repetitive tasks. Compile reasoning once, execute forever.
3. **The Hidden Gem**: Parameter handling - `pflow "analyze costs for last month"` uses the same workflow as `pflow "analyze costs for this week"`

### Core Technical Insights

#### Natural Language Planner is THE Feature
- Task 17 (after reorganization) is the heart of pflow
- Everything else exists to support this core innovation
- The planner includes workflow discovery - finding existing workflows by semantic meaning

#### Shared Store Pattern
- All node communication through `shared["key"]` pattern
- Natural, intuitive keys like `shared["url"]`, `shared["text"]`
- No complex parameter passing or glue code needed
- Proxy pattern (NodeAwareSharedStore) handles incompatible nodes transparently

#### PocketFlow Integration
- pflow uses a 100-line framework called pocketflow
- Only used where complex orchestration adds value (mainly in the planner)
- Most components use traditional Python patterns
- Don't over-engineer with pocketflow where simple functions work

### Current State of Implementation

1. **Infrastructure Complete** (Tasks 1, 2, 4, 5, 6, 11):
   - Package setup with CLI entry point
   - Basic CLI for argument collection
   - Node discovery and registry
   - IR schema and validation
   - File nodes (read, write, copy, move, delete)
   - IR-to-PocketFlow converter

2. **Not Yet Built** (the important parts):
   - Natural Language Planner (Task 17) - THE CORE FEATURE
   - Most platform nodes beyond file operations
   - Workflow discovery and storage
   - The "find or build" logic

### Documentation Structure

**Key Files You Should Know**:
- `docs/architecture/pflow-pocketflow-integration-guide.md` - CRITICAL patterns to avoid mistakes
- `docs/features/planner.md` - Natural language planning specs
- `docs/features/workflow-analysis.md` - Why pflow exists (the problem it solves)
- `docs/core-concepts/shared-store.md` - The communication pattern
- `.taskmaster/tasks/tasks.json` - Recently reorganized task list

**Recent Changes**:
- Tasks 17-20 merged into comprehensive Natural Language Planner task
- Task 13 expanded to include all platform nodes
- All v2.0 features consolidated into Task 32
- Dependencies simplified (Task 3 now only needs tasks 6 and 11)

### Architecture Decisions

1. **MVP Simplification**: Everything after 'pflow' is sent as natural language to the LLM. No direct CLI parsing in MVP.

2. **Simple Nodes Philosophy**: Each node does ONE thing well. Exception: general `llm` node to prevent prompt proliferation.

3. **Two-Tier AI**:
   - `claude-code` node: Comprehensive development with project context
   - `llm` node: Fast text processing without context

4. **Test-as-You-Go**: Every task includes its own test strategy. No separate testing phase.

### The Overthinking Problem

The developer (based on code analysis) has spent 6-8 weeks building perfect infrastructure but avoiding the core planner. There are 350+ tests for ~15% of features. Classic overthinking paralysis - building a fortress of tests around the easy parts while avoiding the core innovation.

### What Makes pflow Unique

1. **Semantic Command Space**: Invoke workflows by intent, not memorized names
2. **Find or Build Pattern**: One command either finds your workflow or creates it
3. **Workflow as Memory for AI**: AI agents can build their own toolkit over time
4. **Natural Interfaces**: Nodes use intuitive shared store keys, no configuration needed

### Common Pitfalls to Avoid

1. **Don't Parse CLI Directly**: In MVP, send everything to LLM as natural language
2. **Don't Over-Engineer**: Use simple functions where possible, pocketflow only for complex orchestration
3. **Don't Skip the Planner**: It's THE feature, not peripheral infrastructure
4. **Don't Forget Discovery**: Workflow discovery by semantic meaning is critical for "find or build"

### Current Momentum

The README was just updated to emphasize:
- "One command that finds your workflow or builds it for you"
- Parameter flexibility (same workflow, different inputs)
- AI agent efficiency (90% cost reduction for repetitive tasks)

The project is at a critical juncture - beautiful infrastructure built, but the core planner (the actual value) needs to be implemented.

### Key Questions Being Explored

1. **Market Viability**: Is pflow solving a real problem? (Yes - AI re-reasoning waste)
2. **Adoption Potential**: Realistic estimate 35-40% chance of success
3. **Unique Position**: No direct competitor combines all these features
4. **Primary Risk**: Category creation - educating market while building

### Your Mission

You're likely being asked to help with documentation or implementation. Key things to remember:

1. **The Planner is Everything**: Task 17 is the core. Everything else supports it.
2. **Workflow Discovery is Missing**: This enables "find or build" - must be added
3. **Keep It Simple**: MVP doesn't need perfection, it needs the core feature working
4. **Documentation Overlap**: Several docs cover similar ground and need consolidation

---

## Instructions for AI Agent

Please read and internalize this braindump. It contains critical context about:
- What pflow is and why it matters
- Current implementation state
- Recent reorganizations and decisions
- Key technical patterns and pitfalls
- The core value proposition

Once you've understood this context, acknowledge that you've read it and wait for further instructions. You'll likely be asked to help with documentation merging or implementation planning.

The most important thing to remember: **The Natural Language Planner is THE feature**. Everything else exists to support it.
