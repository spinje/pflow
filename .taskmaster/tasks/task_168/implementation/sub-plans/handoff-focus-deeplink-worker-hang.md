# HANDOFF: `?focus=` deep-link freezes — ELK worker goes silent on the focus-expansion layout

> **Status (2026-06-10, ~13:10): CLOSED — defended, root cause environmental and never pinned.**
> A second investigation completed the evidence matrix (below) and the hang **stopped
> reproducing**: 13+ trials — current build, AND the exact commit (`a13d93ac`) where it
> reproduced "on demand" rebuilt in an isolated worktree, with and without CPU load — all
> apply focus correctly. What WAS established:
>
> - **The message is posted** (send-side `postMessage` wrap logged `SEND id=4`) and neither
>   `error` nor `messageerror` ever fires — so the silence is real, not a lost reply.
> - **The content is innocent, conclusively:** the live root carries zero non-finite values
>   and exactly matches its JSON capture; the captured sequence (register → probe → all 3
>   roots) terminates fine on the raw worker, on main-thread ELK, **and on the actual
>   Vite-built worker chunk** (driven in plain node — the one untested cell; the chunk is
>   esbuild-re-minified + `"use strict"`-wrapped, and it's fine).
> - The worker dispatcher (`saveDispatch`) posts a reply or an error for every dispatched
>   message — silence means the message never got processed or the computation never ended.
> - Every observation of the hang happened in the **long-lived, focus-stolen, often-occluded
>   MCP Chrome instance** (a tab per probe run, all same-origin, accumulated all day); after
>   that instance was restarted, no state on any build reproduces. Leading (unproven) theory:
>   environmental degradation of that Chrome instance, not a code path.
>
> **Defenses shipped (2026-06-10):** `layoutWithWatchdog` in `web/src/graph/layout.ts` — a
> worker layout that stays silent for 10s re-runs on the bundled main-thread ELK, the silent
> worker is terminated, and the session demotes to main-thread layouts (at most one 10s stall
> per session, never a dead canvas; pinned by 3 tests in `layout.test.ts`). Plus
> `Cache-Control: no-cache` on index.html (`_BundleFiles` in `ui/server.py`) — the stale-bundle
> trap that polluted observations — and the chrome-devtools MCP now runs `--headless=true`
> (no focus stealing, and removes the occlusion/interference class entirely).
> All `[dbg]` instrumentation is stripped. If the hang ever recurs, it now self-heals with a
> `console.warn` fingerprint ("ELK worker did not answer") — grep reports for that.
>
> The original investigation record follows, unchanged, for the next person.

## The symptom

`http://127.0.0.1:8765/?workflow=examples/agent-orchestration/plan-to-code/execute-plan/execute-plan.pflow.md&direction=LR&density=beautiful&focus=simplify`

opens with the read panel showing `simplify` (so the focus one-shot RAN and resolved) but the
CANVAS never reflects focus: no dim, no expansion, no reveal, no error banner, page otherwise
healthy. Real CLICKS on the same workflow work perfectly (probed: clicked card `expanded
focused`, 12 dimmed, condition row revealed). `conditional-branching`'s `?focus=` deep-link also
works. **Only the deep-link on execute-plan freezes — and it worked earlier the same day**
(11:15 screenshots), i.e. it regressed during the day's parallel work (suspect window includes
the IO-rows redesign + the condition/back-rail work; neither obviously touches the failing layer).

## What is PROVEN (each by measurement, not theory)

1. **The focus state is set.** Read panel opens; the one-shot (`GraphView.tsx` ~line 123)
   resolves `simplify` → `n21` and calls `setFocus`.
2. **The pipeline stalls at ELK, not before/after.** `[dbg]` trace on the live page:
   `layout start compact|LR|g1,g4,g7|g0,n21` → `elk.layout call 17 children` → **nothing**.
   No `done`, no `THREW`, no error banner (the `.catch` → banner path never fires), no console
   error. The decoration effect correctly skips (stale-paint guard: `laid.key !== layoutKey`)
   forever — that's the frozen canvas.
3. **The graph input is innocent.** The EXACT root (captured live via `globalThis.__roots`,
   saved at `/tmp/elk-roots.json`, 3 roots = the page's 3 layout calls; the hanging one is
   `[2]`) lays out fine:
   - on main-thread `elk.bundled.js` in node (replay script — see "Repro kit"),
   - in a REAL browser standalone Worker running the RAW `elkjs/lib/elk-worker.min.js`,
   - even as the same 3-root SEQUENCE through ONE standalone worker (replies 1,2,3 all ok).
   It is a flat 17-child, 79-edge root, no ports, no nesting, `structuredClone`-able (probed).
4. **In the app, the worker goes silent mid-protocol.** Raw `addEventListener("message"/"error")`
   on the app's worker (via `workerFactory`): replies `id=0` (register), `id=1` (startup probe),
   `id=2`, `id=3` (the two initial layouts) — then the focus layout is sent and there is
   **no reply and NO error event**. The worker either never received the message, is stuck in a
   non-terminating computation, or swallowed an error without posting a reply.
5. **elk-api has no `worker.onerror`** (`elkjs/lib/elk-api.js`, PromisedWorker): any unanswered
   message = promise pending forever. That's the hang mechanism (not the cause).
6. **Python/contract layer irrelevant**: `buildFlow`+`applyFocus`+`expandTargets` on the real
   `/api/graph` contract behave correctly in node (scratch test passed; the LR row-reveal works
   live on conditional-branching AND on execute-plan via real click).

## The remaining delta (where the cause must live)

