# Contributing to pflow

So you want to contribute — cool. Here's what you need to know to get going without wasting your time or mine.

## Setting up

You'll need Python 3.10+ and [uv](https://docs.astral.sh/uv/) (we use uv instead of pip for everything).

```bash
git clone https://github.com/spinje/pflow.git
cd pflow
make install
```

That installs dependencies and sets up pre-commit hooks. If `make install` works and you can run `make test` without everything catching fire, you're good.

## Running things

```bash
make test    # runs the full test suite with pytest
make check   # linting, type checking, the whole quality gauntlet
```

Run both before you open a PR. CI will catch it anyway, but it's faster to catch it locally than to wait for GitHub Actions to tell you what you already could've known.

## Making changes

The usual fork-and-PR flow:

1. Fork the repo
2. Create a branch off `main` (call it whatever makes sense, I don't care about branch naming conventions)
3. Make your changes
4. Run `make test` and `make check`
5. Open a PR against `main`

That's basically it.

## What makes a good PR

Just keep it focused. One PR should do one thing — fix a bug, add a feature, refactor something. If you find yourself writing "also while I was in there I..." in the PR description, that's probably two PRs.

Include tests for new stuff. Not because I'm a test coverage zealot, but because pflow changes a lot and tests are what keep things from silently breaking three weeks later when someone touches something nearby, and as you may know, AI agents love to break things.

A clear description helps too. Doesn't have to be long — just explain what you changed and why. If there's a tradeoff you made, mention it. If you tried something else first and it didn't work, that's useful context.

## What if I'm not sure about something?

Open an issue first. Or a draft PR. Or just ask. I'd rather have a quick conversation before you spend a weekend on something that might not fit, than have you find out after the fact. No one wants that.

## Code style

We use `ruff` for linting and formatting, `mypy` for type checking. The pre-commit hooks handle most of it automatically. If you write type hints and don't shadow builtins, you're probably fine. The CI will yell at you if something's off.

One thing worth mentioning: we use `uv` everywhere, not `pip`. So `uv pip install`, `uv run pytest`, etc. If you see yourself typing `pip install` you've gone off the path.

## Tests

Tests live in `tests/` and roughly mirror the `src/pflow/` structure. If you're adding something to `src/pflow/core/`, the tests probably go in `tests/test_core/`. You get the idea.

We use pytest. Nothing fancy (apart from running tests paralell in 4 threads by default) — just write test functions, assert things, move on. The existing CLAUDE.md files should keep AI agents in check and know what to do. But making a final pass to ensure all tests are testing actual behavior and not just implementation details is always a good idea. We dont optimize for test coverage.

## Questions?

Open an issue or start a [discussion](https://github.com/spinje/pflow/discussions). Either works.

## License

By contributing, you agree that your contributions will be licensed under the [FSL-1.1-ALv2](LICENSE) license.
