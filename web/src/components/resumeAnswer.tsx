// The ONE resume-answer refusal machine (Task 176): both approval surfaces — the gate panel
// (GateCallout) and the failed-run Resume arm (ResumeControl) — deliver answers through
// POST /api/resume and face the same machine-readable refusal contract, so the state machine,
// the refusal dispatch, and the refusal panels live here once (two consumers = a real seam).
// The refusal classification is load-bearing ("no silent no-ops": every 4xx `refusal` maps to
// a panel state) — one copy means a new refusal kind or a body-field rename lands in one place.
//
// `force: true` is sent ONLY from the ack dialog's "Resume anyway" (the server never adds it);
// the dialog covers both ack-required refusals — stale workflow and side-effect re-fire — and
// names whichever one triggered it (edge ledger #6: force skips both when they co-occur).

import { useState } from "react";

import { ApiError, resumeRun } from "../api/client";
import type { ApiErrorEntry } from "../types";

export type ResumeAnswerPayload = { approve?: "yes" | "no"; choose?: string };

// The ack-required refusals, carrying the answer to retry with force after the explicit ack.
type ResumeConfirm =
  | { kind: "side_effect"; nodeId: string; nodeType: string; retry: ResumeAnswerPayload }
  | { kind: "stale"; hashKnown: boolean; retry: ResumeAnswerPayload };

export interface ResumeAnswer {
  // Disable-while-in-flight: a double-clicked Approve would spawn twice — the second child
  // refuses on the loader's superseded check (consumption policy), but one POST is cleaner.
  submitting: boolean;
  // Inline diagnostics for every refusal WITHOUT a dedicated panel state (answer_required,
  // not_resumable, nothing_to_resume, gate_stopped, still_running, fidelity, …).
  errors: ApiErrorEntry[];
  // The refusal panel to render INSTEAD of the surface's normal content, or null.
  refusal: { kind: "superseded"; newerRunId: string } | ResumeConfirm | null;
  submit: (answer?: ResumeAnswerPayload, force?: boolean) => void;
  cancelConfirm: () => void;
  // Superseded's action: pin the newer attempt (the parent's selectRun — the single pin path).
  pinNewer: () => void;
}

export function useResumeAnswer(run: string, onPinRun: (runId: string) => void): ResumeAnswer {
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<ApiErrorEntry[]>([]);
  const [superseded, setSuperseded] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ResumeConfirm | null>(null);

  const submit = (answer: ResumeAnswerPayload = {}, force = false): void => {
    setSubmitting(true);
    setErrors([]);
    setConfirm(null);
    // Superseded is terminal today (its only affordance is pinNewer — no re-submit path), but a
    // fresh submit clears it anyway so the machine stays self-consistent if a retry affordance is
    // ever added: `refusal` prioritizes superseded over confirm, so a stuck value would mask every
    // later refusal (PR #579 review note).
    setSuperseded(null);
    resumeRun({ run, ...answer, ...(force ? { force: true } : {}) })
      .then((newRunId) => onPinRun(newRunId)) // pin the new attempt — the banner clears, the surface unmounts
      .catch((err: unknown) => {
        setSubmitting(false);
        if (!(err instanceof ApiError)) {
          setErrors([{ message: "The resume request failed — could not reach the server." }]);
          return;
        }
        const refusal = err.body?.refusal;
        if (refusal === "superseded" && typeof err.body?.newer_execution_id === "string") {
          setSuperseded(err.body.newer_execution_id);
          return;
        }
        if (refusal === "stale_workflow") {
          // hash_known=false: a pre-content-hash trace — we cannot even verify it's unchanged.
          setConfirm({ kind: "stale", hashKnown: err.body?.hash_known !== false, retry: answer });
          return;
        }
        if (refusal === "side_effect_confirmation") {
          setConfirm({
            kind: "side_effect",
            nodeId: typeof err.body?.node_id === "string" ? err.body.node_id : "the failed step",
            nodeType: typeof err.body?.node_type === "string" ? err.body.node_type : "unknown",
            retry: answer,
          });
          return;
        }
        setErrors(err.errors);
      });
  };

  return {
    submitting,
    errors,
    refusal: superseded !== null ? { kind: "superseded", newerRunId: superseded } : confirm,
    submit,
    cancelConfirm: () => setConfirm(null),
    pinNewer: () => superseded !== null && onPinRun(superseded),
  };
}

/** Inline refusal/diagnostic list (DR-6 — never a blank panel). Renders each Diagnostic's
 *  `suggestions` under its message — the HOW-to-fix the JSON already carries; discarding it
 *  left the user a diagnosis with no next step (the RunForm rule, review-caught here too). */
export function GateErrors({ errors }: { errors: ApiErrorEntry[] }): JSX.Element | null {
  if (errors.length === 0) return null;
  return (
    <div className="gate-errors" role="alert">
      {errors.map((entry, i) => (
        <div key={i} className="gate-error">
          <p>{entry.message ?? entry.title ?? "Request failed."}</p>
          {entry.suggestions?.map((suggestion, j) => (
            <p key={j} className="gate-suggestion">
              {suggestion}
            </p>
          ))}
        </div>
      ))}
    </div>
  );
}

// The two refusal panels with an ACTION (everything else is GateErrors): superseded → offer the
// newer attempt; stale/side-effect → ack then retry the SAME answer with force. `context` picks
// the surface-true wording — a gate answer vs a bare resume ("answered" vs "resumed").
export function RefusalNotice({ answer, context }: { answer: ResumeAnswer; context: "gate" | "resume" }): JSX.Element | null {
  const { refusal, submitting } = answer;
  if (refusal === null) return null;

  if (refusal.kind === "superseded") {
    return (
      <>
        <p className="gate-note">
          {context === "gate"
            ? "This gate was already answered — a newer attempt exists."
            : "This run was already resumed — a newer attempt exists."}
        </p>
        <div className="gate-actions">
          <button type="button" className="gate-btn gate-primary" onClick={answer.pinNewer}>
            View newer attempt
          </button>
        </div>
      </>
    );
  }

  return (
    <>
      <p className="gate-note gate-warn">
        {refusal.kind === "side_effect" ? (
          <>
            Resuming re-runs <code>{refusal.nodeId}</code> ({refusal.nodeType}) — its side effects may fire
            again.
          </>
        ) : refusal.hashKnown ? (
          context === "gate" ? (
            "The workflow file changed since this run paused — the resumed steps may not match what was approved."
          ) : (
            "The workflow file changed since this run — the resumed steps may differ from what originally ran."
          )
        ) : (
          // The WHY, matching the CLI's wording: no hash to compare means the trace predates tracking.
          "Cannot verify the workflow is unchanged — this run predates workflow-hash tracking, so the resumed steps may not match the current file."
        )}
      </p>
      <div className="gate-actions">
        <button type="button" className="gate-btn" disabled={submitting} onClick={answer.cancelConfirm}>
          Cancel
        </button>
        <button
          type="button"
          className="gate-btn gate-primary"
          disabled={submitting}
          onClick={() => answer.submit(refusal.retry, true)}
        >
          Resume anyway
        </button>
      </div>
    </>
  );
}
