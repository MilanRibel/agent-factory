# AGENTS.md

- Write code, comments and docs in English.
- Commands: `uv run pytest`, `uv run ruff check .`
- One issue = one branch = one PR. Tests first, show them failing. Never push to main.
- Protected paths (change only when the issue says so): docs/adr/, .github/, images/**/Dockerfile, uv.lock
- Every architectural decision gets an ADR.
- Never read, write or log secrets. Never mount docker.sock.
- Do not merge PRs.
