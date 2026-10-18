"""Workflow policy tests: every workflow is SHA-pinned and least-privilege.

The policy holds for every file in .github/workflows/:
- every `uses:` is pinned to a 40-hex commit SHA (local `./` actions excepted);
- top-level `permissions` is declared and grants no write access, because a
  top-level write reaches every job and would bypass the allowlist;
- a job-level write needs a WRITE_ALLOWLIST entry with a reason, and `write-all`
  is never allowed; an allowlist entry without a matching write is reported too;
- no `pull_request_target` trigger;
- every checkout sets `persist-credentials: false`;
- no `${{ ... }}` expression in a `run:` script (pass values through `env:`).

ci.yml also installs gitleaks in two jobs. Until that copy is removed, both
install steps must stay identical.
"""

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
CI_WORKFLOW = WORKFLOWS_DIR / "ci.yml"
GITLEAKS_INSTALL = "Install gitleaks"
GITLEAKS_JOBS = ("test", "secret-scan")
PINNED_USES = re.compile(r"[^@\s]+@[0-9a-f]{40}")

Workflow = dict[str, Any]
AllowlistKey = tuple[str, str, str]  # (workflow file, job, permission scope)

# Job-level write permissions and the reason each job needs it.
WRITE_ALLOWLIST: dict[AllowlistKey, str] = {}

# A workflow that follows the policy: a pinned checkout without stored
# credentials, a local action and a shell variable (not an expression) in run.
CLEAN_WORKFLOW = """\
on:
  pull_request:
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: ./.github/actions/setup
      - run: echo "${GITHUB_REF}"
"""

PINNED_CHECKOUT = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1"
TOP_LEVEL_PERMISSIONS = "permissions:\n  contents: read\n"
RUNS_ON = "    runs-on: ubuntu-24.04\n"
JOB_WRITE = RUNS_ON + "    permissions:\n      contents: write\n"
ALLOWLIST_KEY: AllowlistKey = ("ci.yml", "build", "contents")

# Each violation is (old, new, problem): replacing old with new in CLEAN_WORKFLOW
# must make the check report exactly that problem.
VIOLATIONS: dict[str, tuple[str, str, str]] = {
    "action pinned to a tag": (
        PINNED_CHECKOUT,
        "actions/checkout@v4",
        "ci.yml: build.steps[0]: actions/checkout@v4 is not pinned to a commit SHA",
    ),
    "action pinned to a short SHA": (
        PINNED_CHECKOUT,
        "actions/checkout@3d3c42e",
        "ci.yml: build.steps[0]: actions/checkout@3d3c42e"
        " is not pinned to a commit SHA",
    ),
    "reusable workflow pinned to a branch": (
        "jobs:\n",
        "jobs:\n  call:\n    uses: octo-org/ci/.github/workflows/build.yml@main\n",
        "ci.yml: call: octo-org/ci/.github/workflows/build.yml@main"
        " is not pinned to a commit SHA",
    ),
    "top-level write-all": (
        TOP_LEVEL_PERMISSIONS,
        "permissions: write-all\n",
        "ci.yml: top-level permissions: write-all",
    ),
    "missing top-level permissions": (
        TOP_LEVEL_PERMISSIONS,
        "",
        "ci.yml: no top-level permissions",
    ),
    "top-level write scope": (
        TOP_LEVEL_PERMISSIONS,
        "permissions:\n  contents: write\n",
        "ci.yml: top-level permissions: contents: write",
    ),
    "job write-all": (
        RUNS_ON,
        RUNS_ON + "    permissions: write-all\n",
        "ci.yml: build: permissions: write-all",
    ),
    "job write without allowlist entry": (
        RUNS_ON,
        JOB_WRITE,
        "ci.yml: build: permissions: contents: write has no allowlist entry",
    ),
    "pull_request_target as a map": (
        "on:\n  pull_request:\n",
        "on:\n  pull_request_target:\n",
        "ci.yml: pull_request_target trigger",
    ),
    "pull_request_target in a list": (
        "on:\n  pull_request:\n",
        "on: [push, pull_request_target]\n",
        "ci.yml: pull_request_target trigger",
    ),
    "pull_request_target as a string": (
        "on:\n  pull_request:\n",
        "on: pull_request_target\n",
        "ci.yml: pull_request_target trigger",
    ),
    "checkout without with": (
        "        with:\n          persist-credentials: false\n",
        "",
        "ci.yml: build.steps[0]: checkout without persist-credentials: false",
    ),
    "checkout with persist-credentials true": (
        "persist-credentials: false",
        "persist-credentials: true",
        "ci.yml: build.steps[0]: checkout without persist-credentials: false",
    ),
    "expression in run": (
        'echo "${GITHUB_REF}"',
        'echo "${{ github.head_ref }}"',
        "ci.yml: build.steps[2]: expression in run",
    ),
}


