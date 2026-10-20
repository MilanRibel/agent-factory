"""pre-commit config tests: every hook repo is pinned, and gitleaks matches CI.

.pre-commit-config.yaml is a convenience and deliberately not a protected path;
CI stays the gate. This test is protected (#9), so a weaker config still fails
here. Every `rev:` is a full 40-hex commit SHA with a tag comment. The gitleaks
hook pins the tag of GITLEAKS_VERSION in ci.yml and runs with the flags of the
secret-scan job. A pinned SHA proves the same commit, not that it is a good one.
"""

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
GITLEAKS_REPO = "https://github.com/gitleaks/gitleaks"
CI_FLAGS = ("--redact", "--ignore-gitleaks-allow")

# Repos that pre-commit does not fetch, so they have no rev.
UNFETCHED_REPOS = ("local", "meta")

SHA = re.compile(r"[0-9a-f]{40}")
# yaml drops comments, so the tag comment is read from the lines.
REPO_LINE = re.compile(r"^\s*-\s*repo:\s*(\S+)")
REV_LINE = re.compile(r"^\s*rev:\s*\S+\s*#\s*(\S+)")


def ci_gitleaks_version() -> str:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text())
    return str(workflow["env"]["GITLEAKS_VERSION"])


def ci_gitleaks_flags() -> set[str]:
    """Flags passed to `gitleaks git` in the secret-scan job."""
    workflow = yaml.safe_load(CI_WORKFLOW.read_text())
    steps: list[dict[str, Any]] = workflow["jobs"]["secret-scan"]["steps"]
    return {
        word
        for step in steps
        for line in step.get("run", "").splitlines()
        if line.split()[:2] == ["gitleaks", "git"]
        for word in line.split()[2:]
    }


def tag_comments(text: str) -> dict[str, str]:
    """The tag comment on the rev line of each repo."""
    tags: dict[str, str] = {}
    repo = None
    for line in text.splitlines():
        if match := REPO_LINE.match(line):
            repo = match.group(1)
        elif (match := REV_LINE.match(line)) and repo is not None:
            tags[repo] = match.group(1)
    return tags


def config_problems(text: str, gitleaks_version: str) -> list[str]:
    config = yaml.safe_load(text)
    tags = tag_comments(text)
    problems: list[str] = []
    for entry in config["repos"]:
        repo = entry["repo"]
        if repo in UNFETCHED_REPOS:
            continue
        rev = str(entry.get("rev"))
        if not SHA.fullmatch(rev):
            problems.append(f"{repo}: rev {rev} is not a 40-hex commit SHA")
        elif repo not in tags:
            problems.append(f"{repo}: rev has no tag comment")
        elif repo == GITLEAKS_REPO and tags[repo] != f"v{gitleaks_version}":
            problems.append(
                f"{repo}: tag {tags[repo]} is not v{gitleaks_version} from ci.yml"
            )
        if repo != GITLEAKS_REPO:
            continue
        for hook in entry["hooks"]:
            for flag in CI_FLAGS:
                if flag not in hook.get("args", []):
                    problems.append(f"gitleaks hook {hook['id']}: no {flag}")
    return problems


def mutated(pattern: str, replacement: str) -> str:
    """The repo config with the first match of pattern replaced."""
    text, count = re.subn(pattern, replacement, CONFIG.read_text(), count=1)
    assert count == 1, f"{pattern!r} does not occur in the config"
    return text


def test_repo_config_has_no_problems() -> None:
    assert config_problems(CONFIG.read_text(), ci_gitleaks_version()) == []


def test_gitleaks_hook_uses_the_ci_flags() -> None:
    assert set(CI_FLAGS) <= ci_gitleaks_flags()
    config = yaml.safe_load(CONFIG.read_text())
    hooks = [
        hook
        for entry in config["repos"]
        if entry["repo"] == GITLEAKS_REPO
        for hook in entry["hooks"]
    ]
    assert hooks, f"{CONFIG.name} has no hook from {GITLEAKS_REPO}"
    for hook in hooks:
        assert set(CI_FLAGS) <= set(hook.get("args", []))


def test_rev_with_a_tag_fails() -> None:
    text = mutated(r"rev: .*", "rev: v1.0.0")
    repo = yaml.safe_load(text)["repos"][0]["repo"]

    assert config_problems(text, ci_gitleaks_version()) == [
        f"{repo}: rev v1.0.0 is not a 40-hex commit SHA"
    ]


def test_rev_without_a_tag_comment_fails() -> None:
    text = mutated(r"(rev: \S+)\s*#.*", r"\1")
    repo = yaml.safe_load(text)["repos"][0]["repo"]

    assert config_problems(text, ci_gitleaks_version()) == [
        f"{repo}: rev has no tag comment"
    ]


def test_gitleaks_tag_other_than_ci_fails() -> None:
    version = ci_gitleaks_version()
    text = mutated(rf"# v{re.escape(version)}\b", "# v0.0.1")

    assert config_problems(text, version) == [
        f"{GITLEAKS_REPO}: tag v0.0.1 is not v{version} from ci.yml"
    ]


def test_gitleaks_hook_without_redact_fails() -> None:
    text = mutated(r"--redact, ", "")

    assert config_problems(text, ci_gitleaks_version()) == [
        "gitleaks hook gitleaks: no --redact"
    ]


def test_gitleaks_hook_without_ignore_gitleaks_allow_fails() -> None:
    text = mutated(r", --ignore-gitleaks-allow", "")

    assert config_problems(text, ci_gitleaks_version()) == [
        "gitleaks hook gitleaks: no --ignore-gitleaks-allow"
    ]
