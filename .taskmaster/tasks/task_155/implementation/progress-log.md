# Task 155 — Implementation Progress Log

Workflow Graph Model for Multi-Renderer Support. Living document — append as work proceeds.

> **Authoritative build guide:** `implementation/implementation-plan.md` (this folder). Spec:
> `task-155.md` (reconciled to the plan; plan §6 wins on deviations). ADRs: 0001/0003/0004.

---

## Implementation steps (from plan §7)

- [ ] **Phase 0 — parser/schema `_routes_to_end`** (`markdown_parser.py` both write-sites + `ir_schema.py` whitelist + tests; confirm committed `next: end` examples still validate). Small, LOW risk, separate commit. *Build depends on this field.*
- [ ] **Phase 1 — `graph/model.py`** (dataclasses + derived helpers `is_decision`/`is_terminal`/`shadowed`/`node`; assert `Node.parent`↔`Container.members` + edge-endpoint referential integrity).
- [ ] **Phase 2 — `graph/scope.py`** (move `refs_in`/`source_refs_in` *verbatim*; `resolve`/`for_level` are NOT here — reimplemented in build).
- [ ] **Phase 3 — `graph/build.py`** (the big one: two-sub-pass; expansion + recursion-stack cycle detection incl. `path is None`; the 4-path Scope→structural reimplementation; batch carry-all / leaf-as-data / dynamic-one-expansion; `unexpanded` + empty-IR guard; `_routes_to_end`→END node+edge; `shadowed`/`is_decision`/`is_terminal`). **Main structural test surface** `test_graph_build.py`.
- [ ] **Phase 4 — `graph/renderers/mermaid.py`** (`render_mermaid`; move pure utils; rewrite label builders to read dataclasses; flat-id + truncated-tail collapse + batch-fan + end-sink-parity + pair-dedup + suppression at render).
- [ ] **Phase 5 — compat shim** (`mermaid/__init__.py` re-exports only `generate_mermaid`; migrate `test_mermaid.py` helper imports/tests).
- [ ] **Phase 6 — remove old internals** (delete `_context/_edges/_io/_render/_scope.py`; update `mermaid/CLAUDE.md`; add `graph/CLAUDE.md`).
- [ ] **Phase 7 — throwaway react-flow completeness sketch** (6 patterns + 163 harness, no info loss; discard).
- [ ] **Post: doc reconciliation** (plan §12) — `task-155.md` ✅ done; `CONTEXT.md`/`core/CLAUDE.md`/`graph/CLAUDE.md` during phases.

**Agent handoff (N=3):** agent 1 = phases 0–3 (structural), agent 2 = phase 4 (renderer), agent 3 = phases 5–7. Firebreak at 3→4 (the two-layer split, locked by the frozen `GraphModel` + build suite).

---

## 2026-06-06 15:57 CEST — Planning complete, plan approved

Spent the session taking the task from "scoped spec" to a verified, review-hardened, approved implementation plan. **No code written yet** — Phase 0 is next.

**What happened:**
- Read spec + 3 braindumps + research findings + master session log + ADRs 0001/0003/0004 + CONTEXT.md.
- 6 `pflow-codebase-searcher` passes verified the model design against current code (findings F1–F14 in plan §2).
- **3 review rounds** (`/code-review` plan mode): round 1 (review-plan/simplicity/feature-interactions/impact-completeness), round 2 + round 3 (review-plan/feature-interactions/silent-failures). Final verdict: **risk LOW, design sound, ready** — every finding was a tractable plan edit, not a redesign.
- `/plan-breakdown` → N=3 agent split (in plan §12a).
- Reconciled `task-155.md` to the plan (6 surgical edits + 1 pointer note).
- Copied the approved plan to `implementation/implementation-plan.md`.

**Key decisions locked (rationale in plan §6):**
- 💡 Model is **leaner than the original spec sketch** — `shape`/`is_decision`/`is_terminal`/suppression are **derived views**, not stored; routing maps (`outgoing_routes` etc.) are **build scratch, not model fields**; dropped `Edge.via_coalesce` and the leaf `NodeId.batch_index`.
- 💡 **Identity** = `NodeId(node_id, ancestor_path)` with `batch_index` on each `AncestorStep`. Leaf batch items are `BatchSpec.items` *data*, not Nodes. Mirrors runtime identity (ADR-0003) so the future live-overlay join is lossless.
- 💡 **D1 (batch):** carry ALL literal items; the `…dots` ellipsis is render-only (fixed the blocking gap where `__dots` had edges but no identity).
- 💡 **D2 (`- next: end`):** modeled as an `EdgeKind.END` edge to a synthetic per-level END node, sourced from a NEW Phase 0 parser field `_routes_to_end`. Distinct edge kind so `is_decision`(BRANCH-only)/`is_terminal`(excludes END) stay correct. Mermaid ignores END edges (parity); React Flow consumes them.
- 💡 `descriptions` → `render_mermaid` (not build); source back-ref is a `(file,line)` pointer.

**The verifications that changed the plan (don't re-derive):**
- ❌ My initial assumption that cycle detection was global-visited → **wrong**; it's already a recursion-stack (port as-is; only fix the `path is None` gap via `synthesize_inline_workflow_id`).
- ❌ My initial D2 framing (BRANCH edge / Node flag) → **wrong on two counts**: `- next: end` is *discarded at parse time* (needs the parser change), AND a BRANCH-kind end edge would corrupt `is_decision`. Resolved via the parser field + distinct `EdgeKind.END`.
- ❌ "nearest-consumer-only" (spec wording) → **misnomer**; the code does pair-dedup (each distinct consumer, deduped per `(source,target)`).
- ✅ The runtime-overlay join (Substrate 2 / future JSONL trace, Task 133) is **compatible by design** (ADR-0003); the JSONL rework *strengthens* it. No model change; documented as pins in plan §6a.
- ✅ The 4-path Scope migration is **exhaustive** (no 5th); compat surface is exactly `generate_mermaid` + 6 test-only helpers.

**Top risks carried into implementation (plan §10):**
- ⚠️ **#1 — the 4-path Scope→structural reimplementation in `build.py`** (Phase 3). The bulk of the work; the highest-risk phase. Stays with one agent.
- ⚠️ The `handle-error → pflow_end` parity pin — the renderer MUST call `graph.is_terminal()` (END-excluding), not re-walk edges. Single most important D2 regression guard.
- ⚠️ Batch-output-fan reconstruction without the routing maps → add a multiple-outputs golden (no current golden pins it).

**Decided: no new ADR.** The one candidate (the runtime-inert `_routes_to_end` IR field) follows the existing `_source_*` parser-injected-field convention (which has no ADR) → document in `core/CLAUDE.md` + `graph/CLAUDE.md`, not an ADR.

**Next action:** Phase 0 — the `_routes_to_end` parser/schema change (separate commit).
