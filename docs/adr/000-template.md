# ADR-NNN: Title

- Status: <value>
- Date: YYYY-MM-DD

## Context

How to use this template: copy it to `docs/adr/NNN-kebab-case.md`, where NNN is
the next free number (000 is this template). Fill in the title, the status and
the date, and replace the text of every section. `tests/test_adr_format.py`
checks the format.

Status values: `Proposed`, `Accepted`, `Deprecated`, `Superseded by ADR-NNN`.

A new ADR starts as `Proposed`. Only the human sets it to `Accepted`, in the same
PR, before the merge (review rule).
The reviewer checks that no ADR was set to Accepted by its author (review rule).
An ADR that no longer applies becomes `Deprecated`; one that a later ADR replaces
becomes `Superseded by ADR-NNN`, with the number of the later ADR.

The date is the day the ADR was written, as YYYY-MM-DD.

Replace this how-to with the real context: the problem and the forces that make a
decision necessary.

## Decision

The decision, in a few sentences.

## Consequences

What becomes easier or harder because of the decision.

## Alternatives considered

Each option that was weighed, and why it was not chosen.
