// A tiny context for canvas interactions that originate INSIDE a node (so node
// `data` stays callback-free / overlay-ready). Today it's just row-level port
// focus — clicking one input/output row on a ports node focuses that single port.

import { createContext, useContext } from "react";

export interface Interaction {
  focusPort: (portId: string) => void;
}

const InteractionContext = createContext<Interaction>({ focusPort: () => {} });

export const InteractionProvider = InteractionContext.Provider;

export function useInteraction(): Interaction {
  return useContext(InteractionContext);
}
