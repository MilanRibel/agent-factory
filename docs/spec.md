# Agent factory: spec (v0)

Goal: run ML-engineering projects (Kaggle competitions) autonomously on a local laptop,
in containers, with production-grade security and full traceability in GitHub.

## Principles
- Autonomy comes from guardrails, not from per-change human approval.
- Humans gate only: this spec, changes to protected paths, budget increases, the final submission.
- Credentials, network access and write permissions define role boundaries, not images.
- Everything is reproducible and documented: ADRs, AGENTS.md, README, experiment log.

## Environment
- macOS laptop, Docker Desktop (personal use), local containers only.
- GitHub Free: rulesets require a public repo, so `agent-factory` is public.
  Nothing secret or employer-related may ever be committed here.
- Visibility of per-competition repos is decided in phase 4 (agents read issues and
  comments there, so public repos expose a prompt-injection route).

## Components
- Orchestrator: deterministic state machine (no LLM), runs natively on the host.
  State in SQLite (WAL). GitHub is the source of truth for work and outcomes,
  SQLite for execution state (runs, leases, retries, audit log).
- Roles run as ephemeral containers: planner, implementer, reviewer, worker/sandbox.
- One shared base image (uv, non-root) with thin per-role images, pinned by digest.
- The planner is recurring: it re-plans after experiment results. Tickets are experiments.
- Merge via branch protection + CI + one reviewer-agent approval. No merge agent.
- Evaluation code (eval/, CI config) is a protected path (CODEOWNERS).

## Security model
- Only one way to start a container: JobSpec -> run_container(). A role matrix enforces
  network profile, mounts and credentials per role. No docker.sock in any container.
- Hardening: non-root, read-only rootfs, cap_drop ALL, no-new-privileges,
  memory/cpu/pids limits, timeouts. Worker: network none, no secrets.
- Egress for LLM roles via an internal network and an allowlist proxy
  (Anthropic API, GitHub only).
- v1 auth: `claude setup-token` (CLAUDE_CODE_OAUTH_TOKEN) injected as env var into
  LLM roles only. ANTHROPIC_API_KEY stays unset. The LLM runtime sits behind one
  interface so it can be swapped for an API key + gateway later.
- Separate GitHub identities for implementer and reviewer. Rulesets are set by the
  human with a script, never by an agent.
- Dependencies (uv.lock) are a protected path. Competition data never goes into git.

## Contracts (built first, in phase 1)
1. JobSpec  2. Role matrix  3. Ticket state machine
4. Run result contract (exit code, metrics.json, artifacts,
   provenance: git SHA, image digest, data hash, seed)

## Out of scope for v1
Kubernetes, GPUs, multiple users, cloud hosting.

## Roadmap
Phase 0 foundation; 1 contracts and core; 2 sandbox and isolation; 3 skeleton without LLM;
4 competition template and identities; 5 implementer; 6 worker end-to-end;
7 reviewer; 8 planner; 9 parallelism and operations; 10 hardening and red-team;
11 first real competition.
