# Braindump: Task 107 - Markdown Workflow Format

## Where I Am

We just finished a deep exploration of workflow formats. Started by testing the generate-changelog workflow, then iterated on improvements (docs diff context, style reference, breaking changes accordion). The format friction during that work led to a fundamental discussion: should pflow use markdown instead of JSON?

By the end, the user and I were both convinced this is a significant improvement, not just an aesthetic preference. The user's exact words: *"it feels like going from a broken toy to something actually elegant and production ready"* — I pushed back on "broken toy" being too strong, but agreed the qualitative gap is real.

## User's Mental Model

**Key framing the user introduced:**
- "LLMs are the users, not humans" — This reframe changed everything
- Humans "accidentally" benefit from readability, but the format is FOR LLMs
- The JSON escaping problem is "almost unusable by humans" already, so we're not losing human-friendliness

**Their priorities (stated and unstated):**
1. LLM authoring quality — can LLMs generate correct workflows easily?
2. Lintability — especially with Task 104 (Python node) replacing jq
3. Token efficiency — 20-40% savings matters at scale
4. Documentation inline — "literate workflows"
5. Elegance — the user has taste and values clean design

**Terminology they use:**
- "LLMs are the users" (not "AI-friendly format")
- "Literate workflows" (borrowed from literate programming)
- "Lintable" (not "validated" or "checked")
- "Broken toy to production ready" (their framing of the improvement)

## Key Insights

**The reframe that unlocked everything:**
When I listed "users learn new format" as a cost, the user correctly pointed out: the users ARE LLMs, who prefer markdown. This inverted my cost/benefit analysis.

**JSON escaping is worse than I admitted:**
I successfully wrote JSON without syntax errors in this session. But I was being careful. And prompts were relatively simple. The cognitive load is real even when you don't make errors.

**The linting benefit compounds with Task 104:**
Current: shell nodes with jq one-liners (unlintable, cryptic)
Future: Python nodes with real code (lintable, readable)

This isn't just about markdown vs JSON — it's about the whole authoring experience shifting from "hacky scripts" to "real code."

**Documentation inline is bigger than I realized:**
The generate-changelog workflow has a separate README.md explaining design decisions. In markdown format, that explanation lives WITH the nodes. Single source of truth.

**The `purpose` field is a crippled version of what markdown enables:**
In JSON, each node has a `purpose` field — one line, terse, no formatting. Markdown replaces this with free-form prose that can:
- Explain WHY this approach was chosen (not just what it does)
- Include links to external docs
- Show example input/output
- Document edge cases and tradeoffs
- Use formatting (bold, lists, blockquotes)

The user noted this could go **inline with each node** OR **at the end of the file** OR both. Flexibility matters — some workflows need heavy documentation, others need minimal. The format should accommodate both.

Example of what becomes possible:
```markdown
## fetch
type: http
url: https://r.jina.ai/${target_url}

Uses [Jina Reader](https://r.jina.ai) for conversion.

> **Why Jina?** We tested Trafilatura, Readability, and direct fetching.
> Jina had the best quality for SPAs and paywalled content.

**Expected output:** Clean markdown with images as `![alt](url)` references.
```

This replaces: `"purpose": "Fetch markdown via Jina Reader"` — a massive expressiveness upgrade.

**"Novel = scary" doesn't apply:**
The user pointed out: if humans rarely touch the format, and when they do it's just markdown (which they know), there's no novelty cost. The format is familiar syntax with new semantics.

## Assumptions & Uncertainties

**ASSUMPTION:** Task 104 (Python node) will be implemented and will replace most jq usage. The markdown format's value increases significantly with Python nodes.

**ASSUMPTION:** LLMs will continue to be the primary workflow authors. If humans become primary authors, the calculus might change.

**UNCLEAR:** How to handle prompts that contain markdown syntax (code block examples). Mentioned using 4 backticks to wrap 3, but this could get ugly.

**UNCLEAR:** File extension. Options: `.md`, `.pflow.md`, `.pflow`. User didn't express preference.

**UNCLEAR:** Should documentation prose be preserved in the IR or discarded? It's useful for humans reading workflows but maybe not needed for execution.

**NEEDS VERIFICATION:** My claim that markdown is 20-40% more token-efficient needs actual measurement.

**NEEDS VERIFICATION:** That shellcheck/ruff actually work on extracted code blocks seamlessly in practice.

## How We Got Here

The conversation didn't start with "let's rethink the format." It started with improving the generate-changelog workflow (adding docs diff context, style reference). While implementing those improvements, the pain of editing prompts in JSON became apparent. The docs diff discussion surfaced a deeper question: why are we escaping everything?

This organic path matters — the markdown format isn't theoretical. It emerged from real friction while doing real work.

**The TypeScript → JavaScript analogy:**
I used this framing and it resonated. Markdown is the authoring format (source). IR is the execution format (compiled). You don't "maintain two formats" — you have one source of truth that compiles down.

