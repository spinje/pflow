// The ONE data_type → form-control mapping for the run form (Task 175). A pure,
// total function: every declared input type lands on one of four HTML controls.
// The single place to extend when a new input type needs a richer control (e.g.
// a file-upload input) — locality, not a plugin system.
//
// `io.data_type` is the AUTHORED string, so it may be a Python alias or null; the
// canonical set is string,number,integer,boolean,array,object,any (core/types.py).
// Anything unrecognized falls back to a plain text box — the value still rides to
// the CLI as a `name=value` token where infer_type + declared-type coercion re-type
// it (channel A), so a text fallback is never lossy.

export type Control = "text" | "number" | "checkbox" | "textarea";

export function controlForType(dataType: string | null): Control {
  switch (dataType) {
    case "number":
    case "integer":
      return "number";
    case "boolean":
      return "checkbox";
    case "object":
    case "array":
      return "textarea"; // JSON typed into a multi-line box
    default:
      // string / any / null / unrecognized (incl. Python aliases like "str", "dict")
      return "text";
  }
}
