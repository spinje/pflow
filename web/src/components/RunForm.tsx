// The run-inputs form (Task 175) — the reusable seam, decoupled from the panel
// chrome (RunPanel owns open/close/resize + the launch fetch; this owns
// schema→values→submit→errors). CONTROLLED: the parent holds `values` and the
// submit handler, so the form's logic (control mapping, prefill display, required
// markers, the sensitive hint, the no-input confirm, inline 400 errors) is unit-
// testable in isolation.
//
// Value encoding is channel A: every control emits a TOKEN STRING (checkbox →
// "true"/"false", number → its digits, text → as-is, JSON textarea → raw JSON
// text). RunPanel sends them verbatim as the CLI's `name=value` argv, where
// infer_type + declared-type coercion re-type them — so the form is faithful to a
// hand-typed run.
//
// (The "load inputs from" picker is Phase 5 — it adds a prefill SOURCE on top of
// this same controlled surface, not new form mechanics.)

import { Markdown } from "./Markdown";
import { controlForType } from "../utils/controlForType";
import type { InputField } from "../graph/flow";
import type { ApiErrorEntry } from "../types";

export function RunForm({
  inputs,
  values,
  onChange,
  onSubmit,
  submitting,
  errors,
}: {
  inputs: InputField[];
  // Token-string value per input name (RunPanel owns the map + prefill).
  values: Record<string, string>;
  onChange: (name: string, value: string) => void;
  onSubmit: () => void;
  submitting: boolean;
  // Server diagnostics from a 400 (malformed body / pre-flight failure). Form-level,
  // not per-field — the pre-flight's diagnostics are not field-keyed.
  errors: ApiErrorEntry[];
}): JSX.Element {
  return (
    <form
      className="run-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (!submitting) onSubmit();
      }}
    >
      {inputs.length === 0 ? (
        // A no-input workflow is still an explicit, deliberate trigger (n8n-style),
        // not a run-on-click — show the confirm, nothing to fill.
        <p className="run-form-empty">This workflow takes no inputs.</p>
      ) : (
        <>
          <h3 className="run-form-heading">Inputs</h3>
          {inputs.map((field) => (
            <RunField key={field.name} field={field} value={values[field.name] ?? ""} onChange={onChange} />
          ))}
        </>
      )}

      {errors.length > 0 && (
        <div className="run-form-errors" role="alert">
          {errors.map((entry, i) => (
            <div className="run-form-error" key={i}>
              <p className="run-form-error-msg">{entry.message ?? entry.title ?? "The run could not be started."}</p>
              {/* the HOW-to-fix the pre-flight Diagnostic carries (e.g. "Available inputs: topic") — shown
                  so the browser doesn't discard the fix hint the JSON already has. */}
              {entry.suggestions?.map((s, j) => (
                <p className="run-form-error-fix" key={j}>
                  {s}
                </p>
              ))}
            </div>
          ))}
        </div>
      )}

      <button className="run-submit" type="submit" disabled={submitting}>
        {submitting ? "Starting…" : "▶ Run"}
      </button>
    </form>
  );
}

function RunField({
  field,
  value,
  onChange,
}: {
  field: InputField;
  value: string;
  onChange: (name: string, value: string) => void;
}): JSX.Element {
  const control = controlForType(field.dataType);
  const id = `run-field-${field.name}`;
  const typeLabel = [field.dataType, field.required ? "required" : null].filter(Boolean).join(" · ");

  return (
    <div className="run-field">
      <label className="run-field-label" htmlFor={id}>
        <span className="run-field-name">{field.name}</span>
        {field.required && (
          <span className="run-field-required" aria-label="required">
            *
          </span>
        )}
        {typeLabel && <span className="run-field-type">{typeLabel}</span>}
      </label>

      {control === "checkbox" ? (
        <input
          id={id}
          type="checkbox"
          checked={value === "true"}
          onChange={(e) => onChange(field.name, e.target.checked ? "true" : "false")}
        />
      ) : control === "textarea" ? (
        <textarea
          id={id}
          className="run-field-input"
          value={value}
          rows={3}
          spellCheck={false}
          onChange={(e) => onChange(field.name, e.target.value)}
        />
      ) : (
        <input
          id={id}
          className="run-field-input"
          type={control === "number" ? "number" : "text"}
          value={value}
          onChange={(e) => onChange(field.name, e.target.value)}
        />
      )}

      {field.description && (
        <div className="run-field-desc">
          <Markdown text={field.description} />
        </div>
      )}
      {field.sensitive && (
        // The form never COLLECTS a secret: blank → omitted from argv → the spawned
        // run resolves it by name from settings/env (5-tier precedence). The user
        // may still type a literal override. This is a hint, not the redaction rule.
        <p className="run-field-hint">Provided from settings/env — leave blank to use it, or type an override.</p>
      )}
    </div>
  );
}
