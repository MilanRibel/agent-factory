"""Secret scan tests: CI blocks a committed key, also after it was removed again.

The fake key is generated at runtime in tmp_path and never committed. Without a
gitleaks binary the scan tests skip locally and fail in CI (CI is set there).
The ci.yml checks pin down the secret-scan job and the verified gitleaks install
that secret-scan and test rely on. Files that reconfigure or silence gitleaks may
not exist in the repo root; #8 makes them protected paths, so relaxing that check
needs an issue.
"""

import json
import os
import re
import secrets
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
INSTALL_STEP = "Install gitleaks"
KEY_HIT = [("generic-api-key", "settings.py")]

# Config and ignore files that gitleaks picks up from the repo root it scans.
GITLEAKS_OVERRIDES = (".gitleaks.toml", ".gitleaksignore", ".gitleaks/")

# Characters for the fake key. No vowels, y, m, p, x or 0, so no generic-api-key
# stopword ("http", "md5", "000000", ...) can occur in the key and hide it from
# the rule. The names avoid rule keywords, or the scan would flag this line.
ALPHABET = "bcdfghjklnqrstvwzBCDFGHJKLNQRSTVWZ123456789"
DIGITS = "123456789"

Workflow = dict[str, Any]
Steps = list[dict[str, Any]]


def fake_key() -> str:
    # The trailing digit keeps the key out of the rule's letters-only allowlist.
    body = "".join(secrets.choice(ALPHABET) for _ in range(39))
    return body + secrets.choice(DIGITS)


def gitleaks_binary() -> str:
    path = shutil.which("gitleaks")
    if path is None:
        if os.environ.get("CI"):
            pytest.fail("gitleaks is not on PATH; the CI job must install it")
        pytest.skip("gitleaks is not installed")
    return path


