"""Workflow lint tests: CI lints every workflow with a pinned, verified actionlint.

The workflow-lint job installs actionlint and shellcheck from release tarballs
pinned by version and sha256, and actionlint runs shellcheck on every `run:`
script. With a wrong -shellcheck path actionlint silently disables that rule, so
the check ties the path in the run step to the one the install step runs with
--version. Config files and flags that silence actionlint are not allowed.
"""

import re
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
JOB = "workflow-lint"
RUN_STEP = "Run actionlint"
ACTIONLINT = "${RUNNER_TEMP}/actionlint/actionlint"
SHELLCHECK = "${RUNNER_TEMP}/shellcheck/shellcheck"

# Config files that actionlint reads from the repo; they can ignore errors.
ACTIONLINT_CONFIGS = (".github/actionlint.yaml", ".github/actionlint.yml")
# Flags that make actionlint skip errors or read another config.
SILENCING_FLAGS = ("ignore", "config-file")

Workflow = dict[str, Any]
Steps = list[dict[str, Any]]


def run_text(steps: Steps, name: str) -> str:
    return next((step.get("run", "") for step in steps if step.get("name") == name), "")


def has_verified_install(steps: Steps, name: str, sha256_var: str) -> bool:
    return any(
        sha256_var in line and "sha256sum --check" in line
        for line in run_text(steps, name).splitlines()
    )


def actionlint_argv(steps: Steps) -> list[str]:
    """The command in the Run actionlint step, split into words."""
    return shlex.split(run_text(steps, RUN_STEP).replace("\\\n", " "))


def flag_names(argv: list[str]) -> list[str]:
    """Flag names in argv, so `-flag`, `--flag` and `-flag=value` all give `flag`."""
    return [word.lstrip("-").split("=")[0] for word in argv if word.startswith("-")]


def flag_value(argv: list[str], name: str) -> str | None:
    for index, word in enumerate(argv):
        flag, sep, value = word.lstrip("-").partition("=")
        if word.startswith("-") and flag == name:
            if sep:
                return value
            return argv[index + 1] if index + 1 < len(argv) else None
    return None


def workflow_lint_problems(workflow: Workflow) -> list[str]:
    jobs = workflow.get("jobs", {})
    if JOB not in jobs:
        return [f"{JOB} job"]
    job = jobs[JOB]
    env = workflow.get("env", {})
    steps: Steps = job.get("steps", [])
    argv = actionlint_argv(steps)

    def pinned(key: str, pattern: str) -> bool:
        return re.fullmatch(pattern, str(env.get(key))) is not None

    passed = {
        "check name": job.get("name", JOB) == JOB,
        "pinned actionlint version": pinned("ACTIONLINT_VERSION", r"\d+\.\d+\.\d+"),
        "pinned actionlint sha256": pinned("ACTIONLINT_SHA256", r"[0-9a-f]{64}"),
        "pinned shellcheck version": pinned("SHELLCHECK_VERSION", r"\d+\.\d+\.\d+"),
        "pinned shellcheck sha256": pinned("SHELLCHECK_SHA256", r"[0-9a-f]{64}"),
        "verified actionlint install": has_verified_install(
            steps, "Install actionlint", "${ACTIONLINT_SHA256}"
        ),
        "verified shellcheck install": has_verified_install(
            steps, "Install shellcheck", "${SHELLCHECK_SHA256}"
        ),
        "installed actionlint runs": argv[:1] == [ACTIONLINT],
        "installed shellcheck used": flag_value(argv, "shellcheck") == SHELLCHECK
        and f'"{SHELLCHECK}" --version' in run_text(steps, "Install shellcheck"),
        "no silencing flags": not set(flag_names(argv)) & set(SILENCING_FLAGS),
        "no actionlint action": not any(
            "actionlint" in step.get("uses", "")
            for any_job in jobs.values()
            for step in any_job.get("steps", [])
        ),
    }
    return [name for name, ok in passed.items() if not ok]


def load_workflow() -> Workflow:
    return yaml.safe_load(CI_WORKFLOW.read_text())


def edit_run(workflow: Workflow, step_name: str, old: str, new: str) -> None:
    for step in workflow["jobs"][JOB]["steps"]:
        if step.get("name") == step_name:
            step["run"] = step["run"].replace(old, new)


def add_actionlint_action(workflow: Workflow) -> None:
    step = {"uses": "raven-actions/actionlint@" + "0" * 40}
    workflow["jobs"][JOB]["steps"].append(step)


# Each mutation breaks exactly the check it is named after.
MUTATIONS: dict[str, Callable[[Workflow], None]] = {
    "workflow-lint job": lambda wf: wf["jobs"].pop(JOB),
    "check name": lambda wf: wf["jobs"][JOB].update(name="Workflow lint"),
    "pinned actionlint version": lambda wf: wf["env"].update(
        ACTIONLINT_VERSION="latest"
    ),
    "pinned actionlint sha256": lambda wf: wf["env"].update(
        ACTIONLINT_SHA256="unverified"
    ),
    "pinned shellcheck version": lambda wf: wf["env"].update(
        SHELLCHECK_VERSION="latest"
    ),
    "pinned shellcheck sha256": lambda wf: wf["env"].update(
        SHELLCHECK_SHA256="unverified"
    ),
    "verified actionlint install": lambda wf: edit_run(
        wf, "Install actionlint", "sha256sum --check", "cat"
    ),
    "verified shellcheck install": lambda wf: edit_run(
        wf, "Install shellcheck", "sha256sum --check", "cat"
    ),
    "installed actionlint runs": lambda wf: edit_run(
        wf, RUN_STEP, f'"{ACTIONLINT}"', "actionlint"
    ),
    "installed shellcheck used": lambda wf: edit_run(
        wf, RUN_STEP, f'"{SHELLCHECK}"', '"${RUNNER_TEMP}/shellcheck"'
    ),
    "no silencing flags": lambda wf: edit_run(
        wf, RUN_STEP, " -verbose", " -verbose -ignore 'SC2086'"
    ),
    "no actionlint action": add_actionlint_action,
}


def test_ci_workflow_lint_is_configured() -> None:
    assert workflow_lint_problems(load_workflow()) == []


@pytest.mark.parametrize("name", MUTATIONS)
def test_check_reports_mutation(name: str) -> None:
    workflow = load_workflow()
    MUTATIONS[name](workflow)

    assert workflow != load_workflow()  # the mutation really changed something
    assert workflow_lint_problems(workflow) == [name]


def actionlint_config_problems(root: Path) -> list[str]:
    return [name for name in ACTIONLINT_CONFIGS if (root / name).exists()]


def test_repo_has_no_actionlint_config() -> None:
    assert actionlint_config_problems(REPO_ROOT) == []


@pytest.mark.parametrize("name", ACTIONLINT_CONFIGS)
def test_check_reports_actionlint_config(tmp_path: Path, name: str) -> None:
    config = tmp_path / name
    config.parent.mkdir(parents=True)
    config.write_text("")

    assert actionlint_config_problems(tmp_path) == [name]
