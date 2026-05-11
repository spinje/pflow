#!/usr/bin/env bash
set -uo pipefail
cd "$BASELINE_REPO_ROOT"
WORKFLOW="$BASELINE_HOME/generated-padding.pflow.md"
LONG=$(cat "$BASELINE_DIR/_shared/long-stable-text.txt")

WORKFLOW="$WORKFLOW" LONG="$LONG" python3 - <<'PY'
import os
from pathlib import Path

long = os.environ["LONG"]
Path(os.environ["WORKFLOW"]).write_text(
    f"""# Padding Advisory

## Inputs

### a

Stable input A.

- type: string
- required: true

### b

Stable input B.

- type: string
- required: true

### c

Stable input C.

- type: string
- required: true

## Cache

```cache
Large stable prefix A:

{long}

${{a}}

Large stable prefix B:

{long}

${{b}}

Small suffix C:

${{c}}
```

## Steps

### producer

Writes the full prefix using all declared chunks.

- type: llm
- model: anthropic/claude-opus-4-5
- prompt_cache: [a, b, c]

```prompt
Prime the cache.
```

### consumer

Starts at the final chunk; padding with earlier chunks would reuse a larger
prefix.

- type: llm
- model: anthropic/claude-opus-4-5
- prompt_cache: [c]

```prompt
Use only c.
```

## Outputs

### consumer-out

Consumer output.

- source: ${{consumer.response}}
- type: string
""",
    encoding="utf-8",
)
PY

uv run pflow analyze-cache "$WORKFLOW" --no-trace-autoload a="$LONG" b="$LONG" c="$LONG"
