# ADR-003: Sandbox without network

- Status: Accepted
- Date: 2026-10-20

## Context

The roles run as ephemeral containers: planner, implementer, reviewer and
worker/sandbox (`docs/spec.md`). The forces:

- Generated code runs in the worker, so it gets no outbound path.
- The worker needs no packages or downloads at run time, because the image and
  the data are prepared beforehand.

## Decision

The worker runs with network none, no secrets, data mounted read-only, and
results through one output mount.

## Consequences

Positive:

- No outbound traffic from where generated code runs.
- A small attack surface.

Negative:

- No installs or downloads at run time, so the image and the data must be ready.
- The output mount is a channel, and what the worker writes there is untrusted
  data that the orchestrator reads, never an instruction (T-019 in
  `docs/threat-model.md`). The orchestrator reads it as data (ADR-002).
- Docker Desktop containers share the VM kernel, so the isolation is weaker than
  a microVM (T-016 in `docs/threat-model.md`).

## Alternatives considered

- Also route the worker through the allowlist proxy that the LLM roles use
  (`docs/spec.md`). Not chosen: more channels to leak data.
- gVisor or microVMs. They give stronger isolation. Not chosen: more work now.
  They are a candidate for phase 10.
