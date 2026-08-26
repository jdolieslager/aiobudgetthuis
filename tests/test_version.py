"""Guard the release procedure: both version declarations must match."""

from pathlib import Path
import tomllib

import aiobudgetthuis


def test_version_matches_pyproject():
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    with pyproject.open("rb") as f:
        version = tomllib.load(f)["project"]["version"]
    assert aiobudgetthuis.__version__ == version
