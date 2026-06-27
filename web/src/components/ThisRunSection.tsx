// The detail panel's "This run" section (Task 173) — ONE node's runtime record off its trace, fetched on
// demand from /api/run-node. The interactive single-node counterpart of `pflow report`: the realized input
// (post-`${...}`), the resolved output, status, time, cost, tokens, and the error — what the canvas badge
// and hover chip can't show. It owns its OWN fetch + catch (DR-6 posture): a failed fetch shows a small
// "couldn't load", never throws or blanks the panel. Generic rendering — no per-node-type curation (the
// interactive surface shows the structure; `pflow report` curates the linear view). Reuses the panel's
// existing `.panel-section` / `.facts` / `.read-param` idioms, so it adds no CSS.

import { useEffect, useState } from "react";

import { fetchRunNode } from "../api/client";
import { refKey } from "../graph/flow";
import { CodeBlock } from "./CodeBlock";
import { StatusBadge, fmtCost, fmtDuration } from "./nodes/StatusBadge";
import type { NodeStatus, RFRef, RunNodeDetail } from "../types";

export function ThisRunSection({
  workflow,
  runId,
  nodeRef,
}: {
  workflow: string;
  runId: string | null;
  nodeRef: RFRef;
}): JSX.Element {
  const [detail, setDetail] = useState<RunNodeDetail | null>(null);
  const [phase, setPhase] = useState<"loading" | "loaded" | "error">("loading");

  // Keyed on the STRUCTURAL ref-key (not the nodeRef object — its identity varies per render): a different
  // node, a run switch, or a loop's next iteration remounts/refetches the latest record.
  useEffect(() => {
    let cancelled = false;
    setPhase("loading");
    setDetail(null);
    fetchRunNode(workflow, runId, nodeRef)
      .then((d) => {
        if (!cancelled) {
          setDetail(d);
          setPhase("loaded");
        }
      })
      .catch(() => {
        if (!cancelled) setPhase("error");
      });
    return () => {
      cancelled = true;
    };
  }, [workflow, runId, refKey(nodeRef)]);

  // The panel's MOST distinct section: a bordered, elevated card (not the near-invisible <details> it
  // replaced). `aria-label` names the section (the visible "This run" summary is gone). The loading/error
  // states share the card so it never blanks the panel (DR-6).
  return (
    <section className="this-run" aria-label="This run">
      {phase === "loading" && <p className="read-panel-purpose">Loading run detail…</p>}
      {phase === "error" && <p className="read-panel-purpose">Couldn't load run detail.</p>}
      {phase === "loaded" && detail && <RunDetailBody detail={detail} />}
    </section>
  );
}

function RunDetailBody({ detail }: { detail: RunNodeDetail }): JSX.Element {
  // The header mirrors the panel's top (PanelHeader): the run-status badge IN the tile (vs a node icon),
  // "status" over the status value, and the duration (+ cost) where the description sits. `type` is dropped
  // — it's already the panel's top header. The status word stays white; the badge + glyph carry the color.
  const subtitle = [
    fmtDuration(detail.duration_ms),
    detail.cost_usd != null && detail.cost_usd > 0 ? fmtCost(detail.cost_usd) : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const inputEntries = Object.entries(detail.input);
  return (
    <>
      <header className="this-run-head">
        {/* the tile borders in the run-status color (the shared palette) — like the node tile's kind border */}
        <span className={`this-run-tile status-${detail.status}`}>
          <StatusBadge status={detail.status as NodeStatus} inline />
        </span>
        <div className="this-run-headtext">
          <span className="read-panel-kind">status</span>
          <span className="this-run-status">{detail.status}</span>
          {subtitle && <span className="this-run-sub">{subtitle}</span>}
        </div>
      </header>

      {detail.tokens && (
        <p className="this-run-tokens">
          {`${detail.tokens.input.toLocaleString()} in / ${detail.tokens.output.toLocaleString()} out`}
        </p>
      )}

      {detail.error && (
        <section className="read-panel-params">
          <h3>Error</h3>
          <CodeBlock code={detail.error} lang="text" />
        </section>
      )}

      {inputEntries.length > 0 && (
        <section className="read-panel-params">
          <h3>Input</h3>
          {inputEntries.map(([name, value]) => (
            <RunField name={name} value={value} key={name} />
          ))}
        </section>
      )}

      {detail.output != null && (
        <section className="read-panel-params">
          <h3>Output</h3>
          <RunOutput output={detail.output} />
        </section>
      )}
    </>
  );
}

// One named payload value — a string renders as plain text, anything else as JSON; both in the panel's
// scroll-capped `.read-param-value` <pre> (no truncation — large values scroll).
function RunField({ name, value }: { name: string; value: unknown }): JSX.Element {
  const isString = typeof value === "string";
  return (
    <div className="read-param">
      <div className="read-param-head">
        <span className="read-param-name">{name}</span>
      </div>
      <CodeBlock code={isString ? value : JSON.stringify(value, null, 2)} lang={isString ? "text" : "json"} />
    </div>
  );
}

function RunOutput({ output }: { output: Record<string, unknown> | string }): JSX.Element {
  if (typeof output === "string") {
    return <CodeBlock code={output} lang="text" />;
  }
  if (!Array.isArray(output)) {
    return (
      <>
        {Object.entries(output).map(([name, value]) => (
          <RunField name={name} value={value} key={name} />
        ))}
      </>
    );
  }
  return <CodeBlock code={JSON.stringify(output, null, 2)} lang="json" />;
}
