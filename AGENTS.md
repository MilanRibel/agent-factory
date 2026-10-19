# AGENTS.md

- Write code, comments and docs in English.
- Commands: `uv run pytest`, `uv run ruff check .`
- One issue = one branch = one PR. Tests first, show them failing. Never push to main.
- Protected paths (change only when the issue says so): docs/adr/, .github/, images/**/Dockerfile, uv.lock, AGENTS.md, CLAUDE.md, .claude/, scripts/set-rulesets.sh, .gitleaks.toml, .gitleaksignore, .gitleaks/, tests/protected_paths.py, tests/fake_gh.py, tests/test_claude_settings.py, tests/test_codeowners.py, tests/test_pr_template.py, tests/test_secret_scan.py, tests/test_set_rulesets.py, tests/test_workflow_lint.py, tests/test_workflow_policy.py, tests/test_workflow_triggers.py
- Every architectural decision gets an ADR.
- Never read, write or log secrets. Never mount docker.sock.
- Do not merge PRs.
