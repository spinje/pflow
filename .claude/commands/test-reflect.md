---
name: Test Reflect
description: Self-audit the tests you just wrote — deepen or delete. Run when the task orchestrator directs you to (phases whose tests were plausibly hard to write or easy to cheat).
---


before we call this done should we consider any HIGH VALUE tests that could catch actual bugs? we should NOT be optimizing for test coverage this is only if we can  identify something thats actually valuable. take a step back and think hard. now you got the whole picture.

If the current tests are shallow we need to either remove them or make them test what they are actually supposed to test if they should be testing something valuable. The bar isn't "passing" its "passing the right thing".

You just implemented a phase and its tests. Audit those tests AND related tests you have read against pflow's bar (root `CLAUDE.md` testing directives) before the work counts as done. The bar: **a test earns its place only if it would FAIL when the behavior it guards breaks.**

For EACH test you added or touched in this phase:

1. **Would it fail if the behavior broke?** Mutate mentally (or actually, briefly): flip the guard
   condition, break the invariant, return the wrong status, drop the key from the shared store —
   does this test catch it, or does it pass anyway (theater)?
   **When you run a mutation for real, the kill criterion is a COUNTED failure — `N failed` — never
   a non-zero exit code.** A run that collects no tests exits non-zero too (pytest returns 5 for
   "no tests collected"), so a filter that matches nothing reports a confident KILL for a run that
   executed nothing at all. Read the count, and check it against the tests you meant to run.
2. **Does it exercise the real path?** The real CLI/workflow surface over a hand-built internal
   call where the bug would live in the entry path (a directly-constructed node or store can mask
   exactly the layer under test). Fixtures shaped like real workflows crossing the same code path.
3. **Through the interface**, not implementation internals a refactor would legitimately change.
4. **Exact assertions where values are deterministic** — no bare truthiness where a value belongs;
   assert the discriminating value, not just "no exception".
5. **Archetype, not duplicate.** Test the archetype once; don't restate it across sibling node
   types, file-op nodes, or formatters — test only the differences. Don't test what mypy or the
   meta-tests already verify mechanically.
6. **Does an absence assertion prove anything?** "X must not appear" passes for FREE against an
   empty store, an errored run, output that was never produced, or a fixture that was never
   populated. Every "must not appear" needs a **presence assertion in the same medium** beside it,
   proving the medium was capable of showing X at all. Applies identically to CLI output, trace
   contents, API shapes, and a driven page's text — this is the purest form of a test that cannot
   fail.

Then act, don't report intentions:

- **DEEPEN** any test a real bug would slip past — add the failure-path case, sharpen the assertion.
- **DELETE** any test that cannot catch a real bug — coverage padding is debt, not armor.
- **Log which** (test name → deepened/deleted → why) in your progress-log entry's Self-checks line.

"Green" is not the claim; "green and discriminating" is.

Do you understand what Im after here and why passing the right thing is important?
