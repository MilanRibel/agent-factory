"""set-rulesets.sh tests: a human protects main with a ruleset, Claude Code never does.

The script runs directly (which also proves the exec bit) with an env built from
scratch: a fake gh (tests/fake_gh.py) first on PATH, no tokens, and CLAUDECODE only
when a test sets it, because pytest inherits CLAUDECODE=1 inside Claude Code.
--apply only ever runs against the fake gh, with --repo example-owner/example-repo.
The ruleset checks pin down the rules from issue #6, and the drift check ties the
required status checks to the job names in the workflow files. The deny rule for
--apply in .claude/settings.json is checked in tests/test_claude_settings.py.
"""

import copy
import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "set-rulesets.sh"
FAKE_GH = REPO_ROOT / "tests" / "fake_gh.py"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
RULESET_NAME = "protect-main"
TEST_REPO = "example-owner/example-repo"
RULESETS = f"repos/{TEST_REPO}/rulesets"
LISTING = f"{RULESETS}?includes_parents=false"

# Keep the user's git config (hooks, signing) away from git in the tests and script.
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
# The repository admin role as a bypass actor.
ADMIN_BYPASS = {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}

# --repo values that are not OWNER/NAME or could add path segments or a query.
INVALID_REPOS = {
    "no-owner": "agent-factory",
    "extra-segment": "a/b/c",
    "dot-dot": "owner/..",
    "query": "owner/repo?x=1",
    "leading-dash": "-owner/repo",
    "empty": "",
}
ORIGINS = {
    "https": f"https://github.com/{TEST_REPO}.git",
    "scp": f"git@github.com:{TEST_REPO}.git",
    "ssh": f"ssh://git@github.com/{TEST_REPO}.git",
}
# Claude Code sets CLAUDECODE=1; an empty value must count as set too.
CLAUDECODE_VALUES = {"set": "1", "empty": ""}

Ruleset = dict[str, Any]


@pytest.fixture
def gh_dir(tmp_path: Path) -> Path:
    """A fake gh in gh/bin, with its call log and rulesets in gh/state."""
    directory = tmp_path / "gh"
    state = directory / "state"
    (directory / "bin").mkdir(parents=True)
    state.mkdir()
    shim = directory / "bin" / "gh"
    shim.write_text(
        "#!/bin/sh\n"
        f"exec {shlex.quote(sys.executable)} {shlex.quote(str(FAKE_GH))} "
        f'{shlex.quote(str(state))} "$@"\n'
    )
    shim.chmod(0o755)
    return directory


def run_script(
    script: Path, *args: str, gh_dir: Path, claudecode: str | None = None
) -> subprocess.CompletedProcess[str]:
    # A plain assert, so a missing script fails the test instead of erroring it.
    assert script.is_file(), f"{script} does not exist"
    env = {"PATH": f"{gh_dir / 'bin'}:/usr/bin:/bin", **GIT_ENV}
    if claudecode is not None:
        env["CLAUDECODE"] = claudecode
    # CI runners have a real gh in /usr/bin; it must never be the one that runs.
    assert shutil.which("gh", path=env["PATH"]) == str(gh_dir / "bin" / "gh")
    # Fixed argv from the tests; no shell.
    return subprocess.run(  # noqa: S603
        [str(script), *args],
        cwd=gh_dir,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
    )


def gh_calls(gh_dir: Path) -> list[dict[str, Any]]:
    log = gh_dir / "state" / "calls.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines()]


def call_endpoints(gh_dir: Path) -> list[tuple[str, str]]:
    return [(call["method"], call["endpoint"]) for call in gh_calls(gh_dir)]


def seed_rulesets(gh_dir: Path, rulesets: dict[int, Ruleset]) -> None:
    data = {str(ruleset_id): ruleset for ruleset_id, ruleset in rulesets.items()}
    (gh_dir / "state" / "rulesets.json").write_text(json.dumps(data))


def stored_rulesets(gh_dir: Path) -> dict[int, Ruleset]:
    path = gh_dir / "state" / "rulesets.json"
    data: dict[str, Ruleset] = json.loads(path.read_text()) if path.exists() else {}
    return {int(ruleset_id): ruleset for ruleset_id, ruleset in data.items()}


