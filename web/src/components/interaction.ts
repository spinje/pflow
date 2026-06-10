// A tiny context for canvas interactions that originate INSIDE a node (so node
// `data` stays callback-free / overlay-ready): row-level port focus (clicking one
// input/output row focuses that single port) and the container expand/collapse
// toggle (the GroupNode corner button — the card BODY selects; design D, 2026-06-10).

import { createContext, useContext } from "react";

export interface Interaction {
  focusPort: (portId: string) => void;
  toggleGroup: (groupId: string) => void;
}

const InteractionContext = createContext<Interaction>({ focusPort: () => {}, toggleGroup: () => {} });

export const InteractionProvider = InteractionContext.Provider;

export function useInteraction(): Interaction {
  return useContext(InteractionContext);
}
