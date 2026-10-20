"""ADR format tests: every architecture decision record has the same form.

docs/adr/ holds the template 000-template.md and the ADRs, each named
NNN-kebab-case.md, and nothing else, not even a subdirectory. The template and
every ADR start with the heading `# ADR-NNN: Title` and the lines
`- Status: <value>` and `- Date: YYYY-MM-DD`. Only blank lines follow before the
sections Context, Decision, Consequences and Alternatives considered, which come
in that order, none of them empty.

The template keeps ADR-NNN, <value> and YYYY-MM-DD as placeholders, so only an
ADR is held to these rules:
- the number in the title matches the filename, no two ADRs share a number, and
  number 000 is reserved for the template;
- the status is one of STATUSES, and `Superseded by ADR-NNN` names an existing
  ADR other than the template;
- the date has the form YYYY-MM-DD and date.fromisoformat accepts it. On
  Python 3.12 that function alone also accepts 20261019 and 2026-W42-1.

The how-to in the template lists the same statuses as STATUSES.
"""

import re
import shutil
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ADR_DIR = "docs/adr"
TEMPLATE_NAME = "000-template.md"
TEMPLATE = REPO_ROOT / ADR_DIR / TEMPLATE_NAME

FILENAME = re.compile(r"(\d{3})-[a-z0-9]+(?:-[a-z0-9]+)*\.md")
# The heading, the status line and the date line, before the first section.
HEADER = (
    re.compile(r"# ADR-(\S+): \S.*"),
    re.compile(r"- Status: (.+)"),
    re.compile(r"- Date: (.+)"),
)
# Every status an ADR may have; NNN stands for the number of another ADR.
STATUSES = ("Proposed", "Accepted", "Deprecated", "Superseded by ADR-NNN")
STATUS = re.compile(
    "|".join(re.escape(status).replace("NNN", r"(\d{3})") for status in STATUSES)
)
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
SECTIONS = ("Context", "Decision", "Consequences", "Alternatives considered")
# The line of the how-to in the template that lists the statuses in backticks.
STATUS_VALUES = "Status values: "

# A valid ADR, the 001-example.md of the fixture.
EXAMPLE_ADR = """\
# ADR-001: Example

- Status: Accepted
- Date: 2026-10-19

## Context

Why a decision is needed.

## Decision

What was decided.

## Consequences

What follows from it.

## Alternatives considered

What else was weighed.
"""
# Each placeholder line of the template, filled in.
FILLED_IN = {
    "# ADR-NNN: Title": "# ADR-001: Title",
    "- Status: <value>": "- Status: Proposed",
    "- Date: YYYY-MM-DD": "- Date: 2026-10-20",
}

Mutation = Callable[[Path], None]  # changes the files in a docs/adr/


def is_date(text: str) -> bool:
    if DATE.fullmatch(text) is None:
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def split(text: str) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """The non-blank lines before the first section, and each section's lines."""
    header: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        if line.startswith("## "):
            sections.append((line.removeprefix("## "), []))
        elif sections:
            sections[-1][1].append(line)
        elif line.strip():
            header.append(line)
    return header, sections


def status_problems(name: str, status: str, numbers: set[str]) -> list[str]:
    match = STATUS.fullmatch(status)
    if match is None:
        return [f"{name}: status {status} is not one of {', '.join(STATUSES)}"]
    superseded_by = match[1]  # None unless the status is `Superseded by ADR-NNN`
    if superseded_by == "000":
        return [f"{name}: status names ADR-000, the template"]
    if superseded_by is not None and superseded_by not in numbers:
        return [f"{name}: status names ADR-{superseded_by}, which does not exist"]
    return []


def file_problems(
    name: str, text: str, number: str | None, numbers: set[str]
) -> list[str]:
    """The problems of the template (number None) or of the ADR with number.

    numbers holds the number of every ADR in docs/adr/.
    """
    header, sections = split(text)
    values = [
        match[1]
        for pattern, line in zip(HEADER, header, strict=False)
        if (match := pattern.fullmatch(line))
    ]
    problems: list[str] = []
    if len(values) != len(HEADER):
        problems.append(
            f"{name}: does not start with `# ADR-NNN: Title`, `- Status: <value>` "
            "and `- Date: YYYY-MM-DD`"
        )
    else:
        if len(header) > len(HEADER):
            problems.append(
                f"{name}: has text between the date line and the first section"
            )
        if number is not None:
            title_number, status, day = values
            if title_number != number:
                problems.append(
                    f"{name}: title number {title_number} does not match the filename"
                )
            problems += status_problems(name, status, numbers)
            if not is_date(day):
                problems.append(f"{name}: date {day} is not a valid YYYY-MM-DD date")
    titles = [title for title, _ in sections]
    if titles != list(SECTIONS):
        problems.append(
            f"{name}: sections are {', '.join(titles)}; expected {', '.join(SECTIONS)}"
        )
    problems += [
        f"{name}: section {title} is empty"
        for title, lines in sections
        if not any(line.strip() for line in lines)
    ]
    return problems


