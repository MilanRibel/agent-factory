"""Threat model tests: docs/threat-model.md keeps the structure from #11.

The threat model is a living document that every phase adds to, so it is not a
protected path; this test guards its structure instead:
- the `## ` sections are SECTIONS, each once, in that order;
- `## Trust boundaries` holds a mermaid diagram that names each of BOUNDARIES;
- `## Threats` holds a table with COLUMNS and at least one row. Each row has a
  T-NNN ID that no other row uses, one of BOUNDARIES, a mitigation, a phase from
  0 to 11 and one of STATUSES;
- the honesty rule: a done or partial mitigation names what implements it, a path
  in backticks that is not a .md file or an issue or PR number, and every path it
  names exists, as in tests/test_agents_md.py. A .md file describes a rule but
  does not enforce it;
- `## Residual risks` holds at least one bullet, every bullet names a path or a
  number, and every .md file a bullet names exists. Other paths may name a file
  that must not exist, such as a tool-config override file.

The how-to above the table lists the same statuses as STATUSES.
"""

import re
from collections.abc import Callable
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
THREAT_MODEL = REPO_ROOT / "docs" / "threat-model.md"

SECTIONS = (
    "Scope and assumptions",
    "Assets",
    "Actors and entry points",
    "Trust boundaries",
    "Threats",
    "Residual risks",
)
COLUMNS = ("ID", "Threat", "Boundary", "Mitigation", "Phase", "Status")
# The diagram and the Boundary column take their boundaries from this one list.
BOUNDARIES = (
    "host",
    "orchestrator",
    "role containers",
    "egress proxy",
    "GitHub",
    "Anthropic API",
)
STATUSES = ("done", "partial", "planned")
PHASES = tuple(str(phase) for phase in range(12))
THREAT_ID = re.compile(r"T-\d{3}")
SEPARATOR = re.compile(r"\|(?:\s*:?-+:?\s*\|)+")
CELL_BORDER = re.compile(r"(?<!\\)\|")
CODE_SPAN = re.compile(r"`([^`]*)`")
# A repo path: letters, digits, _, -, . and /, with a / or a file extension.
PATH = re.compile(r"[\w.-]+(?:/[\w.-]*)*")
EXTENSION = re.compile(r"\.[A-Za-z]+$")
ISSUE = re.compile(r"#\d+\b")
MERMAID = re.compile(r"^```mermaid\n(.*?)^```", re.MULTILINE | re.DOTALL)
# The line of the how-to in `## Threats` that lists the statuses in backticks.
STATUS_VALUES = "Status values: "

Mutation = Callable[[str], str]


def sections(text: str) -> dict[str, str]:
    """The body of each `## ` section, by heading; a later duplicate wins."""
    bodies: dict[str, str] = {}
    heading = None
    for line in text.splitlines(keepends=True):
        if line.startswith("## "):
            heading = line[3:].strip()
            bodies[heading] = ""
        elif heading is not None:
            bodies[heading] += line
    return bodies


def cells(line: str) -> list[str]:
    return [cell.strip() for cell in CELL_BORDER.split(line.strip())[1:-1]]


def path_references(text: str) -> list[str]:
    return [
        span
        for span in CODE_SPAN.findall(text)
        if PATH.fullmatch(span) and ("/" in span or EXTENSION.search(span))
    ]


def section_problems(text: str) -> list[str]:
    headings = [
        line[3:].strip() for line in text.splitlines() if line.startswith("## ")
    ]
    problems = [f"no section `## {name}`" for name in SECTIONS if name not in headings]
    problems += [
        f"unexpected section `## {name}`" for name in headings if name not in SECTIONS
    ]
    if not problems and headings != list(SECTIONS):
        problems.append(f"the sections are not, each once: {', '.join(SECTIONS)}")
    return problems


