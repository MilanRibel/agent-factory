"""PR template tests: every PR body starts from the same evidence sections.

The check is a table of line patterns. The template must match every pattern,
and removing the lines for any one pattern must make the check report it.
Step 5 of the /ticket command points to the template, and since #7 it is the
step 5 from before #7 plus exactly the N/A sentence.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = ".github/pull_request_template.md"
TEMPLATE = REPO_ROOT / TEMPLATE_PATH
TICKET_COMMAND = REPO_ROOT / ".claude" / "commands" / "ticket.md"

# Each required part is a regex that at least one template line must fully match.
REQUIRED_LINES: dict[str, str] = {
    "Closes #": r"Closes #\d*",
    "Summary": r"## Summary",
    "Tests": r"## Tests",
    "Negative test": r"## Negative test",
    "Protected paths touched": r"## Protected paths touched",
    "Security checklist": r"## Security checklist",
    "Not done / follow-ups": r"## Not done / follow-ups",
    "no secrets": r"- \[[ x]\] No secrets\b.*",
    "no docker.sock": r"- \[[ x]\] No `docker\.sock`.*",
    "no new network egress": r"- \[[ x]\] No new network egress\b.*",
    "actions pinned to a commit SHA": r"- \[[ x]\] .*pinned to a full commit SHA\b.*",
}

# Step 5 of ticket.md before #2.
OLD_STEP_5 = "5. Open a PR that closes the issue. Do not merge it yourself."

# Step 5 of ticket.md before #7, and the sentence #7 adds to it.
STEP_5_BEFORE_7 = (
    "5. Open a PR that closes the issue, with a body written from"
    " `.github/pull_request_template.md`: keep every heading and checklist item,"
    ' fill in each section (write "None" where nothing applies), tick a security'
    " item only after checking it, and pass the body with"
    " `gh pr create --body-file`. Do not merge it yourself."
)
NA_SENTENCE = (
    "A checklist item that does not apply stays unticked, followed by `N/A: <reason>`."
)
STEP_5 = STEP_5_BEFORE_7.replace(
    " Do not merge it yourself.", f" {NA_SENTENCE} Do not merge it yourself."
)
# Step 5 texts the N/A check must reject: each differs from STEP_5_BEFORE_7 by
# more or less than the N/A sentence.
STEP_5_VARIANTS = {
    "before #7": STEP_5_BEFORE_7,
    "N/A sentence without the merge ban": STEP_5.removesuffix(
        " Do not merge it yourself."
    ),
    "N/A sentence on a line of its own": STEP_5.replace(
        f" {NA_SENTENCE}", f"\n   {NA_SENTENCE}"
    ),
    "N/A sentence reworded": STEP_5.replace("stays unticked", "is ticked"),
}


def matches(line: str, pattern: str) -> bool:
    return re.fullmatch(pattern, line.strip()) is not None


def missing_parts(markdown: str) -> list[str]:
    lines = markdown.splitlines()
    return [
        name
        for name, pattern in REQUIRED_LINES.items()
        if not any(matches(line, pattern) for line in lines)
    ]


def refers_to_template(command: str) -> bool:
    steps = [line for line in command.splitlines() if line.startswith("5. ")]
    return len(steps) == 1 and TEMPLATE_PATH in steps[0]


def step_block(command: str, number: int) -> str:
    """A numbered step with every line up to the next numbered step."""
    lines = command.splitlines()
    starts = [i for i, line in enumerate(lines) if re.match(r"\d+\. ", line)]
    for index, start in enumerate(starts):
        if lines[start].startswith(f"{number}. "):
            end = starts[index + 1] if index + 1 < len(starts) else len(lines)
            return "\n".join(lines[start:end]).strip()
    return ""


def has_na_step_5(command: str) -> bool:
    return step_block(command, 5) == STEP_5


def command_with_step_5(step_5: str) -> str:
    return f"4. Implement.\n{step_5}\n6. Summarise.\n"


def test_template_has_all_required_parts() -> None:
    assert missing_parts(TEMPLATE.read_text()) == []


@pytest.mark.parametrize("name", REQUIRED_LINES)
def test_check_reports_removed_part(name: str) -> None:
    lines = TEMPLATE.read_text().splitlines()
    kept = [line for line in lines if not matches(line, REQUIRED_LINES[name])]

    assert len(kept) < len(lines)  # the mutation really removed something
    assert missing_parts("\n".join(kept)) == [name]


def test_ticket_command_step_5_refers_to_template() -> None:
    assert refers_to_template(TICKET_COMMAND.read_text())


def test_reference_check_rejects_old_step_5() -> None:
    assert not refers_to_template(OLD_STEP_5)


def test_ticket_command_step_5_adds_na_sentence() -> None:
    assert STEP_5 != STEP_5_BEFORE_7  # the sentence really went in
    assert has_na_step_5(TICKET_COMMAND.read_text())


def test_na_check_accepts_step_5() -> None:
    assert has_na_step_5(command_with_step_5(STEP_5))


@pytest.mark.parametrize("name", STEP_5_VARIANTS)
def test_na_check_rejects_variant(name: str) -> None:
    assert not has_na_step_5(command_with_step_5(STEP_5_VARIANTS[name]))
