"""Spike 4 — operational checks for LiteLLM.

Covers:
  1. Logger silencing — identify the right knob.
  2. Thread safety — 5 concurrent completions via ThreadPoolExecutor.
  3. Env-var key resolution — with HOME overridden to an empty dir.
  4. Hidden config files — confirm nothing touches ~/.litellm/...
  5. Transitive dep audit — list full install footprint.
"""

from __future__ import annotations

import concurrent.futures as futures
import io
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _common import banner, inject_keys_into_env, stable_context_block

inject_keys_into_env()

import litellm  # noqa: E402


# -------------------------------------------------------------------------
# 1. Logger silencing
# -------------------------------------------------------------------------
def test_logger_silencing() -> dict:
    """Make a call with each candidate silencing knob, capture stderr.

    Goal: find the knob that produces zero stderr output on a normal call.
    """
    banner("1. Logger silencing")

    system_block = stable_context_block()
    results: dict[str, dict] = {}

    knobs = [
        ("none", lambda: None),
        ("suppress_debug_info", lambda: setattr(litellm, "suppress_debug_info", True)),
        ("set_verbose=False", lambda: setattr(litellm, "set_verbose", False)),
        ("logger_warning", lambda: [
            logging.getLogger(n).setLevel(logging.WARNING)
            for n in list(logging.Logger.manager.loggerDict)
            if n.startswith("LiteLLM") or n.startswith("litellm")
        ]),
        ("combined", lambda: (
            setattr(litellm, "suppress_debug_info", True),
            setattr(litellm, "set_verbose", False),
            [
                logging.getLogger(n).setLevel(logging.WARNING)
                for n in list(logging.Logger.manager.loggerDict)
                if n.startswith("LiteLLM") or n.startswith("litellm")
            ],
        )),
    ]

    # Reset state between knobs isn't fully possible (loggers are global),
    # so we do them in escalating order and note cumulative effect.
    for name, apply_knob in knobs:
        apply_knob()

        # Redirect stderr briefly
        import contextlib
        buf = io.StringIO()
        try:
            with contextlib.redirect_stderr(buf):
                litellm.completion(
                    model="gemini/gemini-2.5-flash",
                    messages=[
                        {"role": "system", "content": system_block},
                        {"role": "user", "content": "Reply OK."},
                    ],
                    temperature=0.0,
                    max_tokens=10,
                )
            stderr_captured = buf.getvalue()
        except Exception as e:
            stderr_captured = f"[CALL FAILED: {type(e).__name__}: {e}]"
        results[name] = {
            "stderr_len": len(stderr_captured),
            "stderr_preview": stderr_captured[:300] if stderr_captured else "(empty)",
        }
        print(f"  knob={name}: stderr={len(stderr_captured)} chars")

    return results


# -------------------------------------------------------------------------
# 2. Thread safety (5 concurrent calls)
# -------------------------------------------------------------------------
def test_thread_safety() -> dict:
    """Fire 5 concurrent calls; confirm responses are distinct and no races."""
    banner("2. Thread safety (5 concurrent litellm.completion calls)")

    def one_call(i: int) -> dict:
        try:
            r = litellm.completion(
                model="gemini/gemini-2.5-flash",
                messages=[
                    {"role": "user", "content": f"Reply with the single word CALL-{i}."}
                ],
                temperature=0.0,
                max_tokens=20,
            )
            return {
                "i": i,
                "content": r.choices[0].message.content,
                "prompt_tokens": r.usage.prompt_tokens,
                "ok": True,
            }
        except Exception as e:
            return {"i": i, "ok": False, "error": f"{type(e).__name__}: {e}"}

    t0 = time.time()
    with futures.ThreadPoolExecutor(max_workers=5) as pool:
        out = list(pool.map(one_call, range(5)))
    dt = time.time() - t0
    print(f"  5 parallel calls finished in {dt:.2f}s")
    for r in out:
        print(f"    {r}")

    # Basic check: each call should respond distinctly.
    unique_contents = {r.get("content") for r in out if r.get("ok")}
    return {
        "wall_time_s": dt,
        "n_successful": sum(1 for r in out if r.get("ok")),
        "n_unique_contents": len(unique_contents),
        "all_calls": out,
    }


