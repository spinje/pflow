# 21-cache.prompt-cache-incomplete

Minimal fixture for `cache.prompt-cache-incomplete`.

The workflow already declares `## Cache`; both LLM nodes declare only `a` in
`prompt_cache:` while referencing shared chunk `b` in their prompt body. The
analyzer should emit one grouped workflow-level recommendation with cleanup
steps before the corrected `prompt_cache:` lists.
