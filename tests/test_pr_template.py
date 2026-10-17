"""PR template tests: every PR body starts from the same evidence sections.

The check is a table of line patterns. The template must match every pattern,
and removing the lines for any one pattern must make the check report it.
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

# Step 5 of ticket.md before this issue.
OLD_STEP_5 = "5. Open a PR that closes the issue. Do not merge it yourself."


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
