# Task 49: Prepare and Publish `pflow-cli` to PyPI with Trusted Publishers

## ID

49

## Title

Prepare and Publish `pflow-cli` to PyPI (TestPyPI → PyPI) with Reproducible Builds & OIDC Trusted Publishers

## Description

Package the `pflow` CLI as a Python distribution named **`pflow-cli`**, using a safe import namespace (`pflow_cli`) and a `pflow` console script. Produce reproducible wheels and an sdist, validate metadata/rendering, and ship first to **TestPyPI** and then to **PyPI** via **Trusted Publishers (GitHub Actions OIDC)**. Include a clear release procedure, versioning policy, and rollback plan.

## Status

pending

## Dependencies

* Finalize naming: **distribution** `pflow-cli`, **import** `pflow_cli`, **console script** `pflow` (optional alias `pf`).
* Minimum Python version decision (assume `>=3.10`).
* GitHub repo with CI permissions enabled and ability to create tags/releases.
* PyPI/TestPyPI accounts with 2FA; ability to add **Trusted Publisher** mapping for the GitHub repo/workflow.

## Priority

high

## Details

### Scope & Assumptions

* We do **not** control the `pflow` name on PyPI; we will publish as `pflow-cli`.
* Users will run the CLI as `pflow`. Library imports use `pflow_cli` to avoid conflicts.
* Build backend: **hatchling** (simple, modern, no `setup.py`).
* Target platforms: macOS/Linux/Windows, Python 3.10+.

### What Will Be Implemented

1. **Project Layout (src-layout & typing)**

   ```
   pyproject.toml
   README.md
   CHANGELOG.md
   LICENSE
   src/
     pflow_cli/
       __init__.py
       __about__.py        # holds __version__
       __main__.py         # Typer/Click app entrypoint
       cli/…               # CLI commands (optional)
       core/…              # library modules (optional)
     pflow_cli/py.typed    # if exporting type hints for users
   tests/
   ```

   * `__main__.py` exposes `app` for the console script.
   * `py.typed` marks the package as typed for downstream users.

2. **Packaging Configuration (`pyproject.toml`)**

   ```toml
   [build-system]
   requires = ["hatchling>=1.21", "hatch-vcs>=0.4"]
   build-backend = "hatchling.build"

   [project]
   name = "pflow-cli"
   dynamic = ["version"]
   description = "Shell-native, deterministic, memory-aware pipeline runner (CLI)"
   readme = "README.md"
   requires-python = ">=3.10"
   license = { text = "Apache-2.0" }
   authors = [{ name = "Vesperance", email = "dev@example.com" }]
   classifiers = [
     "Programming Language :: Python :: 3",
     "Programming Language :: Python :: 3 :: Only",
     "License :: OSI Approved :: Apache Software License",
     "Operating System :: OS Independent",
     "Typing :: Typed",
     "Environment :: Console",
     "Intended Audience :: Developers"
   ]
   dependencies = [
     "typer>=0.12",
     "pydantic>=2",
     "rich>=13"
   ]

   [project.optional-dependencies]
   cli = [
     "uvloop; platform_system != 'Windows'"
   ]
   # Add more feature groups later, e.g.:
   # mcp = ["..."]
   # cloud = ["httpx>=0.27", "pydantic-settings>=2"]

   [project.scripts]
   pflow = "pflow_cli.__main__:app"
   pf = "pflow_cli.__main__:app"

   [tool.hatch.build]
   packages = ["src/pflow_cli"]
   only-packages = true
   include = [
     "src/pflow_cli/py.typed",
   ]

   [tool.hatch.version]
   source = "vcs"

   [tool.hatch.build.targets.wheel]
   packages = ["src/pflow_cli"]
   ```

   `src/pflow_cli/__about__.py`:

   ```python
   __version__ = "0.1.0"
   ```

   `src/pflow_cli/__init__.py`:

   ```python
   from .__about__ import __version__
   ```

   `src/pflow_cli/__main__.py` (Typer example):

   ```python
   import typer
   from . import __version__

   app = typer.Typer(add_completion=False)

   @app.callback()
   def main(version: bool = typer.Option(False, "--version", help="Show version and exit")):
     if version:
       typer.echo(__version__)
       raise typer.Exit()

   @app.command()
   def hello(name: str = "world"):
     typer.echo(f"hello, {name}")

   if __name__ == "__main__":
     app()
   ```

3. **Versioning & Changelog**

   * **SemVer** (`MAJOR.MINOR.PATCH`), starting at `0.1.0`.
   * Keep a human-readable `CHANGELOG.md` (Keep-a-Changelog style).
   * Version managed by `hatch-vcs`: tagging a commit updates the built package version automatically.

4. **Local Build & Validation**

   ```bash
   # Fresh venv
   python -m venv .venv && . .venv/bin/activate  # (Windows: .venv\Scripts\activate)
   pip install --upgrade pip build twine

   # Build
   python -m build

   # Validate metadata & long_description
   twine check dist/*

   # Smoke test in an isolated venv
   python -m venv .venv-smoke && . .venv-smoke/bin/activate
   pip install dist/pflow_cli-0.1.0-py3-none-any.whl
   pflow --version
   pflow hello --name test
   python -c "import pflow_cli as m; print(m.__version__)"
   ```