The app's failing call differs from the passing standalone harness ONLY in:
- **the worker artifact**: app = Vite `?worker`-bundled chunk of `elk-worker.min.js`
  (`import("elkjs/lib/elk-worker.min.js?worker")` in `web/src/graph/layout.ts`);
  harness = the raw file served directly. Same source, different packaging.
- **transport timing**: app posts the focus layout ~1–2s after layout 2 completes (one-shot
  fires on `nodesInitialized`); harness posted back-to-back.
- **the send-side proxy**: elk-api's PromisedWorker wraps the Vite worker instance.

## Next experiments (in order — each ~10 min with the repro kit)

1. **Was the message even delivered?** Wrap `postMessage` on the worker instance in the
   `workerFactory` (`const orig = w.postMessage.bind(w); w.postMessage = (m) => { console.log("[dbg] SEND", m?.id ?? m?.cmd); orig(m); }`)
   → rebuild → run the repro. If SEND logs but no reply → in-worker problem. If no SEND →
   elk-api/send-side problem (look at PromisedWorker id bookkeeping).
2. **Is the worker stuck or dead?** After the hang, post one more tiny layout from the page
   (keep a handle to the worker in the factory: `(globalThis).__w = w`, then
   `__w.postMessage({id: 99, cmd: "layout", graph: {id:"t",children:[{id:"x",width:1,height:1}],edges:[]}, layoutOptions:{}, options:{}})`
   via evaluate_script). Reply to 99 → the focus message was LOST (transport). No reply → the
   worker is STUCK (non-terminating elkjs computation) — then diff the in-app root vs the
   captured `[2]` (stash at send time and compare; if identical, the Vite-bundled worker
   build is the variable: run the harness against the BUILT worker chunk from
   `src/pflow/ui/static/assets/elk-worker*` instead of the raw lib file).
3. **Bisect the regression window** if 1–2 stall: `git stash` the uncommitted tree and check
   whether the deep-link works at `cc11e683` (it should — it worked at 11:15). The uncommitted
   diff is large but the failing layer (layout.ts/hook) changed little: candidates are the
   IO-rows redesign (`g0` — the root IO CARD — is IN the failing expansion set: expansion
   `g0,n21`; the io card g0 is 260×420 expanded) and `expandTargets` owner-awareness. Note
   `conditional-branching` has NO IO at all — consistent with g0 involvement.

## Strong workaround (consider shipping regardless of root cause)

`layoutGraph` should never be able to hang the canvas: add a watchdog — if the worker layout
hasn't settled in ~10s, `console.warn` and re-run on the bundled main-thread ELK (the fallback
already exists in `loadElk`; the watchdog makes it reachable per-call). The captured root lays
out fine on the main thread, so this fully restores the user symptom even before the root cause
falls. (The error-banner `.catch` path already exists for rejections; the watchdog covers
silence.)

## Repro kit

- **Trigger URL** (above). Click path for comparison: open WITHOUT `&focus=` and click `simplify`.
- **Probe workflows** (in `/tmp`, may need re-creating from the progress log's session — all are
  ~30 lines): `probe-console.pflow.md` (console messages after settle), `probe-click.pflow.md`
  (dispatch click + dump state), `probe-root.pflow.md` (fetch `globalThis.__roots`),
  `probe-harness.pflow.md` (open a page + dump `#log`).
- **Captured roots:** `/tmp/elk-roots.json` (array of 3; `[2]` is the hanging one).
- **Main-thread replay:** `/tmp/elk-replay.mjs` — run from `web/` (`cp` it in, `node` it) → "OK".
- **Standalone worker harness:** recreate `src/pflow/ui/static/elk-test/` (gitignored, wiped by
  every `make ui-build`): copy `web/node_modules/elkjs/lib/elk-worker.min.js` + the roots, plus
  an `index.html` that `new Worker("./elk-worker.min.js")`, posts
  `{id:0,cmd:"register",algorithms:["layered"]}` then `{id:N,cmd:"layout",graph,layoutOptions:{},options:{}}`,
  and logs replies/onerror into `<pre id=log>`. Serve via the running `pflow ui` server.
- **MCP Chrome is SHARED with the other agent** — probe runs may fail with "browser is already
  running"; retry in a loop (`for i in 1..5; do … && break; sleep 15; done`).

## Cleanup required before any commit (instrumentation left in place to continue from)

All tagged `[dbg]`, console-only, harmless at runtime:
- `web/src/hooks/useWorkflowGraph.ts`: 3 logs — "layout start/landed", "decorate?".
- `web/src/graph/layout.ts`: "elk engine: worker", "elk.layout call/done/THREW" + try/catch
  wrapper around `elk.layout(root)`, the `globalThis.__roots` stash, and the raw
  `addEventListener` pair in `workerFactory`.
- `src/pflow/ui/static/elk-test/` (gitignored; vanishes on rebuild anyway).
- After stripping: `make ui-build` to get a clean bundle.

## Context for whoever picks this up

- This investigation rode on the condition-presentation session (edge-colored pills → LR row
  conditions → back rails → final-approach anchors → target-click reveal). ALL of that is DONE,
  tested (128 web tests), and verified live — including on execute-plan via real clicks. Only
  the `?focus=` deep-link on auto-collapsing/IO-bearing workflows is broken, and only through
  this worker silence.
- The screenshot/inspect tooling depends on `?focus=` (it cannot click), so this bug also
  blinds the agent tooling for focused states on big workflows — worth fixing soon.
- Progress log: `.taskmaster/tasks/task_168/implementation/progress-log.md` (the 2026-06-10
  entries narrate the day; this handoff supersedes its open-thread note on the deep-link).
