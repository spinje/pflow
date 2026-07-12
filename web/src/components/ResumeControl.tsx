// The Resume button on failed/interrupted runs (Task 176): one click spawns a detached
// `pflow resume <id>` via POST /api/resume — the same spawn seam and pre-flight the gate
// panel uses, a different entry arm. Rendered by GraphView inside the run callout, directly
// below RunProgress, ONLY for a failed banner or a stopped (killed) run — a PAUSED run is
// the GateCallout's job, and success/degraded/denied have nothing to resume.
//
// The refusal machine (superseded → newer attempt; side-effect / stale-workflow →
// ack-then-force; everything else → inline diagnostics, no retry affordance) is the shared
// useResumeAnswer/RefusalNotice seam in resumeAnswer.tsx. An idempotent `llm` entry never
// refuses, so it resumes dialog-free — the CLI's silent path.

import { GateErrors, RefusalNotice, useResumeAnswer } from "./resumeAnswer";

export function ResumeControl({
  run,
  onPinRun,
}: {
  // The failed/interrupted run's execution id (the pinned runId — the resume token).
  run: string;
  // Pin the overlay to a run: the resumed attempt (200) or the newer attempt (superseded).
  // GraphView passes selectRun — the single pin path.
  onPinRun: (runId: string) => void;
}): JSX.Element {
  const answer = useResumeAnswer(run, onPinRun);

  if (answer.refusal !== null) {
    return (
      <div className="resume-control">
        <RefusalNotice answer={answer} context="resume" />
      </div>
    );
  }

  return (
    <div className="resume-control">
      <GateErrors errors={answer.errors} />
      <div className="gate-actions">
        <button
          type="button"
          className="gate-btn gate-primary"
          disabled={answer.submitting}
          onClick={() => answer.submit()}
        >
          ↻ Resume
        </button>
      </div>
    </div>
  );
}
