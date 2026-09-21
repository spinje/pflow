# Graph transform (`web/src/graph/`)

Pure `RFGraph` → React Flow structure and layout. `flow.ts` is the consumer facade; siblings
follow `scan → io → rows → focus/flow`, with rows/focus importing flow types only to avoid a
runtime cycle. Python contract/rendering boundaries are in `src/pflow/ui/CLAUDE.md`.

## Navigation

- Construction and representative endpoints → `flow.ts:buildFlow`, internal `renderAnchor`.
- Leaf rows/sizing/ELK row ports → `rows.ts:paramRowsFor`, `outputRowsFor`, `nodeRows`,
  `leafSize`, `rowAnchorsFor`; handle landings → internal `flow.ts:sourceHandleFor/targetHandleFor`.
- Read/type presentation → `scan.ts:scanParamReads`, `consumedReadPaths`, `producedTypeOf`.
- IO ownership/ports and batch shells → `io.ts:ioOwners`, `wrapperPorts`, `shellBatchIds`.
- Parallel edge lanes → `flow.ts:assignEdgeLanes`; post-layout rails →
  `portSides.ts:assignDataRails`, `assignBackRails`, `assignLoopRails`.
- Layout/fork order → `layout.ts:layoutGraph`, `orderForkSiblings`; postprocessing →
  `spine.ts:alignSpine`, `layout.ts:compactScopes`.
- Focus/expansion/hover/status/replay → `focus.ts:applyFocus`, `expandTargets`, `rowTouches`,
  `applyStatus`, `applyReplayDim`.
- Opening policy → `direction.ts:autoDirection`, `collapse.ts:initialCollapsed`;
  search reveal → `collapse.ts:revealNodes`; reload identity →
  `remap.ts:remapSelection`, `remapCollapsed`.
- Handle IDs/types → `handles.ts:handleType`; shared CSS geometry → `metrics.ts`;
  source-pane coloring → `sourceDecorate.ts`.

## Rows and read presentation

`nodeRows` is the common model for rendering, sizing, ELK ports, and edge handles. Add a row
kind here and in WorkflowNode's render branch together; do not derive independent row lists.
Hidden rows must fall back to existing node handles. Cache dependencies have explicit chunk
rows, not a normal `prompt_cache` parameter row; losing those landings merges bindings into
the control trunk.

`scanParamReads` recovers sub-key reads lost through backend edge deduplication (`output_path`
is excluded from Edge equality). It corrects read/quiet/type presentation, never creates edges
or unsupported field rows. Keep its scope, batch-alias, and template-grammar filters aligned
with backend scope analysis; it scans params, not loop conditions. Backend owners are
`src/pflow/core/workflow/graph/model.py`, `src/pflow/core/workflow/graph/build.py`, and
`src/pflow/core/workflow/graph/scope.py`.

## Representative endpoints and IO

- `renderAnchor` maps hidden nodes and suppressed hosts to their on-canvas representative.
  A host may back multiple groups; do not assume a one-to-one host/group mapping.
- `shellBatchIds` is the shared suppression rule. Dynamic batches are shells; literal leaf
  batches without expanded child groups are shells too. Literal batches with expanded item
  groups retain their container. Memberlessness alone cannot distinguish these cases.
  Collapse policy and endpoint/deep-link resolution must reuse this rule.
- `wrapperPorts` supplies both canvas rows and IoPanel; `ioOwners` maps ports to rendered cards
  or workflow groups. Components must not re-derive either map.
- Synthesized `io-flow:` edges connect root IO to the control skeleton. Determine control sinks
  from forward control edges, not `is_terminal`: that Python fact also counts outgoing data-flow,
  so a final step feeding a declared output can be non-terminal. Cycles use the last-root-step
  fallback in buildFlow.
- Synthesized `loop:` edges need `assignLoopRails`; a self-loop's default midpoint runs through
  its own node. Backward branches/errors and parallel data bindings have separate lane/rail
  policies; `../components/edges/` consumes those hints rather than recomputing them.

## ELK constraints

- Leaf/collapsed-card ports align ELK with rendered handles. Expanded compound nodes must have
  no fixed ELK port: referenced compound ports crash elkjs under `INCLUDE_CHILDREN`.
- Cross-hierarchy edges also rule out `considerModelOrder.strategy`;
  `crossingMinimization.forceNodeModelOrder` is the supported ordering option here.
  Fork siblings follow branch-chain order, not workflow Steps order (`orderForkSiblings`).
- Expanded IO regions reserve sidebar/bottom space and minimum size. Under TD/DOWN, elkjs
  interprets `nodeSize.minimum` transposed: pass `(minH, minW)`; LR uses `(minW, minH)`.
- Missing compound ports cause center-anchored region trunks. `layoutGraph` must finish
  `alignSpine` then `compactScopes` before cache, camera anchoring, and animation see positions.
  Keep their collision/region guards; detailed algorithms and tuning values live in those functions.
- Worker startup/fallback and silent-worker watchdog → `layout.ts:loadElk`, `layoutWithWatchdog`.
  Preserve fallback/error handling rather than leaving an unresolved layout waiting forever.

## Decoration and identity

`applyFocus` restyles without layout. `expandTargets` is the beautiful-mode size policy that
feeds build/layout; advanced mode keeps a stable empty expansion set. Replacing that constant
with a fresh empty Set needlessly invalidates builds.

Flow edges retain original contract endpoints (`data.from`/`data.to`) even after re-anchoring
onto an IO owner, so port-specific focus can reveal only that port's connections. Group focus
selects the whole represented unit; hover uses the resolved flow rather than another contract walk.

`applyStatus` joins through structural refs. `applyReplayDim` is enabled for pinned terminal
replay (including paused/denied), not live runs. Expanded regions carry replay facts for edge
styling but must not apply container opacity over already-dimmed children. CSS ordering gives
focus dimming precedence (`web/src/cssOrder.test.ts`).

Flat IDs are positional. GraphView uses `remapSelection`/`remapCollapsed` before paint on each
replacement graph; only initial direction/collapse policy is frozen per workflow.

## Verification routes

- Handle existence/type and rendering contracts → `flow.test.ts`.
- Connectivity across collapse/suppression and committed real contracts → `lossless.test.ts`.
- ELK workarounds/postprocessing → `layout.test.ts`, `spine.test.ts` (compound-port integration
  also covered in `flow.test.ts`).
- Shared graph fixtures → `testFixtures.ts`; real payloads → `web/src/test/fixtures/contracts/`,
  drift-checked by `tests/test_core/test_react_flow_contract_fixtures.py`.