5. **Publish to TestPyPI (manual first push)**

   ```bash
   # Option A: manual (once)
   pip install twine
   twine upload --repository testpypi dist/*
   # Install from TestPyPI (in a clean env)
   pip install -i https://test.pypi.org/simple "pflow-cli[cli]==0.1.0"
   pflow --help
   ```

6. **Trusted Publishers via GitHub Actions (OIDC)**

   * In **TestPyPI** and **PyPI** web UIs, add a **Trusted Publisher** for your GitHub repo/workflow.
   * Use tag-driven releases:

     * `vX.Y.Z-rc.N` → publish to **TestPyPI**.
     * `vX.Y.Z` (no suffix) → publish to **PyPI**.
   * Example workflow `.github/workflows/publish.yml`:

     ```yaml
     name: Build & Publish

     on:
       push:
         tags:
           - "v[0-9]+.[0-9]+.[0-9]+"
           - "v[0-9]+.[0-9]+.[0-9]+-rc.*"

     permissions:
       id-token: write
       contents: read

     jobs:
       build:
         runs-on: ubuntu-latest
         steps:
           - uses: actions/checkout@v4
           - uses: actions/setup-python@v5
             with:
               python-version: "3.11"
           - run: python -m pip install --upgrade pip build
           - run: python -m build
           - name: Upload artifact
             uses: actions/upload-artifact@v4
             with:
               name: dist
               path: dist/*

       publish:
         needs: build
         runs-on: ubuntu-latest
         steps:
           - uses: actions/download-artifact@v4
             with:
               name: dist
               path: dist
           - name: Publish to TestPyPI for RC tags
             if: contains(github.ref, '-rc.')
             uses: pypa/gh-action-pypi-publish@release/v1
             with:
               repository-url: https://test.pypi.org/legacy/
           - name: Publish to PyPI for final tags
             if: "!contains(github.ref, '-rc.')"
             uses: pypa/gh-action-pypi-publish@release/v1
     ```

7. **Name-Collision Mitigation & Future Migration**

   * Keep **import** namespace `pflow_cli` to avoid clashing with the unrelated `pflow` package.
   * Console script remains `pflow` for UX.
   * If you later acquire `pflow` on PyPI:

     1. publish `pflow==X.Y.Z` that depends on `pflow-cli==X.Y.Z`;
     2. optionally add `src/pflow/__init__.py` re-exporting a stable surface from `pflow_cli`.

8. **Security & Supply Chain**

   * Enforce 2FA on PyPI maintainers.
   * Use **Trusted Publishers** (OIDC) instead of username/password secrets.
   * Pin GitHub Actions by major tag at least (`@v4`, `@v1`) and review change logs periodically.
   * Include `py.typed` for type consumers; avoid vendoring large deps.
   * Prefer wheels; ensure sdist includes all needed files (src layout + `pyproject.toml` + readme).

9. **Docs & Install Instructions**

   * `README.md` must include:

     * Short description, features, quickstart.
     * Install variants: `pip install "pflow-cli[cli]"`, `pipx install "pflow-cli[cli]"`.
     * Basic usage: `pflow --help`, `pflow hello`.
     * Supported Python versions and OS.
     * Link to CHANGELOG and license.

10. **Release Procedure (operator checklist)**

    1. Confirm changelog entries and bump tag: `git tag v0.1.0 && git push --tags`.
    2. CI builds artifacts; for `-rc` tags it publishes to **TestPyPI**.
    3. Smoke-install from TestPyPI on macOS/Linux/Windows.
    4. If green, tag final: `git tag v0.1.0` (no `-rc`) and push; CI publishes to **PyPI**.
    5. Announce release; create GitHub release notes from the changelog.

11. **Rollback / Yank Plan**

    * If a critical issue is found post-release: publish hotfix `v0.1.1`.
    * If the release is broken/uninstallable: **yank** the version on PyPI (keeps it installable by exact pin but excludes from latest resolution).

### Key Technical Decisions

* **Distribution vs import** name split to avoid current `pflow` namespace collision.
* **hatchling + hatch-vcs** for minimal config and tag-derived versions.
* **OIDC Trusted Publishers** for passwordless, auditable releases.
* **SemVer** and `CHANGELOG.md` for predictable upgrades.
* Provide a short alias console script (`pf`) but keep `pflow` as primary.

### Integration Points

* CI must run existing tests (if any) before building.
* CLI’s `--version` is sourced from `pflow_cli.__about__.__version__`.
* If extras (e.g., `mcp`, `cloud`) are added, lazy-import optional deps and produce helpful error messages when missing.

## Test Strategy

### Unit Tests

* `test_version.py`: ensure `__version__` is present and matches the tag in build artifacts.
* `test_cli_entrypoint.py`: `pflow --version` prints semver; `pflow hello` exits 0.
* Import tests: `import pflow_cli` works; `pflow_cli.__version__` set.

### Integration Tests

* Packaging smoke test in CI: build wheel + sdist, `pip install` into a clean venv on linux/mac/windows runners, run `pflow --help`.
* `twine check` on distributions to validate README rendering and metadata.
* Test extras: `pip install "pflow-cli[cli]"` then ensure CLI optional features (e.g., uvloop on non-Windows) behave or degrade gracefully.

### Key Test Scenarios

* Install from **TestPyPI** and **PyPI** succeeds across OSes.
* Console scripts `pflow` and `pf` are generated and executable.
* `requires-python` correctly prevents installs on unsupported versions.
* Long description renders correctly on TestPyPI/PyPI.
* Optional deps via `[cli]` extra install and are respected by the CLI.

