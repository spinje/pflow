// The Run side-panel (Task 175): a `.read-panel`-shell form, launched from the
// Rail's ▶. It owns the form STATE (values / submitting / errors) and the launch
// FETCH; the reusable RunForm owns the field rendering. Its open/close lives in
// GraphView (a boolean OUTSIDE the `selectedId` selection model — like the
// RunSelector popover — so it never races the three selection panels).
//
// Launch = spawn a detached `pflow run` (server-side, ADR-0008). On a successful
// spawn the parent switches the overlay to follow-newest-live (`onLaunched`) so the
// run lights up; a spawn/pre-flight failure shows inline in the form and never
// blanks the canvas (DR-6 — each fetch owns its failure).

import { useCallback, useMemo, useState } from "react";

import { PanelHeader } from "./PanelHeader";
import { RunForm } from "./RunForm";
import { ApiError, runWorkflow } from "../api/client";
import { inputFields, type InputField } from "../graph/flow";
import { IO_COLOR } from "../utils/format";
import { ioCardIcon } from "../utils/icons";
import type { ApiErrorEntry, RFGraph } from "../types";

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
  // Called after a successful spawn — GraphView follows-newest + closes the panel.
  onLaunched: () => void;
  onClose: () => void;
}): JSX.Element {
  const inputs = useMemo(() => inputFields(graph), [graph]);
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(inputs.map((f) => [f.name, defaultToken(f)])),
  );
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<ApiErrorEntry[]>([]);

  const onChange = useCallback((name: string, value: string) => {
    setValues((prev) => ({ ...prev, [name]: value }));
  }, []);

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
      .then(() => onLaunched()) // success → parent follows-newest + closes (this unmounts)
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