def row_problems(number: int, row: list[str], repo_root: Path) -> list[str]:
    if len(row) != len(COLUMNS):
        return [f"threat row {number} has {len(row)} cells, not {len(COLUMNS)}"]
    threat_id, _, boundary, mitigation, phase, status = row
    name = f"threat row {number} ({threat_id})"
    problems: list[str] = []
    if not THREAT_ID.fullmatch(threat_id):
        problems.append(f"{name}: the ID is not T-NNN")
    if boundary.casefold() not in [known.casefold() for known in BOUNDARIES]:
        problems.append(f"{name}: boundary {boundary!r} is not one of the six")
    if not mitigation:
        problems.append(f"{name} has no mitigation")
    if phase not in PHASES:
        problems.append(f"{name}: phase {phase!r} is not 0 to 11")
    if status not in STATUSES:
        problems.append(
            f"{name}: status {status!r} is not one of {', '.join(STATUSES)}"
        )
    elif status != "planned" and mitigation:
        paths = path_references(mitigation)
        # A .md file describes a rule; it does not implement one.
        mechanisms = [path for path in paths if not path.endswith(".md")]
        if not mechanisms and not ISSUE.search(mitigation):
            problems.append(
                f"{name} is {status} but names no path other than a .md file"
                " and no issue or PR number"
            )
        problems += [
            f"{name} names {path}, which does not exist"
            for path in paths
            if not (repo_root / path).exists()
        ]
    return problems


def table_problems(threats: str, repo_root: Path) -> list[str]:
    table = [line for line in threats.splitlines() if line.startswith("|")]
    if (
        len(table) < 2
        or cells(table[0]) != list(COLUMNS)
        or not SEPARATOR.fullmatch(table[1].strip())
    ):
        return [f"`## Threats` has no table with the columns {', '.join(COLUMNS)}"]
    rows = table[2:]
    if not rows:
        return ["the threat table has no rows"]
    problems: list[str] = []
    seen: set[str] = set()
    for number, line in enumerate(rows, 1):
        row = cells(line)
        problems += row_problems(number, row, repo_root)
        if row and row[0] in seen:
            problems.append(f"threat row {number}: ID {row[0]} is already used")
        seen.add(row[0] if row else "")
    return problems


def diagram_problems(boundaries: str) -> list[str]:
    diagrams = "".join(MERMAID.findall(boundaries))
    if not diagrams:
        return ["`## Trust boundaries` has no mermaid diagram"]
    return [
        f"the mermaid diagram does not name {boundary}"
        for boundary in BOUNDARIES
        if not re.search(rf"\b{re.escape(boundary)}\b", diagrams, re.IGNORECASE)
    ]


def bullets(body: str) -> list[str]:
    """Each `- ` bullet with the indented lines below it."""
    items: list[str] = []
    for line in body.splitlines():
        if line.startswith("- "):
            items.append(line)
        elif items and line.startswith((" ", "\t")):
            items[-1] += "\n" + line
    return items


def residual_risk_problems(residual: str, repo_root: Path) -> list[str]:
    risks = bullets(residual)
    if not risks:
        return ["`## Residual risks` has no bullets"]
    problems: list[str] = []
    for number, risk in enumerate(risks, 1):
        paths = path_references(risk)
        if not paths and not ISSUE.search(risk):
            problems.append(f"residual risk {number} names no path or number")
        # Only .md sources must exist: a risk may name a file that must not exist,
        # such as a tool-config override file.
        problems += [
            f"residual risk {number} names {path}, which does not exist"
            for path in paths
            if path.endswith(".md") and not (repo_root / path).exists()
        ]
    return problems


def threat_model_problems(text: str, repo_root: Path) -> list[str]:
    problems = section_problems(text)
    bodies = sections(text)
    if "Trust boundaries" in bodies:
        problems += diagram_problems(bodies["Trust boundaries"])
    if "Threats" in bodies:
        problems += table_problems(bodies["Threats"], repo_root)
    if "Residual risks" in bodies:
        problems += residual_risk_problems(bodies["Residual risks"], repo_root)
    return problems


