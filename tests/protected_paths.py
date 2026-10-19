"""The protected paths from AGENTS.md, the single source of truth for the tests.

AGENTS.md lists them on one line: `- Protected paths (...): path, path, ...`.
A directory ends with "/". A path is relative to the repository root, so it
does not start with "/", and it holds no whitespace or backtick. The parser
rejects a missing, doubled or empty line, so no check runs on an empty list.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_MD = REPO_ROOT / "AGENTS.md"
LINE_PREFIX = "- Protected paths"


def protected_paths_line(agents_md: str) -> str:
    lines = [line for line in agents_md.splitlines() if line.startswith(LINE_PREFIX)]
    if not lines:
        raise ValueError("AGENTS.md has no protected-paths line")
    if len(lines) > 1:
        raise ValueError(f"AGENTS.md has {len(lines)} protected-paths lines")
    return lines[0]


def parse_protected_paths(agents_md: str) -> tuple[str, ...]:
    listed = protected_paths_line(agents_md).partition(":")[2]
    paths = tuple(path.strip() for path in listed.split(",") if path.strip())
    if not paths:
        raise ValueError("the protected-paths line in AGENTS.md lists no paths")
    for index, path in enumerate(paths):
        if path in paths[:index]:
            raise ValueError(f"protected path {path} is listed twice")
        if any(char.isspace() for char in path):
            raise ValueError(f"protected path {path} contains whitespace")
        if "`" in path:
            raise ValueError(f"protected path {path} contains a backtick")
        if path.startswith("/"):
            raise ValueError(f"protected path {path} starts with /")
    return paths


def protected_paths() -> tuple[str, ...]:
    return parse_protected_paths(AGENTS_MD.read_text())