def is_pinned(uses: str) -> bool:
    return uses.startswith("./") or PINNED_USES.fullmatch(uses) is not None


def trigger_events(workflow: dict[Any, Any]) -> list[str]:
    # YAML 1.1 reads the bare key `on` as the boolean True, so keys are not all str.
    triggers = workflow.get(True, workflow.get("on"))
    if isinstance(triggers, str):
        return [triggers]
    if isinstance(triggers, list | dict):
        return [str(event) for event in triggers]
    return []


def write_scopes(permissions: Any) -> list[str]:
    """Scopes set to write in a permissions map (`write-all` is checked apart)."""
    if not isinstance(permissions, dict):
        return []
    return [scope for scope, level in permissions.items() if level == "write"]


def top_level_permission_problems(name: str, workflow: Workflow) -> list[str]:
    permissions = workflow.get("permissions")
    if permissions is None:
        return [f"{name}: no top-level permissions"]
    if permissions == "write-all":
        return [f"{name}: top-level permissions: write-all"]
    return [
        f"{name}: top-level permissions: {scope}: write"
        for scope in write_scopes(permissions)
    ]


def uses_problems(where: str, uses: str | None) -> list[str]:
    if uses is None or is_pinned(uses):
        return []
    return [f"{where}: {uses} is not pinned to a commit SHA"]


def step_problems(where: str, step: dict[str, Any]) -> list[str]:
    uses = step.get("uses")
    problems = uses_problems(where, uses)
    is_checkout = uses is not None and uses.startswith("actions/checkout@")
    if is_checkout and (step.get("with") or {}).get("persist-credentials") is not False:
        problems.append(f"{where}: checkout without persist-credentials: false")
    if "${{" in step.get("run", ""):
        problems.append(f"{where}: expression in run")
    return problems


def policy_problems(
    workflows_dir: Path, allowlist: Mapping[AllowlistKey, str] = WRITE_ALLOWLIST
) -> list[str]:
    files = sorted([*workflows_dir.glob("*.yml"), *workflows_dir.glob("*.yaml")])
    if not files:
        return [f"no workflow files in {workflows_dir}"]

    problems: list[str] = []
    writes: set[AllowlistKey] = set()
    for file in files:
        name = file.name
        workflow: Workflow = yaml.safe_load(file.read_text())
        if "pull_request_target" in trigger_events(workflow):
            problems.append(f"{name}: pull_request_target trigger")
        problems += top_level_permission_problems(name, workflow)

        for job_id, job in workflow.get("jobs", {}).items():
            if job.get("permissions") == "write-all":
                problems.append(f"{name}: {job_id}: permissions: write-all")
            for scope in write_scopes(job.get("permissions")):
                writes.add((name, job_id, scope))
                if (name, job_id, scope) not in allowlist:
                    problems.append(
                        f"{name}: {job_id}: permissions: {scope}: write"
                        " has no allowlist entry"
                    )
            # A job that calls a reusable workflow has `uses` instead of steps.
            problems += uses_problems(f"{name}: {job_id}", job.get("uses"))
            for index, step in enumerate(job.get("steps", [])):
                problems += step_problems(f"{name}: {job_id}.steps[{index}]", step)

    for key, reason in allowlist.items():
        entry = "/".join(key)
        if not reason.strip():
            problems.append(f"allowlist: {entry} has no reason")
        if key not in writes:
            problems.append(f"allowlist: {entry} is unused")
    return problems