def adr_problems(root: Path) -> list[str]:
    adr_dir = root / ADR_DIR
    if not adr_dir.is_dir():
        return [f"{ADR_DIR}/ does not exist"]
    files = sorted(path for path in adr_dir.rglob("*") if path.is_file())
    if not files:
        return [f"{ADR_DIR}/ has no files"]
    template = adr_dir / TEMPLATE_NAME
    if not template.is_file():
        return [f"{ADR_DIR}/{TEMPLATE_NAME} is missing"]

    problems: list[str] = []
    adrs: dict[Path, str] = {}  # each ADR and its number
    first: dict[str, str] = {}  # each number other than 000 and the first ADR with it
    for path in files:
        name = path.relative_to(root).as_posix()
        match = FILENAME.fullmatch(path.name)
        if path.parent != adr_dir:
            problems.append(f"{name} is in a subdirectory of {ADR_DIR}/")
        elif match is None:
            problems.append(f"{name} is not named NNN-kebab-case.md")
        elif path != template:
            number = match[1]
            adrs[path] = number
            if number == "000":
                problems.append(f"{name}: number 000 is reserved for the template")
            elif number in first:
                problems.append(
                    f"{name}: number {number} is also used by {first[number]}"
                )
            else:
                first[number] = name
    for path, number in [(template, None), *adrs.items()]:
        name = path.relative_to(root).as_posix()
        problems += file_problems(name, path.read_text(), number, set(first))
    return problems


def write_fixture(root: Path) -> Path:
    """docs/adr/ below root, with a copy of the real template and 001-example.md."""
    adr_dir = root / ADR_DIR
    adr_dir.mkdir(parents=True)
    shutil.copyfile(TEMPLATE, adr_dir / TEMPLATE_NAME)
    (adr_dir / "001-example.md").write_text(EXAMPLE_ADR)
    return adr_dir


def example(number: str, title: str) -> str:
    """A valid ADR with that number and title."""
    return EXAMPLE_ADR.replace("# ADR-001: Example", f"# ADR-{number}: {title}")


def replace(name: str, old: str, new: str) -> Mutation:
    """Replace old, which occurs once in the file name, with new."""

    def mutate(adr_dir: Path) -> None:
        path = adr_dir / name
        text = path.read_text()
        assert text.count(old) == 1, old
        path.write_text(text.replace(old, new))

    return mutate


def add(name: str, text: str) -> Mutation:
    """Add the file name, which does not exist yet."""

    def mutate(adr_dir: Path) -> None:
        path = adr_dir / name
        assert not path.exists(), name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    return mutate


def template_missing(root: Path) -> None:
    adr_dir = root / ADR_DIR
    adr_dir.mkdir(parents=True)
    (adr_dir / "001-example.md").write_text(EXAMPLE_ADR)


def empty_adr_dir(root: Path) -> None:
    (root / ADR_DIR).mkdir(parents=True)


