# Braindump: Task 121 — Workflow Testability

## Where I Am

Task 121 was created during a README direction planning session (Session 5). The task file is written and comprehensive. No implementation was started. This braindump captures the conversational context and tacit knowledge that shaped the task.

## How This Task Emerged

This was NOT a feature planning session. The user was working on README direction for pflow's GitHub launch. The chain:

1. User asked about "skills as living artifacts that agents build and update on demand"
2. I said it's important but for the README, show the mechanism, don't state the thesis
3. We documented the insight in PFLOW-CORE-INSIGHTS.md
4. User then asked: "do you think a lot of developers will say.. but I can't write tests for this so its useless?"
5. This revealed an anxiety about developer credibility — not a feature request
6. We explored what testing would look like architecturally
7. Confirmed no existing task covers this (searched taskmaster, read Task 76)
8. Created Task 121

**The user's real concern is README credibility, not test framework urgency.** They're preparing to launch pflow publicly and anticipating HN/Reddit objections. "Can I test this?" is a developer smell-test question. The task exists to close a conceptual gap and make testability a documented future direction, not because testing is the next implementation priority.

## User's Mental Model

**How the user thinks about testing in pflow's context:**
- Testing completes the "living skills" lifecycle. Without tests, "modify → re-publish" is reckless. User didn't say this explicitly but agreed when I articulated it.
- The user's first instinct was practical: "I think that is absolutely doable, dont you think?" — they see the architecture supporting it, they just hadn't formalized it.
- User pushed specifically on mocking: "but you almost always want to mock llm responses and often other things too?" — they know from experience that testing workflows without mocking is meaningless.
- User asked specifically about pytest integration: "would you build something custom here or use pytest integration for code node etc?" — they see a tension between pflow-native testing and leveraging existing Python tooling. This tension isn't fully resolved.

**Critical correction the user made about Task 76:**
I initially described Task 76 (`pflow registry run`) as "testing individual nodes in isolation." User pushed back: "isnt task 76 for an llm manually invoking it with data that it creates on the fly?" They see Task 76 as ad-hoc exploration, not testing. I then said "that's not testing at all" and user confirmed. Don't conflate Task 76 with testing in any future discussion — the user has a clear distinction in mind.

**Pattern: the user catches sloppy characterizations.** They asked "did you read the task file?" when I relied on an agent summary instead of reading Task 76 directly. They also pushed back on "If the format were opaque code, modification would be risky" — calling it out as not really true. Always verify claims before stating them to this user. They value precision over advocacy.

## Key Insights

**The three-angles-are-one-lifecycle insight (from earlier in the session, not in task file):**
Skills integration, the format, and building blocks are three layers of one lifecycle: create (building blocks) → validate → execute → save → publish as Skill → discover → modify → re-publish. Testing slots into this lifecycle as the safety mechanism between "modify" and "re-publish." This is why testability matters strategically, not just as a developer convenience.

**Mocking at the node level is the right abstraction.** We discussed mocking at the service level (HTTP, LLM API, MCP) vs the node level (intercept before exec()). Node-level won because: the node interface is already declared (you know mock shape), the wrapper chain provides a natural interception point, and it's service-agnostic (one mocking mechanism for all node types). This is in the task file but the reasoning journey isn't.

**Snapshot/record-replay solves the "what should my mock look like?" problem.** Users won't want to hand-craft LLM response mocks. Running once with real services and capturing the shared store state is the pragmatic answer. This was my suggestion, user didn't push back but didn't enthusiastically endorse either.

## Assumptions & Uncertainties

ASSUMPTION: The wrapper chain (InstrumentedWrapper → BatchWrapper → NamespacedWrapper → TemplateAwareWrapper → ActualNode) can be extended with a MockWrapper that short-circuits exec(). I reasoned from the architecture doc, haven't verified in code.

ASSUMPTION: The shared store captures enough information per node to serve as a snapshot fixture. Need to verify what `shared["node_id"]` actually contains after execution.

ASSUMPTION: A `## Tests` section in `.pflow.md` won't conflict with the markdown parser. The parser is a line-by-line state machine (~350 lines, `src/pflow/core/markdown_parser.py`). A new `## Tests` top-level section would need parser support. This is likely straightforward but is implementation work.

UNCLEAR: Priority of declarative mocks vs pytest integration. The task file says "declarative first, pytest as escape hatch" but the user specifically asked about pytest for code nodes. They might want pytest to be more first-class than I framed it.

UNCLEAR: Whether this task should be implemented before README launch or is just a documented future direction. The user's anxiety suggests they want to at least be able to say "testability is designed for and coming" in the README.

NEEDS VERIFICATION: That `pflow registry run` (Task 76) is actually named `run` in the current codebase, not `execute` as in the original task title. The architecture doc says `pflow registry run <node> params`. The task file says `pflow registry execute`. Check which is actually implemented.

