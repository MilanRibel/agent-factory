"""Tool-config override tests: pyproject.toml stays the only config for the tools.

ruff, pyright, pytest and uv read other files before or instead of their table in
pyproject.toml. tests/test_tooling.py passes the config explicitly, so it proves
what pyproject.toml says, not what CI runs. This guard fails when such a file, or
a pyproject.toml below the root, is tracked or would be added, and when it cannot
trust the `git ls-files` listing. #31 makes this file a protected path, so
relaxing the check needs an issue.

Not covered: conftest.py hooks, inline comments that silence a line (`# noqa`,
`# type: ignore`, `# pyright: ignore`) and file-level comments that silence a
file (`# ruff: noqa`, `# pyright: basic`, `# pyright: <rule>=false`).
"""

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path, PurePosixPath

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Files that replace a tool's table in pyproject.toml for their directory and below.
TOOL_CONFIG_OVERRIDES = (
    # Read by ruff; in one directory both win over pyproject.toml.
    "ruff.toml",
    ".ruff.toml",
    # Read by pyright at the project root instead of [tool.pyright].
    "pyrightconfig.json",
    # Read by pytest 9 instead of [tool.pytest.ini_options], even when empty.
    "pytest.toml",
    ".pytest.toml",
    "pytest.ini",
    ".pytest.ini",
    # Read by uv instead of [tool.uv]. This precedence comes from the uv docs
    # (https://docs.astral.sh/uv/concepts/configuration-files/) and is not tested.
    "uv.toml",
)

Setup = Callable[[Path], tuple[Path, dict[str, str]]]


def tool_config_override_problems(
    root: Path, env: Mapping[str, str] | None = None
) -> list[str]:
    """The override files git tracks or would add below root, at any depth."""
    env = os.environ if env is None else env
    git = shutil.which("git", path=env.get("PATH", ""))
    if git is None:
        return ["git is not on PATH"]
    # Resolved binary and fixed arguments; no shell, no untrusted input.
    result = subprocess.run(  # noqa: S603
        [git, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        env=dict(env),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return [f"git ls-files failed with exit code {result.returncode}"]
    paths = list(dict.fromkeys(path for path in result.stdout.split("\0") if path))
    if not paths:
        return ["git ls-files listed no files"]
    return [
        path
        for path in paths
        if PurePosixPath(path).name in TOOL_CONFIG_OVERRIDES
        or (PurePosixPath(path).name == "pyproject.toml" and path != "pyproject.toml")
    ]


def scratch_env(tmp_path: Path) -> dict[str, str]:
    # Keep the user's git config (hooks, signing) out of the scratch repos, and
    # keep git from finding a repository above tmp_path.
    return {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CEILING_DIRECTORIES": str(tmp_path),
        "GIT_AUTHOR_NAME": "Example",
        "GIT_AUTHOR_EMAIL": "example@example.com",
        "GIT_COMMITTER_NAME": "Example",
        "GIT_COMMITTER_EMAIL": "example@example.com",
    }


def git(cwd: Path, env: dict[str, str], *args: str) -> None:
    binary = shutil.which("git")
    assert binary is not None
    # Resolved binary and fixed arguments; no shell, no untrusted input.
    subprocess.run(  # noqa: S603
        [binary, *args], cwd=cwd, env=env, capture_output=True, text=True, check=True
    )


def commit(repo: Path, env: dict[str, str], *paths: str) -> None:
    git(repo, env, "add", "--", *paths)
    git(repo, env, "commit", "--quiet", "--message", "example")


def scratch_repo(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A git repository with a committed root pyproject.toml."""
    repo, env = tmp_path / "repo", scratch_env(tmp_path)
    repo.mkdir()
    git(repo, env, "init", "--quiet")
    (repo / "pyproject.toml").write_text('[project]\nname = "example"\n')
    commit(repo, env, "pyproject.toml")
    return repo, env


def test_repo_has_no_tool_config_overrides() -> None:
    assert tool_config_override_problems(REPO_ROOT) == []


@pytest.mark.parametrize("committed_in_src", [False, True], ids=["root", "src"])
@pytest.mark.parametrize("name", TOOL_CONFIG_OVERRIDES)
def test_check_reports_tool_config_override(
    tmp_path: Path, name: str, committed_in_src: bool
) -> None:
    repo, env = scratch_repo(tmp_path)
    path = f"src/{name}" if committed_in_src else name
    (repo / path).parent.mkdir(exist_ok=True)
    (repo / path).write_text("")
    if committed_in_src:
        commit(repo, env, path)

    assert tool_config_override_problems(repo, env) == [path]


def test_check_reports_nested_pyproject(tmp_path: Path) -> None:
    repo, env = scratch_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "pyproject.toml").write_text('[tool.ruff.lint]\nselect = ["E"]\n')
    commit(repo, env, "src/pyproject.toml")

    assert tool_config_override_problems(repo, env) == ["src/pyproject.toml"]


def not_a_repository(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    root = tmp_path / "plain"
    root.mkdir()
    (root / "ruff.toml").write_text("")
    return root, scratch_env(tmp_path)


def empty_repository(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo, env = tmp_path / "repo", scratch_env(tmp_path)
    repo.mkdir()
    git(repo, env, "init", "--quiet")
    return repo, env


def git_not_on_path(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo, env = scratch_repo(tmp_path)
    empty = tmp_path / "empty-path"
    empty.mkdir()
    return repo, {**env, "PATH": str(empty)}


# Each listing the check cannot trust, with exactly the problem it must cause.
UNTRUSTED_LISTINGS: dict[str, tuple[Setup, str]] = {
    "not a git repository": (
        not_a_repository,
        "git ls-files failed with exit code 128",
    ),
    "empty git repository": (empty_repository, "git ls-files listed no files"),
    "git not on PATH": (git_not_on_path, "git is not on PATH"),
}


@pytest.mark.parametrize("name", UNTRUSTED_LISTINGS)
def test_check_reports_untrusted_listing(tmp_path: Path, name: str) -> None:
    setup, problem = UNTRUSTED_LISTINGS[name]
    root, env = setup(tmp_path)

    assert tool_config_override_problems(root, env) == [problem]
