"""Workflow trigger tests: required checks run on every PR.

A `paths` or `paths-ignore` filter on a trigger lets a PR skip the workflow. A
skipped required check either blocks the PR forever or lets it through unchecked,
so no workflow trigger may filter on paths.
"""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
PATH_FILTERS = ("paths", "paths-ignore")

# Same triggers as ci.yml, with the bare `on:` key.
CLEAN_WORKFLOW = """\
on:
  pull_request:
  push:
    branches: [main]
jobs: {}
"""


def trigger_problems(workflows_dir: Path) -> list[str]:
    files = sorted([*workflows_dir.glob("*.yml"), *workflows_dir.glob("*.yaml")])
    if not files:
        return [f"no workflow files in {workflows_dir}"]

    problems: list[str] = []
    for file in files:
        workflow = yaml.safe_load(file.read_text())
        # YAML 1.1 reads the bare key `on` as the boolean True.
        triggers = workflow.get(True, workflow.get("on"))
        if triggers is None:
            problems.append(f"{file.name}: no on: triggers")
        elif isinstance(triggers, dict):  # `on: push` and `on: [...]` cannot filter
            problems += [
                f"{file.name}: {event}.{key}"
                for event, config in triggers.items()
                if isinstance(config, dict)
                for key in PATH_FILTERS
                if key in config
            ]
    return problems


def test_repo_workflows_have_no_path_filters() -> None:
    assert trigger_problems(WORKFLOWS_DIR) == []


@pytest.mark.parametrize("key", PATH_FILTERS)
@pytest.mark.parametrize("event", ["pull_request", "push"])
def test_check_reports_path_filter(tmp_path: Path, event: str, key: str) -> None:
    trigger = f"  {event}:\n"
    filtered = CLEAN_WORKFLOW.replace(trigger, f"{trigger}    {key}: ['src/**']\n")
    assert filtered != CLEAN_WORKFLOW  # the filter really went in
    (tmp_path / "ci.yml").write_text(filtered)

    assert trigger_problems(tmp_path) == [f"ci.yml: {event}.{key}"]


def test_check_reports_empty_workflows_dir(tmp_path: Path) -> None:
    assert trigger_problems(tmp_path) == [f"no workflow files in {tmp_path}"]
