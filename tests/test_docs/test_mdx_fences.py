"""Tests for the MDX fence/leak linter (scripts/check_mdx_fences.py).

The linter guards against `${...}` workflow templates leaking out of code
blocks in docs. When that happens Mintlify compiles them to live JS expressions
that throw `ReferenceError` at render and crash the page — a failure `mint
validate` does not catch because the compiled JS is syntactically valid.
"""

import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "check_mdx_fences.py"


def _load_linter():
    spec = importlib.util.spec_from_file_location("check_mdx_fences", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_linter = _load_linter()


# The exact shape of the bug that broke the changelog: a 3-backtick outer fence
# wrapping a nested 3-backtick block, so the nested block's bare ``` closes the
# outer fence early and the `${input.text}` line lands in raw prose.
BROKEN = """\
---
title: "T"
---

<Update label="x">
  ```markdown
  ## Cache

  ```cache [brief]
  ${brief}
  ```

  ### extract-features
  - prompt: Extract features from ${input.text}
  ```
</Update>
"""

# Same example, fixed by giving the outer fence one extra backtick.
FIXED = """\
---
title: "T"
---

<Update label="x">
  ````markdown
  ## Cache

  ```cache [brief]
  ${brief}
  ```

  ### extract-features
  - prompt: Extract features from ${input.text}
  ````
</Update>

Inline `${item}` in prose is fine, and so is JSX like `cols={2}`.
"""


def test_flags_leaked_template_in_prose():
    problems = _linter.check_text(BROKEN, "broken.mdx")
    assert problems, "linter should flag the leaked ${input.text}"
    assert any("input.text" in p and "leaked" in p for p in problems), problems


def test_fixed_example_is_clean():
    assert _linter.check_text(FIXED, "fixed.mdx") == []


def test_inline_and_jsx_braces_are_not_flagged():
    # `${item}` inside inline code and bare JSX `{2}` must not trip the check.
    text = "A line with `${item}` inline code and a <Columns cols={2}> tag.\n"
    assert _linter.check_text(text, "prose.mdx") == []


def test_unclosed_fence_is_flagged():
    text = "intro\n\n```python\nx = 1\n"
    problems = _linter.check_text(text, "unclosed.mdx")
    assert any("never closed" in p for p in problems), problems


def test_real_docs_have_no_leaks():
    docs_dir = _REPO_ROOT / "docs"
    problems: list[str] = []
    for mdx in sorted(docs_dir.rglob("*.mdx")):
        problems.extend(_linter.check_text(mdx.read_text(encoding="utf-8"), str(mdx)))
    assert not problems, "Leaked templates / unclosed fences in docs:\n" + "\n".join(problems)
