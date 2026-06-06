# Graph model node identity is structural, not a flattened string

The Graph model identifies each node by its structural position — `(node_id, ancestor_path, batch_index?)` — not by a flattened `parent__child` string. Renderers derive whatever flat ID they need (mermaid's `parent__child`, batch items keyed by label) from that structure; the model itself stays canonical.

We chose this over storing the mermaid-style flat string (the obvious, lower-churn option) because the runtime/trace already identifies nodes structurally — bare `node_id`, hierarchy carried in `sub_workflow_events`, batch items keyed by integer index — so a structural model lets a future live-overlay join runtime execution events onto static nodes directly and losslessly. The flat-string alternative forces every overlay consumer to reverse-engineer ancestry from `__` (which silently breaks on any `node_id` containing `__`) and to re-derive batch-item labels, and it cannot address dynamic-batch items at all (the visualizer emits no per-item node for them).

Reversible — the Graph model is greenfield — but recorded so it is not later "simplified" back to flat strings, which would quietly break the overlay seam. The flattening that mermaid needs is confined to one render-time helper in the mermaid renderer.
