# Batch/loop CHIP RAIL — plan (2026-06-10, user-picked via 3-round shoot-lab)

> Design locked in `/tmp/batch-chip-lab/` rounds: **A3** (tinted capsule, icon + count) ·
> **B3** (dynamic batch shows `×N`; source in tooltip/read panel — user overrode the
> "fake number" concern, their call) · **C2** (loop chip, same vocabulary; batch sits
> right of loop) · **F1-square** (count INSIDE the expander: `[25 ⤢]`, rounded-SQUARE
> 7px — round = info chip, square = button; "nodes" word + ▸ chevron die).

## The design (what ships)

A **chip rail** straddling the TOP border, right-aligned, on leaves AND group cards
(both states — header-parity holds, nothing moves across the fold):

- LEAF:        `[↻] [⧉ ×25|×N]`                       (modifiers only)
- GROUP card:  `[↻] [⧉ ×N] [25 ⤢]`                    (modifiers + merged expander)
- Open region: same rail, expander glyph swaps to arrows-in (GLYPH_COLLAPSE), count stays.

Chips: 22px tall, tinted bg + colored border + colored mono text (the count-pill
language, upsized). Loop = amber round (↻ glyph, tooltip = polarity + condition + cap).
Batch = purple capsule (stack glyph + `×{count}` literal / `×N` dynamic; tooltip =
parallel|sequential + `over ${source_ref}` | "literal items"). Expander = the ONLY
square element (7px radius), carries `{memberCount}` + the existing A1 glyphs; keeps
class `.group-toggle` (test pins) + stopPropagation + dblclick behavior.

## Retired by this change

- The header **batch badge** (`Badges.tsx` batch arm + `.badge-batch` CSS) — was
  squeezing the 2-line description to uselessness AND duplicating the deck.
- The **category-line `↻` loop mark** (WorkflowNode + `.loop-mark` CSS) — supersedes
  this morning's decision; the chip is the mark now.
- The **looped sub-workflow tile-icon swap** (`iconFor`'s `workflow && loop → loop.svg`)
  — identity never mutates; behavior is additive (the chip). loop.svg stays (chip glyph
  is inline SVG; the asset may go unused — fine).
- The **count pill** (`▸ 25 nodes`) and the separate **corner toggle button** on groups
  — merged into the rail expander.

## Kept / adjacent

- The batch DECK (the at-rest silhouette) — chips quantify it, both stay.
- Loop-rule ROWS (advanced/focus-expanded) + LoopEdge U — untouched.
- unexpanded/warning badges (header) — untouched (status-ish, different family).
- IO card's `"14 inputs"` pill — keeps its text, inherits the restyled `.count-pill`
  chip language (height/typography) so the two border-pill species match.
- Read panel — already carries full batch/loop specs.
- RESERVED: the rail is the future live-overlay status-chip home (status joins
  leftmost, outranks modifiers).

## Mechanics / risks (verified against code)

- **`.node.detailed` has `overflow: hidden`** (compact was already re-set to visible
  for connector stubs) → a straddling rail would CLIP on advanced cards; the deck is
  silently clipped there today too. Fix: detailed goes `overflow: visible` (rows have
  transparent bg; the card bg owns the corners). Verify corners in browser; fallback =
  radius on the last row.
- **ELK ignorance is fine**: the rail extends 11px above the box, exactly like the old
  `.group-pill` (top −9) did. No leafSize/groupHeader change → zero layout drift.
- **Header `padding-right: 34px`** (was clearance for the inside-corner button) — no
  longer needed; remove, verify titles don't collide with the rail's lower half.
- `.group-toggle` becomes a rail member (static flex, not absolute); GraphView.test's
  `.group-toggle` click/stopPropagation pins stay valid unchanged.
- GroupNode's `NodeBadges` usage dies with the batch arm (an unexpanded host is never
  a group host — H8), so the import goes; WorkflowNode keeps NodeBadges (unexpanded).

## Files

- NEW `web/src/components/nodes/ChipRail.tsx` — rail + ModifierChips (loop/batch facts → chips).
- `WorkflowNode.tsx` — render rail; delete loop-mark span.
- `GroupNode.tsx` — render rail (hostNode chips + expander); delete count-pill +
  corner-button block + NodeBadges.
- `Badges.tsx` — drop the batch arm.
- `utils/icons.ts` — drop the loop swap in `iconFor`.
- `index.css` — `.chip-rail`/`.chip`/variants; restyle `.group-toggle` + `.count-pill`;
  delete `.loop-mark`/`.badge-batch`; detailed overflow; drop the 34px clearance.
- NEW `ChipRail.test.tsx` (jsdom) — literal `×3` / dynamic `×N` / tooltips / loop chip /
  absent-facts renders nothing.
- Docs: `web/CLAUDE.md` (chips bullet; amend loop-mark/icon-swap/count-pill mentions),
  `visualization-requirements.md` (Implemented), progress log.

## Gates

vitest + tsc strict + `npm run build`; real-browser screenshots (batched leaf advanced
+ beautiful, batched sub-workflow card both states, looped+batched worst case via
check-groups, io card pill parity); Python untouched (zero contract change).
