"""Tests for release metadata consistency."""

import re
from pathlib import Path

import public_api_sdk


ROOT = Path(__file__).resolve().parents[1]


def test_package_version_matches_pyproject() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)

    assert match is not None
    assert public_api_sdk.__version__ == match.group(1)


def test_readme_version_badge_matches_package_version() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert f"badge/version-{public_api_sdk.__version__}-" in readme
