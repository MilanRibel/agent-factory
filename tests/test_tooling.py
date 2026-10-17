"""Negative tooling tests: prove the project config is active, not just installed.

Each test feeds a tool code that breaks a configured rule and asserts the tool
rejects it when run with the project's pyproject.toml.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"


def run_module(module: str, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    # Fixed argv from the project interpreter; no shell, no untrusted input.
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", module, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_ruff_reports_unused_import_and_bare_assert(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("import os\n\n\ndef check(value: int) -> None:\n    assert value\n")

    result = run_module(
        "ruff",
        "check",
        "--no-cache",
        "--config",
        str(PYPROJECT),
        "--output-format",
        "json",
        str(bad),
        cwd=tmp_path,
    )

    codes = {diagnostic["code"] for diagnostic in json.loads(result.stdout)}
    assert result.returncode != 0
    assert {"F401", "S101"} <= codes


def test_pyright_reports_type_error_and_strict_error_in_src(tmp_path: Path) -> None:
    # Strict mode is path-based, so mirror the repo layout around a copy of the config.
    shutil.copy(PYPROJECT, tmp_path / "pyproject.toml")
    src = tmp_path / "src"
    src.mkdir()
    (src / "bad.py").write_text(
        'count: int = "three"\n\n\ndef double(value):\n    return value * 2\n'
    )

    result = run_module("pyright", "--outputjson", "-p", str(tmp_path), cwd=tmp_path)

    report = json.loads(result.stdout)
    rules = {diagnostic.get("rule") for diagnostic in report["generalDiagnostics"]}
    assert result.returncode != 0
    assert "reportAssignmentType" in rules
    assert "reportMissingParameterType" in rules  # only reported in strict mode


def test_pytest_rejects_unregistered_marker(tmp_path: Path) -> None:
    test_file = tmp_path / "test_marker.py"
    test_file.write_text(
        "import pytest\n\n\n"
        "@pytest.mark.not_registered\n"
        "def test_marked() -> None:\n"
        "    pass\n"
    )

    result = run_module(
        "pytest",
        "-c",
        str(PYPROJECT),
        "--rootdir",
        str(tmp_path),
        "-p",
        "no:cacheprovider",
        str(test_file),
        cwd=tmp_path,
    )

    assert result.returncode != 0
    assert "'not_registered' not found in `markers`" in result.stdout + result.stderr
