"""CODEOWNERS tests: every protected path in AGENTS.md has a code owner.

AGENTS.md is the single source of truth for the protected paths, and
tests/protected_paths.py parses it. Each protected path needs a CODEOWNERS line
`/<path> @owner…`, and every line that is not blank or a comment has the form
`pattern @owner…`. CODEOWNERS may own more than AGENTS.md lists, such as /eval/
from docs/spec.md.

The checks here and in tests/test_claude_settings.py shrink along with the
AGENTS.md line, so PINNED_PATHS is a lower bound for it: a pinned path that
AGENTS.md drops fails, a path that AGENTS.md adds passes.
"""

import re
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from protected_paths import (
    AGENTS_MD,
    parse_protected_paths,
    protected_paths,
    protected_paths_line,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CODEOWNERS = REPO_ROOT / ".github" / "CODEOWNERS"

# A pattern followed by one or more owners: a user (@name) or a team (@org/team).
ENTRY = re.compile(r"(\S+)(?:\s+@[\w-]+(?:/[\w.-]+)?)+")

# The protected paths before #8 and the ones #8 adds. An issue that removes a
# protected path from AGENTS.md updates this pin on purpose.
PINNED_PATHS = (
    "docs/adr/",
    ".github/",
    "images/**/Dockerfile",
    "uv.lock",
    # Guardrail files.
    "AGENTS.md",
    "CLAUDE.md",
    ".claude/",
    "scripts/set-rulesets.sh",
    # Files that reconfigure or silence gitleaks.
    ".gitleaks.toml",
    ".gitleaksignore",
    ".gitleaks/",
    # Files that enforce a guardrail.
    "tests/protected_paths.py",
    "tests/fake_gh.py",
    "tests/test_claude_settings.py",
    "tests/test_codeowners.py",
    "tests/test_pr_template.py",
    "tests/test_secret_scan.py",
    "tests/test_set_rulesets.py",
    "tests/test_workflow_lint.py",
    "tests/test_workflow_policy.py",
    "tests/test_workflow_triggers.py",
)

UV_LOCK_ENTRY = "/uv.lock @MilanRibel"

CodeownersMutation = Callable[[list[str]], None]
AgentsMutation = Callable[[str], str]


def codeowners_problems(codeowners: str, paths: Sequence[str]) -> list[str]:
    problems: list[str] = []
    owned: set[str] = set()
    for line in codeowners.splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        match = ENTRY.fullmatch(entry)
        if match is None:
            problems.append(f"not `pattern @owner…`: {entry}")
        else:
            owned.add(match.group(1))
    problems += [
        f"no CODEOWNERS entry for protected path {path}"
        for path in paths
        if f"/{path}" not in owned
    ]
    return problems


def pin_problems(paths: Sequence[str]) -> list[str]:
    listed = set(paths)
    return [
        f"AGENTS.md does not list pinned protected path {path}"
        for path in PINNED_PATHS
        if path not in listed
    ]


def replace_entry(old: str, new: str | None) -> CodeownersMutation:
    """Replace a CODEOWNERS line with new; None drops it."""

    def mutate(lines: list[str]) -> None:
        index = lines.index(old)  # raises if the line is not there
        if new is None:
            del lines[index]
        else:
            lines[index] = new

    return mutate


def with_paths(agents_md: str, paths: Sequence[str]) -> str:
    """AGENTS.md with the protected-paths line listing paths instead."""
    line = protected_paths_line(agents_md)
    head = line.partition(":")[0]
    return agents_md.replace(line, f"{head}: {', '.join(paths)}")


def replace_in_line(old: str, new: str) -> AgentsMutation:
    """Replace old, which occurs once on the protected-paths line, with new."""

    def mutate(agents_md: str) -> str:
        line = protected_paths_line(agents_md)
        assert line.count(old) == 1, old
        return agents_md.replace(line, line.replace(old, new))

    return mutate


def drop_line(agents_md: str) -> str:
    return agents_md.replace(protected_paths_line(agents_md) + "\n", "")


def double_line(agents_md: str) -> str:
    return agents_md + protected_paths_line(agents_md) + "\n"


# Each mutation of the real CODEOWNERS, with exactly the problems it must cause.
CODEOWNERS_MUTATIONS: dict[str, tuple[CodeownersMutation, list[str]]] = {
    "/uv.lock line removed": (
        replace_entry(UV_LOCK_ENTRY, None),
        ["no CODEOWNERS entry for protected path uv.lock"],
    ),
    "owner removed from /uv.lock": (
        replace_entry(UV_LOCK_ENTRY, "/uv.lock"),
        [
            "not `pattern @owner…`: /uv.lock",
            "no CODEOWNERS entry for protected path uv.lock",
        ],
    ),
    "uv.lock without leading slash": (
        replace_entry(UV_LOCK_ENTRY, "uv.lock @MilanRibel"),
        ["no CODEOWNERS entry for protected path uv.lock"],
    ),
    "owner without @": (
        replace_entry(UV_LOCK_ENTRY, "/uv.lock MilanRibel"),
        [
            "not `pattern @owner…`: /uv.lock MilanRibel",
            "no CODEOWNERS entry for protected path uv.lock",
        ],
    ),
}

# Each mutation of the real AGENTS.md, with the error the parser must raise.
PARSER_MUTATIONS: dict[str, tuple[AgentsMutation, str]] = {
    "line removed": (drop_line, "AGENTS.md has no protected-paths line"),
    "line listed twice": (double_line, "AGENTS.md has 2 protected-paths lines"),
    "line emptied": (
        lambda agents_md: with_paths(agents_md, []),
        "the protected-paths line in AGENTS.md lists no paths",
    ),
    "path listed twice": (
        lambda agents_md: with_paths(
            agents_md, [*parse_protected_paths(agents_md), "uv.lock"]
        ),
        "protected path uv.lock is listed twice",
    ),
    "comma before uv.lock dropped": (
        replace_in_line(", uv.lock", " uv.lock"),
        "protected path images/**/Dockerfile uv.lock contains whitespace",
    ),
    "path in backticks": (
        replace_in_line("uv.lock", "`uv.lock`"),
        "protected path `uv.lock` contains a backtick",
    ),
    "path with leading slash": (
        replace_in_line("uv.lock", "/uv.lock"),
        "protected path /uv.lock starts with /",
    ),
}


def test_repo_codeowners_covers_protected_paths() -> None:
    assert codeowners_problems(CODEOWNERS.read_text(), protected_paths()) == []


def test_repo_agents_md_keeps_pinned_paths() -> None:
    assert pin_problems(protected_paths()) == []


@pytest.mark.parametrize("name", CODEOWNERS_MUTATIONS)
def test_check_reports_codeowners_mutation(name: str) -> None:
    mutate, problems = CODEOWNERS_MUTATIONS[name]
    lines = CODEOWNERS.read_text().splitlines()
    mutate(lines)

    assert lines != CODEOWNERS.read_text().splitlines()  # really changed something
    assert codeowners_problems("\n".join(lines), protected_paths()) == problems


def test_check_reports_protected_path_without_entry() -> None:
    agents_md = AGENTS_MD.read_text()
    paths = parse_protected_paths(
        with_paths(agents_md, [*parse_protected_paths(agents_md), "pyproject.toml"])
    )

    assert codeowners_problems(CODEOWNERS.read_text(), paths) == [
        "no CODEOWNERS entry for protected path pyproject.toml"
    ]
    assert pin_problems(paths) == []  # an added path passes the pin


@pytest.mark.parametrize("path", PINNED_PATHS)
def test_pin_reports_removed_path(path: str) -> None:
    agents_md = AGENTS_MD.read_text()
    listed = parse_protected_paths(agents_md)
    assert path in listed  # the mutation really removes something
    paths = parse_protected_paths(
        with_paths(agents_md, [kept for kept in listed if kept != path])
    )

    assert pin_problems(paths) == [
        f"AGENTS.md does not list pinned protected path {path}"
    ]
    assert codeowners_problems(CODEOWNERS.read_text(), paths) == []


def test_pin_ignores_order() -> None:
    agents_md = AGENTS_MD.read_text()
    listed = parse_protected_paths(agents_md)
    paths = parse_protected_paths(with_paths(agents_md, listed[::-1]))

    assert paths != listed  # the mutation really changed the order
    assert pin_problems(paths) == []


@pytest.mark.parametrize("name", PARSER_MUTATIONS)
def test_parser_rejects_mutation(name: str) -> None:
    mutate, message = PARSER_MUTATIONS[name]
    agents_md = AGENTS_MD.read_text()
    mutated = mutate(agents_md)

    assert mutated != agents_md  # the mutation really changed something
    with pytest.raises(ValueError, match=f"^{re.escape(message)}$"):
        parse_protected_paths(mutated)
