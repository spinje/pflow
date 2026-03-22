from importlib.metadata import PackageNotFoundError, version


def get_version() -> str:
    """Get pflow version from installed package metadata."""
    try:
        return version("pflow-cli")
    except PackageNotFoundError:
        return "0.0.0-dev"