## Unexplored Territory

UNEXPLORED: **Batch/parallel execution in tests.** pflow supports batch processing (process multiple items with same operation). If a workflow uses batch parallelism, mocking gets more complex — do you mock each batch item separately? Return an array? This wasn't discussed.

UNEXPLORED: **Testing error/failure paths.** Nodes have actions (e.g., `default`, `error`). Testing the error action path requires mocking a node to return an error action, not just mock data. The task file doesn't address this.

UNEXPLORED: **Nested workflow testing.** Workflows can call other workflows (`type: workflow`). When testing workflow A that calls workflow B, do you mock the entire sub-workflow? Mock individual nodes within it? This could get complex.

UNEXPLORED: **Test isolation for file/shell nodes.** Shell nodes have side effects. File nodes write to disk. Tests need isolation — temp directories, no real filesystem changes. This is standard but wasn't discussed.

CONSIDER: **Should tests be a separate file?** The task file says tests can live in `.pflow.md` OR in external files. But putting tests in the workflow file makes the file longer and the parser more complex. A companion `workflow.pflow-test.md` or `workflow.test.yaml` might be simpler to implement and maintain.

CONSIDER: **The `pflow test` command naming.** Is it `pflow test workflow.pflow.md` or `pflow workflow test workflow.pflow.md`? Fits better as a top-level command (like `pytest`) but pflow's CLI uses subcommand groups (`pflow workflow`, `pflow registry`).

MIGHT MATTER: **Test execution speed.** If non-mocked nodes include shell commands or file operations, test suites could be slow. Consider whether `pflow test` should default to mocking everything and requiring explicit opt-in to run real nodes.

MIGHT MATTER: **Assertion on intermediate nodes, not just final output.** The task file mentions this briefly ("execution traces capture per-node results") but it's a design question: can you assert on node 3's output even if it's not a declared workflow output? This would require accessing the shared store mid-workflow, which is possible but adds API surface.

## What I'd Tell Myself

1. This task emerged from README anxiety. Don't treat it as the next implementation priority unless the user says so. It's a conceptual gap that needed documenting.

2. The user values honesty about what exists vs what's planned. Don't let the task file's detailed design make it sound like this is partially built. It's entirely unbuilt.

3. The wrapper chain interception point is the key architectural bet. Before writing any implementation plan, read `src/pflow/runtime/` to verify the wrapper chain works as described in the architecture doc and that inserting a MockWrapper is actually feasible.

4. Start with the simplest possible version: `pflow test workflow.pflow.md` with inline mocks in YAML, basic equality assertions. No snapshot recording, no pytest integration. Get the feedback loop working first.

## Open Threads

- The README direction session (Session 5) is the parent context. Key decisions were made about posture (show don't sell) and structure (three angles are one lifecycle), but the core question "what does the reader see first?" is still unanswered. This is captured in the progress log at `projects/pflow/writing/readme/progress-log.md`.

- I asked the user "when someone asks what's pflow, what do you actually say?" and never got an answer. That question is still the most important one for the README.

- The "living skills" insight was documented in PFLOW-CORE-INSIGHTS.md during this session. It connects to testing (testing makes modify→re-publish safe). The next agent working on the README should read that section.

## Relevant Files & References

- **Task 121:** `/Users/andfal/projects/pflow/.taskmaster/tasks/task_121/task-121.md`
- **Task 76 (related, not overlapping):** `/Users/andfal/projects/pflow/.taskmaster/tasks/task_76/task-76.md`
- **Architecture doc (wrapper chain):** `/Users/andfal/projects/pflow/architecture/architecture.md` — lines 169-185
- **Markdown parser:** `src/pflow/core/markdown_parser.py` (~350 lines, state machine) — would need extension for `## Tests` section
- **Living skills insight:** `/Users/andfal/projects/mainframe/projects/pflow/documents/PFLOW-CORE-INSIGHTS.md` — "Skills as Living Artifacts" section
- **README progress log:** `/Users/andfal/projects/mainframe/projects/pflow/writing/readme/progress-log.md`
- **README synthesis (sessions 1-4):** `/Users/andfal/projects/mainframe/projects/pflow/writing/readme/braindumps/synthesis.md`

## For the Next Agent

If you're implementing Task 121: Start by reading the wrapper chain code in `src/pflow/runtime/`. Verify that inserting a MockWrapper before the actual node is feasible. That's the whole architectural bet. If it works, the rest is plumbing.

If you're continuing the README session: The testing task is a sidetrack. The main thread is README direction. Read the progress log, read the synthesis, and push the user to answer: "when someone asks what's pflow, what do you actually say?" That answer is the README's opening line.

> **Note to next agent**: Read this document fully before taking any action. When ready, confirm you've read and understood by summarizing the key points, then state you're ready to proceed.