def table_lines(text: str) -> list[str]:
    threats = sections(text)["Threats"]
    return [line for line in threats.splitlines() if line.startswith("|")]


def append_row(row: str) -> Mutation:
    """Add row after the last line of the threat table."""

    def mutate(text: str) -> str:
        last = table_lines(text)[-1]
        assert text.count(last + "\n") == 1, last
        return text.replace(last + "\n", f"{last}\n{row}\n")

    return mutate


def first_id(text: str) -> str:
    return cells(table_lines(text)[2])[0]


def duplicate_first_id(text: str) -> str:
    return append_row(f"| {first_id(text)} | x | host | Fixed in #11. | 0 | done |")(
        text
    )


def drop_rows(text: str) -> str:
    for line in table_lines(text)[2:]:
        text = text.replace(line + "\n", "")
    return text


def swap_header(text: str) -> str:
    header = table_lines(text)[0]
    return text.replace(
        header, "| ID | Threat | Boundary | Mitigation | Status | Phase |"
    )


def drop_heading(name: str) -> Mutation:
    def mutate(text: str) -> str:
        return text.replace(f"## {name}\n", "")

    return mutate


def swap_headings(first: str, second: str) -> Mutation:
    def mutate(text: str) -> str:
        return (
            text.replace(f"## {first}\n", "\0")
            .replace(f"## {second}\n", f"## {first}\n")
            .replace("\0", f"## {second}\n")
        )

    return mutate


def add_section(text: str) -> str:
    return text + "\n## Notes\n\nA note.\n"


def unfence_diagram(text: str) -> str:
    return text.replace("```mermaid\n", "```text\n")


def rename_in_diagram(old: str, new: str) -> Mutation:
    def mutate(text: str) -> str:
        diagram = MERMAID.search(text)
        assert diagram is not None
        block = re.sub(re.escape(old), new, diagram.group(1), flags=re.IGNORECASE)
        return text.replace(diagram.group(1), block)

    return mutate


def drop_residual_risks(text: str) -> str:
    for risk in bullets(sections(text)["Residual risks"]):
        assert text.count(risk + "\n") == 1, risk
        text = text.replace(risk + "\n", "")
    return text


def add_residual_risk(risk: str) -> Mutation:
    """Add a bullet at the end of `## Residual risks`, the last section."""

    def mutate(text: str) -> str:
        return f"{text}- {risk}\n"

    return mutate


ROW = (
    "| {threat_id} | Fixture threat | {boundary} | {mitigation} | {phase} | {status} |"
)


def row(
    mitigation: str = "Checked by `tests/test_threat_model.py`.",
    phase: str = "0",
    status: str = "done",
    threat_id: str = "T-999",
    boundary: str = "host",
) -> str:
    """The valid fixture row from the issue, with one cell changed."""
    return ROW.format(
        threat_id=threat_id,
        boundary=boundary,
        mitigation=mitigation,
        phase=phase,
        status=status,
    )


