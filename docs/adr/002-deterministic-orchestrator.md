# ADR-002: Deterministic orchestrator

- Status: Proposed
- Date: 2026-10-20

## Context

The orchestrator starts the role containers through one entry point,
JobSpec -> run_container(), and tracks work and runs (`docs/spec.md`). It needs a
form, a place to run and a store for its state. The forces:

- LLM output must never decide a state transition: prompt injection could then
  steer the factory (`docs/threat-model.md`).
- No container may hold a Docker socket (`docs/spec.md`, AGENTS.md). A process
  that runs natively on the host starts containers without one.
- A single process needs no separate service.

## Decision

The orchestrator is a deterministic state machine without an LLM; LLM output is
data for it, never a transition. It runs natively on the host as a single
process, keeps the execution state (runs, leases, retries, audit log) in SQLite
in WAL mode, and uses GitHub as the source of truth for work and outcomes.

## Consequences

Positive:

- Predictable and testable.
- Cheap.
- The smallest attack surface.

Negative:

- The scheduler and crash recovery have to be built.
- The native process holds a GitHub token on the host. Proposal: it handles no
  untrusted text with an LLM (T-024 in `docs/threat-model.md`, planned, phase 1)
  and gets only the GitHub permissions the orchestrator needs; no threat row
  covers the permissions yet.
- It stops when the laptop sleeps.

## Alternatives considered

- An LLM as orchestrator. Not chosen: LLM output would decide state transitions,
  so prompt injection could steer the factory.
- Temporal or Prefect. Not chosen: a single process needs no separate service.
- GitHub Actions as orchestrator. Not chosen: it cannot start local containers.
- The orchestrator in a container with a filtered Docker socket. Not chosen: a
  filter still puts a Docker socket in a container, and running natively means
  that no container ever gets one.