def find_step(workflow: Workflow, job_id: str, name: str) -> dict[str, Any] | None:
    steps = workflow.get("jobs", {}).get(job_id, {}).get("steps", [])
    return next((step for step in steps if step.get("name") == name), None)


def gitleaks_install_problems(workflow: Workflow) -> list[str]:
    steps = {job: find_step(workflow, job, GITLEAKS_INSTALL) for job in GITLEAKS_JOBS}
    missing = [job for job, step in steps.items() if step is None]
    if missing:
        return [f"{GITLEAKS_INSTALL} missing in {job}" for job in missing]
    first, second = GITLEAKS_JOBS
    if steps[first] != steps[second]:
        return [f"{GITLEAKS_INSTALL} differs between {first} and {second}"]
    return []


def write_workflow(directory: Path, old: str = "", new: str = "") -> Path:
    """Write CLEAN_WORKFLOW with old replaced by new as directory/ci.yml."""
    text = CLEAN_WORKFLOW.replace(old, new) if old else CLEAN_WORKFLOW
    assert not old or text != CLEAN_WORKFLOW  # the replacement really happened
    (directory / "ci.yml").write_text(text)
    return directory


def test_repo_workflows_follow_policy() -> None:
    assert policy_problems(WORKFLOWS_DIR) == []


def test_clean_workflow_passes(tmp_path: Path) -> None:
    assert policy_problems(write_workflow(tmp_path)) == []


@pytest.mark.parametrize("name", VIOLATIONS)
def test_check_reports_violation(tmp_path: Path, name: str) -> None:
    old, new, problem = VIOLATIONS[name]

    assert policy_problems(write_workflow(tmp_path, old, new)) == [problem]


def test_check_accepts_allowlisted_job_write(tmp_path: Path) -> None:
    workflows = write_workflow(tmp_path, RUNS_ON, JOB_WRITE)
    allowlist = {ALLOWLIST_KEY: "pushes the release tag"}

    assert policy_problems(workflows, allowlist) == []


def test_check_reports_allowlist_entry_without_reason(tmp_path: Path) -> None:
    workflows = write_workflow(tmp_path, RUNS_ON, JOB_WRITE)
    allowlist = {ALLOWLIST_KEY: " "}

    assert policy_problems(workflows, allowlist) == [
        "allowlist: ci.yml/build/contents has no reason"
    ]


def test_check_reports_unused_allowlist_entry(tmp_path: Path) -> None:
    allowlist = {ALLOWLIST_KEY: "pushes the release tag"}

    assert policy_problems(write_workflow(tmp_path), allowlist) == [
        "allowlist: ci.yml/build/contents is unused"
    ]


def test_check_reports_empty_workflows_dir(tmp_path: Path) -> None:
    assert policy_problems(tmp_path) == [f"no workflow files in {tmp_path}"]


def load_ci() -> Workflow:
    return yaml.safe_load(CI_WORKFLOW.read_text())


def install_step(workflow: Workflow, job_id: str) -> dict[str, Any]:
    step = find_step(workflow, job_id, GITLEAKS_INSTALL)
    assert step is not None
    return step


def test_gitleaks_installs_are_identical() -> None:
    assert gitleaks_install_problems(load_ci()) == []


@pytest.mark.parametrize("job_id", GITLEAKS_JOBS)
def test_check_reports_changed_gitleaks_install(job_id: str) -> None:
    workflow = load_ci()
    step = install_step(workflow, job_id)
    run = step["run"]
    step["run"] = run.replace("sha256sum", "Sha256sum", 1)

    assert sum(a != b for a, b in zip(run, step["run"], strict=True)) == 1
    assert gitleaks_install_problems(workflow) == [
        f"{GITLEAKS_INSTALL} differs between test and secret-scan"
    ]


@pytest.mark.parametrize("job_id", GITLEAKS_JOBS)
def test_check_reports_missing_gitleaks_install(job_id: str) -> None:
    workflow = load_ci()
    workflow["jobs"][job_id]["steps"].remove(install_step(workflow, job_id))

    assert gitleaks_install_problems(workflow) == [
        f"{GITLEAKS_INSTALL} missing in {job_id}"
    ]
