# 03 — prompt_cache on a non-LLM (shell) node

**Surface**: 02-validator-errors

**Triggers**: A shell node has `prompt_cache: [article]`. The field is only
valid on `type: llm` nodes (per spec).

**Expected behavior**: `pflow run` exits non-zero with the `cache.invalid-on-non-llm`
warning ID. Error names the field and the node type.

**Mutation contract**: if validation accepts the field on non-LLM nodes, the
field is silently ignored at runtime — author's expectation of caching
behavior never fires; debugging takes hours.
