---
description: Work on a GitHub issue following the project workflow
argument-hint: <issue number>
---
Work on GitHub issue $ARGUMENTS.

1. Read the issue (`gh issue view`), AGENTS.md and docs/spec.md.
2. Propose a short plan and wait for my approval.
3. Create a new branch. Write the tests first and show them failing.
4. Implement. Run `uv run ruff check .` and `uv run pytest`.
5. Open a PR that closes the issue, with a body written from `.github/pull_request_template.md`: keep every heading and checklist item, fill in each section (write "None" where nothing applies), tick a security item only after checking it, and pass the body with `gh pr create --body-file`. A checklist item that does not apply stays unticked, followed by `N/A: <reason>`. Do not merge it yourself.
6. Summarise: what changed, which test proves what, and what was not done.
