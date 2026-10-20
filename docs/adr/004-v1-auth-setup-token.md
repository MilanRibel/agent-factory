# ADR-004: v1 auth via setup-token

- Status: Accepted
- Date: 2026-10-20

## Context

The forces:

- The human has a subscription seat whose use for this project the human has
  confirmed is permitted.
- The API route needs credits that this seat cannot claim.

Facts about the token, as of 2026-10; the author used Claude Code 2.1.303
(source: the Claude Code authentication page,
https://code.claude.com/docs/en/authentication):

- The token is valid for one year.
- It can only make model requests: no Remote Control, no claude.ai connectors.
- A set `ANTHROPIC_API_KEY` takes precedence over it.

## Decision

`claude setup-token` produces `CLAUDE_CODE_OAUTH_TOKEN`. It is stored in the
macOS Keychain and goes only into the env of LLM roles; `ANTHROPIC_API_KEY`
stays unset (T-022 in `docs/threat-model.md`). The LLM runtime sits behind one
interface so it can move to an API key plus a gateway later.

## Consequences

Positive:

- No extra account.
- One token.
- A small blast radius, because it only makes model requests.

Negative:

- No budget per role.
- The token gives a year of access as the human's account.
- The usage limits are shared with the human's own use.
- The token is visible through `docker inspect` to anyone with Docker access on
  the host.
- How to rotate or revoke the token was not found in the documentation (as of
  2026-10) and must be found out before the token is created.

## Alternatives considered

- An API key from a Console organisation behind a gateway (virtual keys,
  per-role budgets). Not chosen: the credits cannot be claimed with this seat.
- Logging in inside each container. Not chosen: it puts the account login in
  every container.
