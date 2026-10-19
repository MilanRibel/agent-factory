"""AGENTS.md tests: every file below tests/ that AGENTS.md mentions exists.

A rule that a test enforces names that test, and the protected-paths line lists
test modules and helpers, all as `tests/<name>.py` paths. A renamed or deleted
file would leave such a reference pointing at nothing, so each one must exist.
AGENTS.md must mention at least one, so the check cannot pass on an empty list.
"""

import re
from collections.abc import Callable
from pathlib import Path

import pytest
from protected_paths import AGENTS_MD

REPO_ROOT = Path(__file__).resolve().parent.parent
# A Python file directly below tests/, such as tests/test_codeowners.py or
# tests/fake_gh.py.
TESTS_PATH = re.compile(r"\btests/\w+\.py\b")

Mutation = Callable[[str], str]


def reference_problems(agents_md: str, repo_root: Path) -> list[str]:
    paths = dict.fromkeys(TESTS_PATH.findall(agents_md))  # unique, in order
    if not paths:
        return ["AGENTS.md mentions no tests/*.py path"]
    return [
        f"AGENTS.md mentions {path}, which does not exist"
        for path in paths
        if not (repo_root / path).is_file()
    ]


def rename(old: str, new: str) -> Mutation:
    """Replace every mention of old with new."""

    def mutate(agents_md: str) -> str:
        return agents_md.replace(old, new)

    return mutate


def drop_paths(agents_md: str) -> str:
    return TESTS_PATH.sub("", agents_md)


# Each mutation of the real AGENTS.md, with exactly the problems it must cause.
MUTATIONS: dict[str, tuple[Mutation, list[str]]] = {
    "test_workflow_policy.py renamed": (
        rename("tests/test_workflow_policy.py", "tests/test_workflow_polcy.py"),
        ["AGENTS.md mentions tests/test_workflow_polcy.py, which does not exist"],
    ),
    "fake_gh.py renamed": (
        rename("tests/fake_gh.py", "tests/fake_hg.py"),
        ["AGENTS.md mentions tests/fake_hg.py, which does not exist"],
    ),
    "every tests/*.py path removed": (
        drop_paths,
        ["AGENTS.md mentions no tests/*.py path"],
    ),
}


def test_repo_agents_md_mentions_existing_files() -> None:
    assert reference_problems(AGENTS_MD.read_text(), REPO_ROOT) == []


@pytest.mark.parametrize("name", MUTATIONS)
def test_check_reports_mutation(name: str) -> None:
    mutate, problems = MUTATIONS[name]
    agents_md = AGENTS_MD.read_text()
    mutated = mutate(agents_md)

    assert mutated != agents_md  # the mutation really changed something
    assert reference_problems(mutated, REPO_ROOT) == problems