# Each mutation of the fixture, with the one problem it must cause.
MUTATIONS: dict[str, tuple[Mutation, str]] = {
    "## Decision removed": (
        replace("001-example.md", "## Decision\n\n", ""),
        "docs/adr/001-example.md: sections are Context, Consequences, "
        "Alternatives considered; expected Context, Decision, Consequences, "
        "Alternatives considered",
    ),
    "## Decision removed from the template": (
        replace(TEMPLATE_NAME, "## Decision\n", ""),
        "docs/adr/000-template.md: sections are Context, Consequences, "
        "Alternatives considered; expected Context, Decision, Consequences, "
        "Alternatives considered",
    ),
    "line between the date line and ## Context": (
        replace("001-example.md", "## Context\n", "Extra line.\n\n## Context\n"),
        "docs/adr/001-example.md: has text between the date line and the first section",
    ),
    "## Decision and ## Consequences swapped": (
        replace(
            "001-example.md",
            "## Decision\n\nWhat was decided.\n\n"
            "## Consequences\n\nWhat follows from it.\n",
            "## Consequences\n\nWhat follows from it.\n\n"
            "## Decision\n\nWhat was decided.\n",
        ),
        "docs/adr/001-example.md: sections are Context, Consequences, Decision, "
        "Alternatives considered; expected Context, Decision, Consequences, "
        "Alternatives considered",
    ),
    "section emptied": (
        replace("001-example.md", "What follows from it.\n", ""),
        "docs/adr/001-example.md: section Consequences is empty",
    ),
    "invalid status": (
        replace("001-example.md", "- Status: Accepted", "- Status: Done"),
        "docs/adr/001-example.md: status Done is not one of Proposed, Accepted, "
        "Deprecated, Superseded by ADR-NNN",
    ),
    "superseded by a missing ADR": (
        replace(
            "001-example.md", "- Status: Accepted", "- Status: Superseded by ADR-009"
        ),
        "docs/adr/001-example.md: status names ADR-009, which does not exist",
    ),
    "superseded by the template": (
        replace(
            "001-example.md", "- Status: Accepted", "- Status: Superseded by ADR-000"
        ),
        "docs/adr/001-example.md: status names ADR-000, the template",
    ),
    "number used twice": (
        add("001-other.md", example("001", "Other")),
        "docs/adr/001-other.md: number 001 is also used by docs/adr/001-example.md",
    ),
    "title number differs from the filename": (
        replace("001-example.md", "# ADR-001:", "# ADR-002:"),
        "docs/adr/001-example.md: title number 002 does not match the filename",
    ),
    "invalid date": (
        replace("001-example.md", "- Date: 2026-10-19", "- Date: 2026-02-30"),
        "docs/adr/001-example.md: date 2026-02-30 is not a valid YYYY-MM-DD date",
    ),
    "date without hyphens": (
        replace("001-example.md", "- Date: 2026-10-19", "- Date: 20261019"),
        "docs/adr/001-example.md: date 20261019 is not a valid YYYY-MM-DD date",
    ),
    "week date": (
        replace("001-example.md", "- Date: 2026-10-19", "- Date: 2026-W42-1"),
        "docs/adr/001-example.md: date 2026-W42-1 is not a valid YYYY-MM-DD date",
    ),
    "stray file": (
        add("notes.md", "Notes.\n"),
        "docs/adr/notes.md is not named NNN-kebab-case.md",
    ),
    "ADR in a subdirectory": (
        add("drafts/002-x.md", example("002", "X")),
        "docs/adr/drafts/002-x.md is in a subdirectory of docs/adr/",
    ),
    "ADR with number 000": (
        add("000-example.md", example("000", "Example")),
        "docs/adr/000-example.md: number 000 is reserved for the template",
    ),
}

# Each docs/adr/ built without the template, with the one problem it must cause.
BROKEN_DIRS: dict[str, tuple[Callable[[Path], None], str]] = {
    "only 001-example.md": (template_missing, "docs/adr/000-template.md is missing"),
    "no docs/adr/": (lambda root: None, "docs/adr/ does not exist"),
    "empty docs/adr/": (empty_adr_dir, "docs/adr/ has no files"),
}


def test_repo_adrs_follow_format() -> None:
    assert adr_problems(REPO_ROOT) == []


def test_check_accepts_fixture(tmp_path: Path) -> None:
    write_fixture(tmp_path)

    assert adr_problems(tmp_path) == []


def test_check_accepts_superseded_adr(tmp_path: Path) -> None:
    adr_dir = write_fixture(tmp_path)
    replace("001-example.md", "- Status: Accepted", "- Status: Superseded by ADR-002")(
        adr_dir
    )
    add("002-example.md", example("002", "Example"))(adr_dir)

    assert adr_problems(tmp_path) == []


def test_check_accepts_filled_in_template(tmp_path: Path) -> None:
    adr_dir = write_fixture(tmp_path)
    shutil.copyfile(TEMPLATE, adr_dir / "001-example.md")
    for placeholder, value in FILLED_IN.items():
        replace("001-example.md", placeholder, value)(adr_dir)

    assert adr_problems(tmp_path) == []


def test_template_how_to_lists_the_statuses() -> None:
    lines = [
        line
        for line in TEMPLATE.read_text().splitlines()
        if line.startswith(STATUS_VALUES)
    ]
    assert len(lines) == 1, lines
    # Every value as written, `Superseded by ADR-NNN` too: STATUS is built from
    # STATUSES, so the how-to and the check hold the same pattern.
    listed = set(re.findall(r"`([^`]+)`", lines[0]))

    assert sorted(listed - set(STATUSES)) == []  # in the how-to, rejected by the check
    assert sorted(set(STATUSES) - listed) == []  # accepted by the check, not listed


@pytest.mark.parametrize("name", MUTATIONS)
def test_check_reports_mutation(tmp_path: Path, name: str) -> None:
    mutate, problem = MUTATIONS[name]
    mutate(write_fixture(tmp_path))

    assert adr_problems(tmp_path) == [problem]


@pytest.mark.parametrize("name", BROKEN_DIRS)
def test_check_reports_broken_dir(tmp_path: Path, name: str) -> None:
    build, problem = BROKEN_DIRS[name]
    build(tmp_path)

    assert adr_problems(tmp_path) == [problem]