**My initial resistance:**
I listed "users learn new format" and "novel = scary" as costs. The user correctly challenged this: LLMs are the users, and they already know markdown. My mental model was wrong. I was optimizing for hypothetical human editors instead of actual LLM authors. This reframe changed everything.

## Unexplored Territory

**UNEXPLORED:** When agents write workflows (via MCP tools or CLI), should they write markdown files directly? The current flow is agents using primitives (`registry discover`, `registry run`, `workflow save`) to iterate with users in chat. Markdown would be the format they write to disk.

**UNEXPLORED:** Migration path for existing JSON workflows. We said "no backwards compatibility needed" (MVP with zero users), but existing examples need conversion.

**UNEXPLORED:** VS Code extension. The user mentioned linting, but a proper `.pflow.md` extension with syntax highlighting, validation, and linting integration would be valuable.

**UNEXPLORED:** How does `pflow workflow save` change? Currently takes JSON file path. Would it accept markdown? Auto-detect by extension?

**UNEXPLORED:** The agent instructions (`pflow instructions create --part 1/2/3`) reference JSON format throughout. These would need updating to teach agents to write markdown.

**NOTE:** pflow is currently linear only - no parallel paths in the graph (Task 39 is future). So edges are always `[a, b, c, d]`. The "parallel" in batch nodes is data parallelism, not graph parallelism. This simplifies the edge syntax question for now.

**CONSIDER:** What if a node needs multiple code blocks of the same type? Two `shell` blocks?

**MIGHT MATTER:** Error recovery. If the markdown parser encounters malformed content, can it give useful errors? We said "markdown always parses" but semantic errors still need good messages.

**MIGHT MATTER:** Round-trip fidelity. If you convert JSON → markdown → IR → execution, do you get identical results? What about markdown → IR → JSON → markdown?

**MIGHT MATTER:** How do batch results work in markdown? The `${node.results[0].response}` syntax is already complex. Does it feel natural in markdown context?

## What I'd Tell Myself

1. **Start with Task 104 (Python node).** The markdown format's value is greatly amplified by having lintable Python instead of cryptic jq. These should be implemented together or in sequence.

2. **Don't overthink the parser.** Markdown libraries exist. Frontmatter extraction is solved. The hard part is good error messages, not parsing.

3. **Test with real workflows first.** Convert generate-changelog and webpage-to-markdown to the markdown format and try to execute them. Real examples reveal edge cases.

4. **The user has strong taste.** They care about elegance. A hacky implementation that "works" won't satisfy them. Take time to get the format right.

5. **Remember the core insight:** This isn't about humans. It's about LLMs. Every design decision should ask: "Is this easier for an LLM to generate correctly?"

## Open Threads

**The generate-changelog workflow was improved during this session:**
- Added `get-docs-diff` node (docs changes as context for refine-entries)
- Added `get-recent-updates` node (style reference for format-both)
- Updated prompts for breaking changes accordion
- Workflow is now 15 nodes, tested and working
- README updated

These changes are committed to `examples/real-workflows/generate-changelog/`. The user may want to commit them.

**We also generated a v1.0.0 changelog for pflow itself** during testing. Files updated:
- `CHANGELOG.md` — has new v1.0.0 section
- `docs/changelog.mdx` — has new Update block with Breaking changes accordion

The user should review these before committing, as they're test output.

**There's a stray directory** with a typo: `. taskmaster` (space before taskmaster). Created by accident. User needs to manually delete:
```bash
rm -rf ". taskmaster"
```

## Relevant Files & References

**Task file:** `.taskmaster/tasks/task_107/task-107.md` — Full spec with design decisions

**Example workflows discussed:**
- `examples/real-workflows/generate-changelog/workflow.json` — Updated with improvements
- `examples/real-workflows/generate-changelog/README.md` — Updated documentation
- `examples/real-workflows/webpage-to-markdown/workflow.json` — Used as comparison example

**Related tasks:**
- Task 104: Python Script Node — Critical dependency, enables lintable transforms
- Task 49: PyPI Release — Complete first before this

**Conversation artifacts:**
- Full markdown workflow example for webpage-to-markdown (in conversation, not saved to file)
- Token efficiency comparison table (in conversation)
- Format comparison tables (JSON vs YAML vs XML vs Markdown)

## For the Next Agent

**Start by:** Reading the task file at `.taskmaster/tasks/task_107/task-107.md`. It has the full design.

**Key context:** The user framed this as "LLMs are the users." Every decision flows from that. Don't optimize for human editing — optimize for LLM generation.

**Don't bother with:** Defending JSON. The decision is made. The question is how to implement markdown, not whether to.

**The user cares most about:**
1. Lintable code blocks (shell, Python)
2. Natural prompt editing (just text)
3. Token efficiency
4. The workflow being self-documenting

**Watch out for:**
- Task 104 (Python node) is a dependency — markdown format is less valuable without it
- Prompts containing markdown syntax (code block examples) need careful handling
- The user has high standards for elegance — hacky solutions won't satisfy

**Quick win to build confidence:** Convert one existing workflow (webpage-to-markdown is simpler) to the markdown format and show it executes correctly. Proves the concept.

---

**Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