# -------------------------------------------------------------------------
# 3 + 4. Env-var resolution with clean HOME
# -------------------------------------------------------------------------
def test_clean_home_env_resolution() -> dict:
    """Child Python process with HOME overridden to empty dir.

    Confirms LiteLLM doesn't reach for any ~/.litellm config.
    """
    banner("3+4. Clean HOME env-var key resolution")
    # Only Gemini to keep cost tiny; confirm env-var-only auth works.
    script = r"""
import os, sys, json
# Print what LiteLLM sees for HOME so we can verify the override worked.
print(json.dumps({"HOME": os.environ.get("HOME"), "has_gemini": bool(os.environ.get("GEMINI_API_KEY"))}), file=sys.stderr)
# Import litellm LAST so any config reads happen with clean HOME.
import litellm
litellm.suppress_debug_info = True
r = litellm.completion(
    model="gemini/gemini-2.5-flash",
    messages=[{"role": "user", "content": "Reply OK."}],
    temperature=0.0, max_tokens=10,
)
print("OK:", r.choices[0].message.content)
"""
    tmp_home = Path("/tmp/pflow_spike_clean_home")
    tmp_home.mkdir(exist_ok=True)
    env = dict(os.environ)
    env["HOME"] = str(tmp_home)
    # Keep the GEMINI_API_KEY but nothing else user-specific
    result = subprocess.run(
        ["uv", "run", "--with", "litellm==1.83.7", "python", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent.parent),
    )
    print("  stdout:", result.stdout.strip())
    print("  stderr:", result.stderr.strip())
    # List any files LiteLLM may have created
    created = [str(p.relative_to(tmp_home)) for p in tmp_home.rglob("*") if p.is_file()]
    return {
        "rc": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "files_created_in_clean_home": created,
    }


# -------------------------------------------------------------------------
# 5. Transitive dep audit
# -------------------------------------------------------------------------
def test_transitive_deps() -> dict:
    """uv pip list --tree from a fresh ephemeral venv with only litellm.

    Captures dep footprint, size, any boto3/google-cloud/azure bloat.
    """
    banner("5. Transitive dependency audit")
    # Use `uv run --with litellm` in a throwaway directory to isolate.
    # We capture `uv pip list` but the --with env is hidden; the stable trick
    # is to run `uv pip install` into a venv, then list. Easier: invoke pip
    # inside the uv --with environment.
    script = r"""
import subprocess, sys, json
# List all installed packages
res = subprocess.run([sys.executable, "-m", "pip", "list", "--format=json"], capture_output=True, text=True)
packages = json.loads(res.stdout)
print(json.dumps({"n_packages": len(packages), "packages": packages}, indent=2))
"""
    result = subprocess.run(
        ["uv", "run", "--isolated", "--with", "litellm==1.83.7", "python", "-c", script],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).parent.parent.parent),
    )
    try:
        data = json.loads(result.stdout)
    except Exception:
        data = {"raw_stdout": result.stdout, "stderr": result.stderr}

    # Scan for heavy deps
    packages = data.get("packages", [])
    names = {p["name"].lower() for p in packages}
    concerning = sorted([n for n in names if any(p in n for p in ["boto3", "google-cloud", "azure", "aws", "anthropic", "openai", "google-genai"])])

    print(f"  total packages in litellm install: {data.get('n_packages')}")
    print(f"  concerning heavyweight deps: {concerning}")
    return {
        "n_packages": data.get("n_packages"),
        "concerning_deps": concerning,
        "all_packages": [p["name"] for p in packages],
    }


# -------------------------------------------------------------------------
def main() -> None:
    all_results = {
        "logger_silencing": test_logger_silencing(),
        "thread_safety": test_thread_safety(),
        "clean_home": test_clean_home_env_resolution(),
        "transitive_deps": test_transitive_deps(),
    }
    banner("SPIKE 4 SUMMARY")
    print(json.dumps(all_results, indent=2, default=str))


if __name__ == "__main__":
    main()
