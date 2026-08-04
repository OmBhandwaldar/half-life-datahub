# Verdict reference

How Half-Life decides whether a memory still deserves to be trusted, and what
each outcome means for an agent reading it.

## Signals

Two independent signals feed every verdict.

**Timeline events.** DataHub's Timeline API already grades each change for
compatibility, so Half-Life does not diff metadata itself. The grading is the
signal: `MAJOR` means backwards incompatible.

**Fingerprint drift.** A hash of each dependency's relevant state (schema field
names and types, glossary definition, ownership, terms) taken when the memory
was recorded. A hash that moved with *no* timeline event to explain it is
**silent drift** — lineage rewiring and unsupported entity types leave no
timeline trail, so without this check a memory can rot invisibly.

## Severity mapping

| Category | Severity | Verdict | Score |
|---|---|---|---|
| `TECHNICAL_SCHEMA` | `MAJOR` | `EXPIRED` | 0 |
| `TECHNICAL_SCHEMA` | `MINOR` | `SUSPECT` | −30 |
| `DOCUMENTATION` on a **glossary term** | any | `SUSPECT` | −30 |
| `DOCUMENTATION` on a **dataset** | any | `VALID` | −5 |
| `GLOSSARY_TERM` | `MINOR` | `SUSPECT` | −30 |
| `OWNERSHIP` | any | `VALID` | 0, escalation re-routed |
| Silent fingerprint drift | — | `SUSPECT` | −25 |

Any `MAJOR` change wins outright: the memory expires regardless of what else is
present. Scores floor at 0.

### Why documentation on a glossary term is different

DataHub reports a glossary term's **definition** change under `DOCUMENTATION`,
not `GLOSSARY_TERM` — that category is reserved for terms being *attached to*
entities. But redefining "Order Total" changes the meaning of every memory built
on it, while editing a dataset's description does not. Half-Life therefore
treats documentation changes on glossary terms as semantic and the same edit on
a dataset as cosmetic.

### Why ownership never invalidates

A memory records a fact about data. Who owns that data has no bearing on whether
the fact is true. What ownership *does* determine is who should be told, so an
ownership change re-routes escalation to the current owner instead of whoever
recorded the memory — one of the open problems DataHub named in
[*AI Agent Memory: Why Quality Is a Data Problem*](https://datahub.com/blog/ai-agent-memory/).

## What each status means for an agent

**`VALID`** — use it. Cite it as prior knowledge.

**`SUSPECT`** — a dependency moved in a way that may or may not matter. Use it
only with the caveat attached, and verify the changed dependency first. Never
present it as fact.

**`EXPIRED`** — the memory is unpublished and recall will not return it. Do not
route around this. Re-derive the answer from the catalog and record a fresh
memory; the audit document explains what happened, but it is an explanation, not
a source to reconstruct the old claim from.

## Terminality

Expiry is terminal. A memory is not resurrected by a later quiet period, because
the change that killed it does not un-happen. Re-recording is a deliberate act
that re-establishes provenance against the current state of the catalog.
