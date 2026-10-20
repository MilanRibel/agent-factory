# ADR-001: Local containers

- Status: Proposed
- Date: 2026-10-20

## Context

The factory runs ML experiments (Kaggle competitions) in loops: the planner
re-plans after each result, and every role runs as an ephemeral container
(`docs/spec.md`). The experiments need a machine to run on. The forces:

- The human wants to run locally.
- As of 2026-10, free cloud tiers are too small for experiment loops: they offer
  little CPU and memory, and their instances go to sleep.
- Kaggle Notebooks and Colab are not containers, while the spec builds its roles
  and its security model on containers.
- Docker Desktop is already installed on the human's own laptop and is free for
  personal use there.

## Decision

Experiments run locally, in containers on the human's own macOS laptop, with
Docker Desktop as the container runtime.

## Consequences

Positive:

- One machine runs everything.
- No cloud costs.
- Fast iteration.
- The images are portable, so they can move to another host later.

Negative:

- No GPU: Docker on macOS has no access to Metal. The first competition is
  tabular, and LightGBM runs on the CPU; a GPU is out of scope for v1
  (`docs/spec.md`).
- Slower file I/O on directories mounted from the host.
- The Docker VM has 8,217,407,488 bytes of memory (about 7.65 GiB) and 14 CPUs,
  measured with `docker info` on 2026-10-20, while `scripts/doctor.py`
  (planned, #14) will require 16 GiB. The human raises the memory in Docker
  Desktop in #14.
- Runs stop when the laptop sleeps.
- Docker Desktop is free for personal use, education and small businesses, and
  paid for professional use in larger organisations. This is a personal project
  on the human's own laptop, so the personal-use terms apply. The licence must be
  reviewed again when the situation changes.

## Alternatives considered

- A cloud VM or a paid container service. Not chosen: the human wants to run
  locally; free tiers are too small for experiment loops (as of 2026-10), and
  paid ones bring cloud costs.
- Kubernetes. Not chosen: it is out of scope for v1 (`docs/spec.md`).
- Colima, Podman, Rancher Desktop or OrbStack instead of Docker Desktop. Not
  chosen: the licence of Docker Desktop decided the choice; it is free for
  personal use and already installed. Colima is the fallback if the situation
  changes, for example if the laptop or its use becomes professional.
