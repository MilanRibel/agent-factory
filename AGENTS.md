# AGENTS.md

- Write code, comments and docs in English.
- Commands: `uv run pytest`, `uv run ruff check .`
- One issue = one branch = one PR. Tests first, show them failing. Never push to main.
- Protected paths (change only when the issue says so): docs/adr/, .github/, images/**/Dockerfile, uv.lock, pyproject.toml, AGENTS.md, CLAUDE.md, .claude/, scripts/set-rulesets.sh, .gitleaks.toml, .gitleaksignore, .gitleaks/, tests/protected_paths.py, tests/fake_gh.py, tests/test_adr_format.py, tests/test_agents_md.py, tests/test_claude_settings.py, tests/test_codeowners.py, tests/test_pr_template.py, tests/test_pre_commit_config.py, tests/test_secret_scan.py, tests/test_set_rulesets.py, tests/test_threat_model.py, tests/test_tooling.py, tests/test_workflow_lint.py, tests/test_workflow_policy.py, tests/test_workflow_triggers.py
- Every architectural decision gets an ADR.
- Never read, write or log secrets. Never mount docker.sock.
- Do not merge PRs.

## Pinning
- Pin actions and reusable workflows to a full 40-hex commit SHA (`tests/test_workflow_policy.py`). Put the version in a comment and verify the SHA with `git ls-remote` (review rule).
- Take the newest release that is at least 14 days old. If none is old enough, take the newest and say so in the PR (review rule).
- After `uv add`, show `uv tree` and `git diff --stat -- pyproject.toml uv.lock`; only the intended package may change (review rule).
- `astral-sh/setup-uv` runs with `enable-cache: false` (review rule).
- A binary downloaded in CI is checked against a pinned sha256 (`tests/test_secret_scan.py`, `tests/test_workflow_lint.py`). Download it with `curl --proto '=https' --proto-redir '=https'`, check it before unpacking and extract only the binary (review rule).
- Before relying on a CLI flag, show that the pinned version lists it in `--help` (review rule).
- A new security tool gets a guard test that fails when its override or ignore files appear (review rule).

## Workflows
- Top-level `permissions` is declared and read-only. A job-level write needs a `WRITE_ALLOWLIST` entry with a reason; never `write-all` (`tests/test_workflow_policy.py`).
- No `pull_request_target` trigger. Every checkout sets `persist-credentials: false`. No `${{ … }}` in a `run:` script; pass values through `env:` (`tests/test_workflow_policy.py`).
- No `paths` or `paths-ignore` filter on a trigger: required checks run on every PR (`tests/test_workflow_triggers.py`).

## Permission mode
Review rules; #28 adds tests for part of them. Labels checked against the Claude Code docs for Claude Code 2.1.303.
- Start Claude Code with `--permission-mode default` (shown as Manual) or `--permission-mode plan`; without the flag a terminal session starts in `auto` in Claude Code 2.1.303. Never `acceptEdits` or `auto`. The one exception is a trial that an issue asks for, on a throwaway branch. Only a human starts such a trial.
- In a permission prompt, answer `Yes` or `No` for that one call. Never choose an option that allows more: one that accepts edits automatically, allows the action for the rest of the session, saves a rule ("Yes, and don't ask again for …") or switches to auto mode ("Yes, and switch to auto mode"). In a file prompt, Shift+Tab selects the rest-of-session option.
- When approving a plan, choose "Yes, manually approve edits". Never "Yes, and use auto mode", "Yes, auto-accept edits" or an option that switches to bypass permissions.
- Shift+Tab cycles `default` → `acceptEdits` → `plan` → `auto` (when available) → `default`; stop only on `default` or `plan`.
- An agent never asks the user to switch modes or to choose one of these options.
- Why: the `Edit` ask rules cover the `Edit` tool only. In `acceptEdits`, a Bash redirect into `AGENTS.md` ran without a prompt (PR #27, trial 4). #28 guards Bash writes.
