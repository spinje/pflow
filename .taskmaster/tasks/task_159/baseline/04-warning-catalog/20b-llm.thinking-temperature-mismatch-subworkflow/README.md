# 20b-llm.thinking-temperature-mismatch-subworkflow

Same constraint as 20-..., but the bad LLM node lives inside a
sub-workflow. Locks the `_add_child_provenance` prefix
("In step '...' sub-workflow:") on the propagated diagnostic so a
refactor of child-IR resolution cannot silently lose ID propagation.