# Each mutation of the real threat model, with exactly the problems it must cause.
# {n} is the number of the added row, {first} the ID of the first row and {risks}
# the number of the added residual risk.
MUTATIONS: dict[str, tuple[Mutation, list[str]]] = {
    # Positive: these pass.
    "planned row names a path that does not exist yet": (
        append_row(row("Add `scripts/not_yet.py`.", status="planned")),
        [],
    ),
    "done row names only an issue": (
        append_row(row("Fixed in #11.")),
        [],
    ),
    # Negative: each fails with exactly one problem.
    "section removed": (drop_heading("Assets"), ["no section `## Assets`"]),
    "sections swapped": (
        swap_headings("Assets", "Actors and entry points"),
        [f"the sections are not, each once: {', '.join(SECTIONS)}"],
    ),
    "section twice": (
        lambda text: text + "\n## Assets\n\nMore.\n",
        [f"the sections are not, each once: {', '.join(SECTIONS)}"],
    ),
    "extra section": (add_section, ["unexpected section `## Notes`"]),
    "no mermaid diagram": (
        unfence_diagram,
        ["`## Trust boundaries` has no mermaid diagram"],
    ),
    "boundary missing from the diagram": (
        rename_in_diagram("egress proxy", "egress filter"),
        ["the mermaid diagram does not name egress proxy"],
    ),
    "table header changed": (
        swap_header,
        [f"`## Threats` has no table with the columns {', '.join(COLUMNS)}"],
    ),
    "table without rows": (drop_rows, ["the threat table has no rows"]),
    "row with five cells": (
        append_row("| T-999 | Fixture threat | Fixed in #11. | 0 | done |"),
        ["threat row {n} has 5 cells, not 6"],
    ),
    "ID not T-NNN": (
        append_row(row(threat_id="T-99")),
        ["threat row {n} (T-99): the ID is not T-NNN"],
    ),
    "ID used twice": (
        duplicate_first_id,
        ["threat row {n}: ID {first} is already used"],
    ),
    "boundary unknown": (
        append_row(row(boundary="sandbox")),
        ["threat row {n} (T-999): boundary 'sandbox' is not one of the six"],
    ),
    "mitigation empty": (
        append_row(row("", status="planned")),
        ["threat row {n} (T-999) has no mitigation"],
    ),
    "phase above 11": (
        append_row(row(phase="12")),
        ["threat row {n} (T-999): phase '12' is not 0 to 11"],
    ),
    "phase not a number": (
        append_row(row(phase="two")),
        ["threat row {n} (T-999): phase 'two' is not 0 to 11"],
    ),
    "status unknown": (
        append_row(row(status="wip")),
        ["threat row {n} (T-999): status 'wip' is not one of done, partial, planned"],
    ),
    "partial row names no path or number": (
        append_row(row("Reviewed by hand.", status="partial")),
        [
            "threat row {n} (T-999) is partial but names no path other than a .md"
            " file and no issue or PR number"
        ],
    ),
    "done row names a missing path": (
        append_row(row("Checked by `tests/test_missing.py`.")),
        ["threat row {n} (T-999) names tests/test_missing.py, which does not exist"],
    ),
    "done row names only a .md file": (
        append_row(row("Described in `docs/spec.md`.")),
        [
            "threat row {n} (T-999) is done but names no path other than a .md"
            " file and no issue or PR number"
        ],
    ),
    "residual risks without bullets": (
        drop_residual_risks,
        ["`## Residual risks` has no bullets"],
    ),
    "residual risk without a source": (
        add_residual_risk("A risk without a source."),
        ["residual risk {risks} names no path or number"],
    ),
    "residual risk names a missing .md file": (
        add_residual_risk("A risk from `docs/missing.md`."),
        ["residual risk {risks} names docs/missing.md, which does not exist"],
    ),
}


def test_repo_threat_model_has_its_structure() -> None:
    assert threat_model_problems(THREAT_MODEL.read_text(), REPO_ROOT) == []


@pytest.mark.parametrize("name", MUTATIONS)
def test_check_reports_mutation(name: str) -> None:
    mutate, expected = MUTATIONS[name]
    text = THREAT_MODEL.read_text()
    mutated = mutate(text)
    rows = len(table_lines(text)) - 2
    risks = len(bullets(sections(text)["Residual risks"]))

    assert mutated != text  # the mutation really changed something
    assert threat_model_problems(mutated, REPO_ROOT) == [
        problem.format(n=rows + 1, first=first_id(text), risks=risks + 1)
        for problem in expected
    ]


def test_threats_how_to_lists_the_statuses() -> None:
    lines = [
        line
        for line in sections(THREAT_MODEL.read_text())["Threats"].splitlines()
        if line.startswith(STATUS_VALUES)
    ]
    assert len(lines) == 1, lines
    listed = set(CODE_SPAN.findall(lines[0]))

    assert sorted(listed - set(STATUSES)) == []  # in the how-to, rejected by the check
    assert sorted(set(STATUSES) - listed) == []  # accepted by the check, not listed
