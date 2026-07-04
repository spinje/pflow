# Narration demo

A small, self-contained workflow for showing off pflow's **agent voice narration** (Task 174):
open it in the Viewer, then point-and-narrate a node with

```bash
pflow ui focus voice-demo draft-notes --say "[excited] this is where the LLM drafts the notes"
```

- **`voice-demo.pflow.md`** — Release Notes Assistant: gather commits → LLM draft → classify →
  branch (major/minor). A handful of distinct node kinds (shell / llm / code / branch) so each
  `--say` lands on something visibly different.

Auto-validated by `tests/test_docs/test_example_validation.py` (IR-schema regression coverage).
