// A tiny context for canvas interactions that originate INSIDE a node (so node
// `data` stays callback-free / overlay-ready): row-level port focus (clicking one
// input/output row focuses that single port) and the container expand/collapse
// toggle (the GroupNode corner button — the card BODY selects; design D, 2026-06-10).
//
// HOVER is the one concept "mark a set of canvas subjects" (2026-06-11) — a PURE
// highlight (no focus change, no expansion, no camera move; user decision), with
// two producers: a panel CHIP marks its one resolved node (hoverNode), a canvas
// ROW marks every node its edges touch (hoverRow → GraphView derives the set via
// flow.ts rowTouches). The marked VALUE rides its own context so only the node
// components re-render on hover, not every Interaction consumer.

import { createContext, useContext } from "react";

export interface Interaction {
  focusPort: (portId: string) => void;
  toggleGroup: (groupId: string) => void;
  hoverNode: (flatId: string | null) => void;
  // A row identifies itself by its owner's flat id + its handle ids (an io row
  // carries both a receive and a feed handle — edges may land on either).
  hoverRow: (row: { nodeId: string; handles: readonly string[] } | null) => void;
}

const InteractionContext = createContext<Interaction>({
  focusPort: () => {},
  toggleGroup: () => {},
  hoverNode: () => {},
  hoverRow: () => {},
});

export const InteractionProvider = InteractionContext.Provider;

export function useInteraction(): Interaction {
  return useContext(InteractionContext);
}

export const NO_HOVER: ReadonlySet<string> = new Set();

// The hover MARKS — flat ids of everything the current hover touches. Disjoint
// id namespaces give one set two readers: NODE ids ring their box (hover-mark),
// EDGE ids light their line (the selected-edge halo + bright stroke, minus the
// elevation — hover is transient, tunneling relief stays a selection concern).
const HoverMarksContext = createContext<ReadonlySet<string>>(NO_HOVER);

export const HoverMarksProvider = HoverMarksContext.Provider;

export function useHoverMarks(): ReadonlySet<string> {
  return useContext(HoverMarksContext);
}
