# Contributing to pflow

Thanks for your interest in contributing to pflow!

## Getting started

```bash
git clone https://github.com/spinje/pflow.git
cd pflow
make install
make test
```

## Development workflow

1. **Check existing issues** — See if someone's already working on it
2. **Open an issue first** — For significant changes, discuss before coding
3. **Create a branch** — Work on a feature branch, not main
4. **Write tests** — New features need tests
5. **Run checks** — `make check` before submitting

## Running tests

```bash
make test        # Run all tests
make check       # Run linting and type checks
```

## Code style

- We use `ruff` for linting and formatting
- We use `mypy` for type checking
- Run `make check` to verify your changes pass all checks

## Submitting changes

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run `make test` and `make check`
5. Open a pull request

## Questions?

- 💬 [Discussions](https://github.com/spinje/pflow/discussions) — ask questions
- 🐛 [Issues](https://github.com/spinje/pflow/issues) — report bugs

## License

By contributing, you agree that your contributions will be licensed under the [FSL-1.1-ALv2](LICENSE) license.
