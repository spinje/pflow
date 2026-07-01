// The Run side-panel (Task 175): a `.read-panel`-shell form, launched from the
// Rail's ▶. It owns the form STATE (values / submitting / errors) and the launch
// FETCH; the reusable RunForm owns the field rendering. Its open/close lives in
// GraphView (a boolean OUTSIDE the `selectedId` selection model — like the
// RunSelector popover — so it never races the three selection panels).
//
// Launch = spawn a detached `pflow run` (server-side, ADR-0008). The server returns
// the spawned run's id; on success the parent PINS the overlay to that exact run via
// `onLaunched(runId)` (NOT follow-newest — pinning stops a shorter new run from
// reverting to an older still-live one). A spawn/pre-flight failure shows inline in
// the form and never blanks the canvas (DR-6 — each fetch owns its failure).

import { useCallback, useEffect, useMemo, useState } from "react";

import { PanelHeader } from "./PanelHeader";
import { RunForm } from "./RunForm";
import { runMark } from "./RunSelector";
import { ApiError, fetchRunInputs, fetchRuns, runWorkflow } from "../api/client";
import { inputFields, type InputField } from "../graph/flow";
import { IO_COLOR, timeAgo } from "../utils/format";
import { ioCardIcon } from "../utils/icons";
import type { ApiErrorEntry, RFGraph, RunInfo } from "../types";

// The token string a field PREFILLS with: its declared default, encoded the way the
// CLI's infer_type reads it back (channel A). A sensitive-named field stays blank —
// the form never holds a secret; the spawned run re-resolves it from settings/env.
function defaultToken(field: InputField): string {
  if (field.sensitive || field.defaultValue == null) return "";
  const d = field.defaultValue;
  if (typeof d === "string") return d;
  if (typeof d === "boolean" || typeof d === "number") return String(d);
  return JSON.stringify(d); // object / array → JSON text (the textarea control)
}

// The form's "Defaults" value map — every field at its declared default token (sensitive blank).
function defaultValues(inputs: InputField[]): Record<string, string> {
  return Object.fromEntries(inputs.map((f) => [f.name, defaultToken(f)]));
}

export function RunPanel({
  workflow,
  workflowName,
  graph,
  onLaunched,
  onClose,
}: {
  // The workflow key/path POSTed to /api/run (resolved server-side).
  workflow: string;
  workflowName: string;
  graph: RFGraph;
  // Called after a successful spawn with the spawned run's id — GraphView PINS the overlay to that exact
  // run (Task 175, so it doesn't follow-newest and revert to an older still-live run) + closes the panel.
  onLaunched: (runId: string) => void;
  onClose: () => void;
}): JSX.Element {
  const inputs = useMemo(() => inputFields(graph), [graph]);
  const [values, setValues] = useState<Record<string, string>>(() => defaultValues(inputs));
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<ApiErrorEntry[]>([]);
  // "load inputs from" picker (Phase 5): this workflow's past runs + the selected source ("defaults" or a
  // run id). Fetched once on open (a one-shot list of what to prefill FROM — not a live poll like the
  // RunSelector clock). Its own catch (DR-6): a runs-fetch failure shows just "Defaults".
  const [runs, setRuns] = useState<RunInfo[]>([]);
  const [source, setSource] = useState<string>("defaults");

  useEffect(() => {
    let cancelled = false;
    fetchRuns(workflow)
      .then((r) => !cancelled && setRuns(r))
      .catch(() => !cancelled && setRuns([]));
    return () => {
      cancelled = true;
    };
  }, [workflow]);

  const onChange = useCallback((name: string, value: string) => {
    setValues((prev) => ({ ...prev, [name]: value }));
  }, []);

  // Prefill the form from a source: "defaults" → the declared defaults; a run id → that run's recorded
  // inputs (server-redacted token strings). Each field takes the run's token if present, else blank — a
  // sensitive field (server-OMITTED → blank → re-resolves from settings/env) or a field added since that
  // run (blank → omitted → resolves at run time). The user can tweak before submitting.
  const loadFrom = useCallback(
    (src: string) => {
      setSource(src);
      setErrors([]);
      if (src === "defaults") {
        setValues(defaultValues(inputs));
        return;
      }
      fetchRunInputs(workflow, src)
        .then((tokens) => setValues(Object.fromEntries(inputs.map((f) => [f.name, tokens[f.name] ?? ""]))))
        .catch((err) =>
          setErrors(err instanceof ApiError ? err.errors : [{ message: "Could not load that run's inputs." }]),
        );
    },
    [inputs, workflow],
  );

  const onSubmit = useCallback(() => {
    // Omit blank fields so they resolve via the CLI's normal precedence (default →
    // env → settings) — faithful to a hand-typed run that simply doesn't pass the arg.
    const payload: Record<string, string> = {};
    for (const field of inputs) {
      const token = values[field.name] ?? "";
      if (token !== "") payload[field.name] = token;
    }
    setSubmitting(true);
    setErrors([]);
    runWorkflow(workflow, payload)
      .then((runId) => onLaunched(runId)) // success → parent pins the overlay to this run + closes (unmounts)
      .catch((err) => {
        setErrors(err instanceof ApiError ? err.errors : [{ message: "Could not start the run." }]);
        setSubmitting(false); // re-enable; on success the panel is already gone
      });
  }, [inputs, values, workflow, onLaunched]);

  return (
    <aside className="read-panel run-panel">
      <PanelHeader
        icon={ioCardIcon("input")}
        color={IO_COLOR}
        eyebrow="run workflow"
        eyebrowColor={IO_COLOR}
        name={workflowName}
        onClose={onClose}
      />
      <section className="read-panel-params">
        {/* "load inputs from" — Defaults or a past run (Phase 5). Only when there are inputs to prefill;
            a no-input workflow has nothing to load. Selecting a run prefills non-sensitive fields. */}
        {inputs.length > 0 && runs.length > 0 && (
          <label className="run-loadfrom">
            <span className="run-loadfrom-label">load inputs from</span>
            <select className="run-loadfrom-select" value={source} onChange={(e) => loadFrom(e.target.value)}>
              <option value="defaults">Defaults</option>
              {runs.map((run) => (
                <option key={run.run_id} value={run.run_id}>
                  {`${runMark(run).label} · ${timeAgo(run.start_time)}`}
                </option>
              ))}
            </select>
          </label>
        )}
        <RunForm
          inputs={inputs}
          values={values}
          onChange={onChange}
          onSubmit={onSubmit}
          submitting={submitting}
          errors={errors}
        />
      </section>
    </aside>
  );
}