def run_tool(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    # Keep the user's git config (hooks, signing) out of the scratch repos.
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    # Fixed argv with resolved binaries; no shell, no untrusted input.
    return subprocess.run(  # noqa: S603
        argv, cwd=cwd, env=env, capture_output=True, text=True, check=False
    )


def scan(mode: str, target: Path, report: Path) -> tuple[int, list[dict[str, Any]]]:
    """Run `gitleaks <mode>` on target; return its exit code and JSON findings."""
    result = run_tool(
        [
            gitleaks_binary(),
            mode,
            "--redact",
            "--no-banner",
            "--report-format",
            "json",
            "--report-path",
            str(report),
            ".",
        ],
        cwd=target,
    )
    findings = json.loads(report.read_text()) if report.exists() else []
    return result.returncode, findings


def hits(findings: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(finding["RuleID"], finding["File"]) for finding in findings]


def test_clean_directory_passes(tmp_path: Path) -> None:
    target = tmp_path / "scan"
    target.mkdir()
    (target / "settings.py").write_text('log_level = "info"\n')

    returncode, findings = scan("dir", target, tmp_path / "report.json")

    assert returncode == 0
    assert findings == []


def test_fake_key_in_directory_is_detected(tmp_path: Path) -> None:
    target = tmp_path / "scan"
    target.mkdir()
    key = fake_key()
    (target / "settings.py").write_text(f'api_key = "{key}"\n')
    report = tmp_path / "report.json"

    returncode, findings = scan("dir", target, report)

    assert returncode == 1
    assert hits(findings) == KEY_HIT
    assert key not in report.read_text()  # --redact keeps the key out of the report


def test_fake_key_removed_from_history_is_detected(tmp_path: Path) -> None:
    git = shutil.which("git")
    assert git is not None
    repo = tmp_path / "repo"
    repo.mkdir()
    settings = repo / "settings.py"
    identity = ["-c", "user.name=test", "-c", "user.email=test@example.invalid"]

    def commit(message: str) -> None:
        for args in (["add", "--all"], [*identity, "commit", "--quiet", "-m", message]):
            assert run_tool([git, *args], cwd=repo).returncode == 0

    assert run_tool([git, "init", "--quiet"], cwd=repo).returncode == 0
    settings.write_text(f'api_key = "{fake_key()}"\n')
    commit("Add settings")
    settings.unlink()
    commit("Remove settings")

    returncode, findings = scan("git", repo, tmp_path / "report.json")

    assert not settings.exists()  # only the history still holds the key
    assert returncode == 1
    assert hits(findings) == KEY_HIT


def load_workflow() -> Workflow:
    return yaml.safe_load(CI_WORKFLOW.read_text())


def scan_flags(steps: Steps) -> set[str]:
    """Flags passed to `gitleaks git` in these steps."""
    return {
        word
        for step in steps
        for line in step.get("run", "").splitlines()
        if line.split()[:2] == ["gitleaks", "git"]
        for word in line.split()[2:]
    }


def has_verified_install(steps: Steps) -> bool:
    return any(
        step.get("name") == INSTALL_STEP
        and "GITHUB_PATH" in step.get("run", "")
        and any(
            "${GITLEAKS_SHA256}" in line and "sha256sum --check" in line
            for line in step.get("run", "").splitlines()
        )
        for step in steps
    )


def secret_scan_problems(workflow: Workflow) -> list[str]:
    jobs = workflow.get("jobs", {})
    if "secret-scan" not in jobs:
        return ["secret-scan job"]
    env = workflow.get("env", {})
    version = str(env.get("GITLEAKS_VERSION"))
    sha256 = str(env.get("GITLEAKS_SHA256"))
    scan_steps: Steps = jobs["secret-scan"].get("steps", [])
    flags = scan_flags(scan_steps)
    passed = {
        "pinned version": re.fullmatch(r"\d+\.\d+\.\d+", version) is not None,
        "pinned sha256": re.fullmatch(r"[0-9a-f]{64}", sha256) is not None,
        "full-history checkout": any(
            step.get("uses", "").startswith("actions/checkout@")
            and step.get("with", {}).get("fetch-depth") == 0
            for step in scan_steps
        ),
        "redacted scan": "--redact" in flags,
        "gitleaks:allow ignored": "--ignore-gitleaks-allow" in flags,
        "verified install in secret-scan": has_verified_install(scan_steps),
        "verified install in test": has_verified_install(
            jobs.get("test", {}).get("steps", [])
        ),
        "no gitleaks-action": not any(
            "gitleaks-action" in step.get("uses", "")
            for job in jobs.values()
            for step in job.get("steps", [])
        ),
    }
    return [name for name, ok in passed.items() if not ok]


def edit_runs(workflow: Workflow, job: str, old: str, new: str) -> None:
    for step in workflow["jobs"][job]["steps"]:
        if old in step.get("run", ""):
            step["run"] = step["run"].replace(old, new)


def shallow_checkout(workflow: Workflow) -> None:
    for step in workflow["jobs"]["secret-scan"]["steps"]:
        step.get("with", {}).pop("fetch-depth", None)


def add_gitleaks_action(workflow: Workflow) -> None:
    step = {"uses": "gitleaks/gitleaks-action@" + "0" * 40}
    workflow["jobs"]["secret-scan"]["steps"].append(step)


# Each mutation breaks exactly the check it is named after.
MUTATIONS: dict[str, Callable[[Workflow], None]] = {
    "secret-scan job": lambda wf: wf["jobs"].pop("secret-scan"),
    "pinned version": lambda wf: wf["env"].update(GITLEAKS_VERSION="latest"),
    "pinned sha256": lambda wf: wf["env"].update(GITLEAKS_SHA256="unverified"),
    "full-history checkout": shallow_checkout,
    "redacted scan": lambda wf: edit_runs(wf, "secret-scan", " --redact", ""),
    "gitleaks:allow ignored": lambda wf: edit_runs(
        wf, "secret-scan", " --ignore-gitleaks-allow", ""
    ),
    "verified install in secret-scan": lambda wf: edit_runs(
        wf, "secret-scan", "sha256sum --check", "cat"
    ),
    "verified install in test": lambda wf: edit_runs(
        wf, "test", "sha256sum --check", "cat"
    ),
    "no gitleaks-action": add_gitleaks_action,
}


def test_ci_secret_scan_is_configured() -> None:
    assert secret_scan_problems(load_workflow()) == []


@pytest.mark.parametrize("name", MUTATIONS)
def test_check_reports_mutation(name: str) -> None:
    workflow = load_workflow()
    MUTATIONS[name](workflow)

    assert workflow != load_workflow()  # the mutation really changed something
    assert secret_scan_problems(workflow) == [name]


def gitleaks_override_problems(root: Path) -> list[str]:
    return [name for name in GITLEAKS_OVERRIDES if (root / name).exists()]


def test_repo_has_no_gitleaks_overrides() -> None:
    assert gitleaks_override_problems(REPO_ROOT) == []


@pytest.mark.parametrize("name", GITLEAKS_OVERRIDES)
def test_check_reports_gitleaks_override(tmp_path: Path, name: str) -> None:
    if name.endswith("/"):
        (tmp_path / name).mkdir()
    else:
        (tmp_path / name).write_text("")

    assert gitleaks_override_problems(tmp_path) == [name]