def dry_run_payload(gh_dir: Path) -> Ruleset:
    result = run_script(SCRIPT, "--repo", TEST_REPO, gh_dir=gh_dir)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def run_git(*args: str, cwd: Path) -> None:
    git = shutil.which("git")
    assert git is not None
    env = {**os.environ, **GIT_ENV}
    # Fixed argv with a resolved binary; no shell, no untrusted input.
    result = subprocess.run(  # noqa: S603
        [git, *args], cwd=cwd, env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def copy_script_into_git_repo(tmp_path: Path, origin_url: str) -> Path:
    """Copy the script into a fresh git repo with this origin; return the copy."""
    assert SCRIPT.is_file(), f"{SCRIPT} does not exist"
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    script = repo / "scripts" / SCRIPT.name
    shutil.copy2(SCRIPT, script)  # copy2 keeps the exec bit
    run_git("init", "--quiet", cwd=repo)
    run_git("remote", "add", "origin", origin_url, cwd=repo)
    return script


def rules_by_type(payload: Ruleset) -> dict[str, dict[str, Any]]:
    return {rule.get("type"): rule for rule in payload.get("rules", [])}


def rule_parameters(payload: Ruleset, rule_type: str) -> dict[str, Any]:
    return rules_by_type(payload).get(rule_type, {}).get("parameters", {})


def ruleset_problems(payload: Ruleset) -> list[str]:
    rules = rules_by_type(payload)
    pull_request = rule_parameters(payload, "pull_request")
    status_checks = rule_parameters(payload, "required_status_checks")
    passed = {
        "ruleset name": payload.get("name") == RULESET_NAME,
        "branch target": payload.get("target") == "branch",
        "active enforcement": payload.get("enforcement") == "active",
        "default branch only": payload.get("conditions", {}).get("ref_name")
        == {"include": ["~DEFAULT_BRANCH"], "exclude": []},
        # Explicit: a PUT without bypass_actors keeps the ones added in the UI.
        "no bypass actors": payload.get("bypass_actors") == [],
        "deletion blocked": "deletion" in rules,
        "force push blocked": "non_fast_forward" in rules,
        "pull request required": "pull_request" in rules,
        # These two pass without their rule, so removing a rule breaks one check.
        "no required approvals in phase 0": "pull_request" not in rules
        or pull_request.get("required_approving_review_count") == 0,
        "status checks required": "required_status_checks" in rules,
        "branch up to date": "required_status_checks" not in rules
        or status_checks.get("strict_required_status_checks_policy") is True,
    }
    return [name for name, ok in passed.items() if not ok]


def required_contexts(payload: Ruleset) -> set[str]:
    checks = rule_parameters(payload, "required_status_checks")
    return {check.get("context") for check in checks.get("required_status_checks", [])}


def workflow_job_names(workflows_dir: Path) -> set[str]:
    """Check names of all jobs: the job's name if it has one, else its id."""
    files = sorted([*workflows_dir.glob("*.yml"), *workflows_dir.glob("*.yaml")])
    return {
        job.get("name", job_id)
        for file in files
        for job_id, job in yaml.safe_load(file.read_text()).get("jobs", {}).items()
    }


def drift_problems(payload: Ruleset, workflows_dir: Path) -> list[str]:
    contexts = required_contexts(payload)
    jobs = workflow_job_names(workflows_dir)
    return sorted(
        [
            *(f"required check {name} has no workflow job" for name in contexts - jobs),
            *(f"job {name} is not a required check" for name in jobs - contexts),
        ]
    )


def remove_rule(rule_type: str) -> Callable[[Ruleset], None]:
    def mutate(payload: Ruleset) -> None:
        payload["rules"] = [
            rule for rule in payload["rules"] if rule.get("type") != rule_type
        ]

    return mutate


# Each mutation breaks exactly the check it is named after.
MUTATIONS: dict[str, Callable[[Ruleset], None]] = {
    "ruleset name": lambda rs: rs.update(name="main-protection"),
    "branch target": lambda rs: rs.update(target="tag"),
    "active enforcement": lambda rs: rs.update(enforcement="evaluate"),
    "default branch only": lambda rs: rs["conditions"]["ref_name"].update(
        include=["~ALL"]
    ),
    "no bypass actors": lambda rs: rs["bypass_actors"].append(ADMIN_BYPASS),
    "deletion blocked": remove_rule("deletion"),
    "force push blocked": remove_rule("non_fast_forward"),
    "pull request required": remove_rule("pull_request"),
    "no required approvals in phase 0": lambda rs: rule_parameters(
        rs, "pull_request"
    ).update(required_approving_review_count=1),
    "status checks required": remove_rule("required_status_checks"),
    "branch up to date": lambda rs: rule_parameters(
        rs, "required_status_checks"
    ).update(strict_required_status_checks_policy=False),
}

# Each edit of ci.yml (old, new) renames the lint check and gives these problems.
RENAMES: dict[str, tuple[str, str, list[str]]] = {
    "job-id": (
        "\n  lint:\n",
        "\n  ruff:\n",
        ["job ruff is not a required check", "required check lint has no workflow job"],
    ),
    "display-name": (
        "\n  lint:\n",
        "\n  lint:\n    name: Lint\n",
        ["job Lint is not a required check", "required check lint has no workflow job"],
    ),
}


def test_dry_run_prints_ruleset_without_calling_gh(gh_dir: Path) -> None:
    result = run_script(SCRIPT, gh_dir=gh_dir)

    assert result.returncode == 0, result.stderr
    assert ruleset_problems(json.loads(result.stdout)) == []
    assert gh_calls(gh_dir) == []  # no network, no gh auth


@pytest.mark.parametrize("name", MUTATIONS)
def test_check_reports_mutation(gh_dir: Path, name: str) -> None:
    payload = dry_run_payload(gh_dir)
    original = copy.deepcopy(payload)
    MUTATIONS[name](payload)

    assert payload != original  # the mutation really changed something
    assert ruleset_problems(payload) == [name]


def test_required_checks_match_workflow_jobs(gh_dir: Path) -> None:
    assert drift_problems(dry_run_payload(gh_dir), WORKFLOWS_DIR) == []


@pytest.mark.parametrize("edit", RENAMES)
def test_drift_check_reports_renamed_job(
    tmp_path: Path, gh_dir: Path, edit: str
) -> None:
    payload = dry_run_payload(gh_dir)
    old, new, problems = RENAMES[edit]
    workflows = tmp_path / "workflows"
    shutil.copytree(WORKFLOWS_DIR, workflows)
    ci = workflows / "ci.yml"
    text = ci.read_text()
    assert text.count(old) == 1  # the edit hits exactly the lint job
    ci.write_text(text.replace(old, new))

    assert drift_problems(payload, workflows) == problems


def test_drift_check_reports_dropped_check(gh_dir: Path) -> None:
    payload = dry_run_payload(gh_dir)
    parameters = rule_parameters(payload, "required_status_checks")
    checks = parameters["required_status_checks"]
    parameters["required_status_checks"] = [
        check for check in checks if check["context"] != "workflow-lint"
    ]

    assert len(parameters["required_status_checks"]) == len(checks) - 1
    assert drift_problems(payload, WORKFLOWS_DIR) == [
        "job workflow-lint is not a required check"
    ]


def test_apply_creates_then_updates_one_ruleset(gh_dir: Path) -> None:
    first = run_script(SCRIPT, "--apply", "--repo", TEST_REPO, gh_dir=gh_dir)
    second = run_script(SCRIPT, "--apply", "--repo", TEST_REPO, gh_dir=gh_dir)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert call_endpoints(gh_dir) == [
        ("GET", LISTING),
        ("POST", RULESETS),
        ("GET", LISTING),
        ("PUT", f"{RULESETS}/1"),
    ]
    assert stored_rulesets(gh_dir) == {1: dry_run_payload(gh_dir)}


def test_apply_leaves_other_rulesets_alone(gh_dir: Path) -> None:
    # The name starts with protect-main, so a prefix match would update it.
    other = {"name": f"{RULESET_NAME}-old"}
    seed_rulesets(gh_dir, {5: other})

    result = run_script(SCRIPT, "--apply", "--repo", TEST_REPO, gh_dir=gh_dir)

    assert result.returncode == 0, result.stderr
    assert call_endpoints(gh_dir) == [("GET", LISTING), ("POST", RULESETS)]
    rulesets = stored_rulesets(gh_dir)
    assert rulesets.pop(5) == other
    assert list(rulesets.values()) == [dry_run_payload(gh_dir)]


def test_apply_targets_repo_from_flag(gh_dir: Path) -> None:
    result = run_script(SCRIPT, "--apply", "--repo", TEST_REPO, gh_dir=gh_dir)

    assert result.returncode == 0, result.stderr
    endpoints = [str(call["endpoint"]) for call in gh_calls(gh_dir)]
    assert endpoints
    assert all(endpoint.startswith(f"repos/{TEST_REPO}/") for endpoint in endpoints)
    assert f"Creating ruleset {RULESET_NAME} in {TEST_REPO}" in result.stderr


def test_dry_run_shows_target_repo(gh_dir: Path) -> None:
    result = run_script(SCRIPT, "--repo", TEST_REPO, gh_dir=gh_dir)

    assert result.returncode == 0, result.stderr
    assert f"Target repository: {TEST_REPO}" in result.stderr
    assert LISTING in result.stderr  # the calls --apply would make
    assert gh_calls(gh_dir) == []


@pytest.mark.parametrize("case", INVALID_REPOS)
@pytest.mark.parametrize("mode", [[], ["--apply"]], ids=["dry-run", "apply"])
def test_invalid_repo_exits_without_calling_gh(
    gh_dir: Path, mode: list[str], case: str
) -> None:
    result = run_script(SCRIPT, *mode, "--repo", INVALID_REPOS[case], gh_dir=gh_dir)

    assert result.returncode == 2
    assert "OWNER/NAME" in result.stderr
    assert gh_calls(gh_dir) == []


@pytest.mark.parametrize("form", ORIGINS)
def test_default_repo_comes_from_origin(
    tmp_path: Path, gh_dir: Path, form: str
) -> None:
    script = copy_script_into_git_repo(tmp_path, ORIGINS[form])

    result = run_script(script, gh_dir=gh_dir)

    assert result.returncode == 0, result.stderr
    assert f"Target repository: {TEST_REPO}" in result.stderr
    assert gh_calls(gh_dir) == []


def test_default_repo_rejects_non_github_origin(tmp_path: Path, gh_dir: Path) -> None:
    origin = f"https://gitlab.com/{TEST_REPO}.git"
    script = copy_script_into_git_repo(tmp_path, origin)

    result = run_script(script, "--apply", gh_dir=gh_dir)

    assert result.returncode == 2
    assert "pass --repo" in result.stderr
    assert gh_calls(gh_dir) == []


@pytest.mark.parametrize("case", CLAUDECODE_VALUES)
def test_apply_refuses_inside_claude_code(gh_dir: Path, case: str) -> None:
    result = run_script(
        SCRIPT,
        "--apply",
        "--repo",
        TEST_REPO,
        gh_dir=gh_dir,
        claudecode=CLAUDECODE_VALUES[case],
    )

    assert result.returncode != 0
    assert "CLAUDECODE" in result.stderr
    assert gh_calls(gh_dir) == []


@pytest.mark.parametrize("case", CLAUDECODE_VALUES)
def test_dry_run_works_inside_claude_code(gh_dir: Path, case: str) -> None:
    result = run_script(
        SCRIPT, "--repo", TEST_REPO, gh_dir=gh_dir, claudecode=CLAUDECODE_VALUES[case]
    )

    assert result.returncode == 0, result.stderr
    assert isinstance(json.loads(result.stdout), dict)
    assert gh_calls(gh_dir) == []


# With --apply before it, a parser that ignores the argument would call gh.
@pytest.mark.parametrize("argument", ["--force", "apply", "--repo"])
def test_unknown_argument_exits_with_usage(gh_dir: Path, argument: str) -> None:
    result = run_script(SCRIPT, "--apply", "--repo", TEST_REPO, argument, gh_dir=gh_dir)

    assert result.returncode == 2
    assert "Usage:" in result.stderr
    assert gh_calls(gh_dir) == []


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_help_prints_usage(gh_dir: Path, flag: str) -> None:
    result = run_script(SCRIPT, flag, gh_dir=gh_dir)

    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert gh_calls(gh_dir) == []


def test_apply_stops_when_listing_fails(gh_dir: Path) -> None:
    (gh_dir / "state" / "fail-listing").touch()

    result = run_script(SCRIPT, "--apply", "--repo", TEST_REPO, gh_dir=gh_dir)

    assert result.returncode != 0
    assert call_endpoints(gh_dir) == [("GET", LISTING)]


def test_apply_refuses_duplicate_names(gh_dir: Path) -> None:
    duplicates = {3: {"name": RULESET_NAME}, 4: {"name": RULESET_NAME}}
    seed_rulesets(gh_dir, duplicates)

    result = run_script(SCRIPT, "--apply", "--repo", TEST_REPO, gh_dir=gh_dir)

    assert result.returncode != 0
    assert call_endpoints(gh_dir) == [("GET", LISTING)]
    assert stored_rulesets(gh_dir) == duplicates
