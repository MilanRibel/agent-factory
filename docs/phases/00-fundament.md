# Phase 0: foundation

Goal: a repo where every change goes through CI and review, with documented decisions.

## Deliverables
- Package skeleton and tooling: uv, ruff, pytest, pyright, pre-commit.
  Set requires-python to >=3.12 and replace the placeholder description in pyproject.toml.
- CI: lint, tests, secret scan (gitleaks), workflow lint (actionlint).
  Actions pinned to commit SHA, minimal permissions.
- PR template.
- Validation of .claude/settings.json and CODEOWNERS (protected paths in AGENTS.md).
- Threat model (docs/threat-model.md).
- ADR template and ADR-001..004: local containers, deterministic orchestrator,
  sandbox without network, v1 auth via setup-token.
- scripts/set-rulesets.sh (dry-run supported; the human runs it, never an agent).
- scripts/doctor.py: Docker daemon reachable, VM memory and CPUs via `docker info`,
  gh logged in, uv present, Keychain item exists (never show or log the value).

## Acceptance
- A PR passes CI and merges; direct push to main is blocked.
- A planted fake secret is blocked by CI.
- doctor.py is green.
- Every deliverable has a test or a documented proof, including a negative test.

## Out of scope
Any container code, any LLM or agent code.
