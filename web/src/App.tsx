// Routing-free shell (v1 has two views: catalog + one graph). The `pflow ui`
// command opens the browser to `/?workflow=<name|path>` (ui/CLAUDE.md), so the
// initial view is driven by the URL query param; React Router is deferred until a
// real third view exists.

import { useCallback, useEffect, useState } from "react";

import { CatalogView } from "./views/CatalogView";
import { GraphView } from "./views/GraphView";

function workflowFromUrl(): string | null {
  return new URLSearchParams(window.location.search).get("workflow");
}

export function App(): JSX.Element {
  const [workflow, setWorkflow] = useState<string | null>(() => workflowFromUrl());

  const open = useCallback((wf: string) => {
    const url = new URL(window.location.href);
    url.searchParams.set("workflow", wf);
    window.history.pushState({}, "", url);
    setWorkflow(wf);
  }, []);

  const back = useCallback(() => {
    const url = new URL(window.location.href);
    url.searchParams.delete("workflow");
    window.history.pushState({}, "", url);
    setWorkflow(null);
  }, []);

  useEffect(() => {
    const onPop = (): void => setWorkflow(workflowFromUrl());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  if (workflow) {
    return <GraphView key={workflow} workflow={workflow} onBack={back} />;
  }
  return <CatalogView onOpen={open} />;
}
