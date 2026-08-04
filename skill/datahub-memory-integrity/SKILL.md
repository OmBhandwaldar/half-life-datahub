---
name: datahub-memory-integrity
description: |
  Use this skill when the user wants agent memories, saved analyses, or context documents in DataHub to stay trustworthy as the catalog changes: recording a conclusion so future agents inherit it, checking whether a stored memory is still valid, expiring memories whose dependencies changed, or auditing why a memory was withdrawn. Triggers on: "remember this", "save this analysis", "what do we already know about X", "is this still true", "check my memories", "why was this memory expired", "stale context", "agent memory", or any request involving durable knowledge stored in DataHub and whether it still holds. For one-off catalog questions with no memory involved, use `/datahub-search`. For lineage impact, use `/datahub-lineage`.
user-invocable: true
min-cli-version: 1.4.0
allowed-tools: Bash(halflife *), Bash(datahub *)
---

# DataHub Memory Integrity

You are responsible for the durability of what agents learn. Storing a
conclusion in DataHub is easy; the hard part is knowing when to stop believing
it.

A memory is a DataHub Document that records a conclusion **and the metadata it
was derived from**. When a dependency changes — a column dropped, a glossary
term redefined, an owner replaced — the memory is re-scored and, if the change
was breaking, expired and unpublished so no agent can inherit it.

The governing principle, from DataHub's own analysis of agent memory: *an agent
with incorrect memorized facts is more risky than a stateless agent, because
errors lock in rather than expire.* Prefer withdrawing a doubtful memory over
serving it.

---

## Multi-Agent Compatibility

This skill works across coding agents (Claude Code, Cursor, Codex, Copilot,
Gemini CLI, Windsurf, and others).

**What works everywhere:**

- The full record / recall / validate workflow via the `halflife` CLI
- Memory inspection via `datahub graphql` against Document entities

**Claude Code-specific features** (other agents can safely ignore these):

- `allowed-tools` in the YAML frontmatter above

**Reference file paths:** Skill-specific references are in `references/`.

---

## Not This Skill

| If the user wants to...                                  | Use this instead     |
| -------------------------------------------------------- | -------------------- |
| Search or browse the catalog, no memory involved         | `/datahub-search`    |
| Trace upstream/downstream impact of a change             | `/datahub-lineage`   |
| Edit descriptions, tags, ownership on data assets        | `/datahub-enrich`    |
| Create assertions or manage incidents                    | `/datahub-quality`   |

---

## Before anything else

Memories are only as good as their recorded provenance, so establish that first.

1. Confirm the connection: `halflife init` (idempotent — creates the structured
   properties if absent, reports `exists` otherwise).
2. If the user has no memories yet, say so plainly rather than inventing them.

---

## Workflow 1 — Recall before investigating

**Always run this before doing expensive catalog work.** Someone may have
already answered the question, and if they have not, the absence is itself
informative.

```bash
halflife recall "how do we compute order totals"
```

Interpret the result carefully:

- **A `VALID` memory** — use it, and say where it came from.
- **A `SUSPECT` memory** — use it only with the stated caveat, and verify the
  changed dependency before relying on it. Tell the user what changed.
- **Memories reported as withheld** — these expired. Do **not** ask for them
  another way and do not reconstruct them from the audit trail. Re-derive the
  answer from the catalog, then record a fresh memory.

If recall returns nothing, proceed with normal investigation.

## Workflow 2 — Record after reaching a conclusion

Record only non-obvious conclusions: things a competent engineer could not read
straight off the schema. Grain, join keys, business rules, gotchas, why the
obvious approach is wrong.

```bash
halflife record \
  --title "Order Total is computed before discounts" \
  --text  "Use the Order Total glossary definition rather than recomputing from unit_price * quantity, which ignores order-level adjustments." \
  --depends-on "urn:li:dataset:(urn:li:dataPlatform:snowflake,analytics.order_details,PROD)" \
  --depends-on "urn:li:glossaryTerm:order_total"
```

**Dependencies are the whole point.** List every URN the conclusion actually
rests on — datasets, glossary terms, and the specific columns if the claim is
column-level. A memory recorded without dependencies can never be invalidated,
which leaves it permanently authoritative. That is worse than not recording it.

Be honest about what the conclusion rests on rather than generous: listing
unrelated datasets makes the memory expire for irrelevant reasons and trains
users to ignore the warnings.

## Workflow 3 — Validate

```bash
halflife validate            # dry run, reports what would change
halflife validate --apply    # writes verdicts back to DataHub
```

Default to the dry run and show the user the transitions before applying. Only
`--apply` when they have seen what will change or have asked for it directly.

How verdicts are reached:

| Signal                                              | Outcome                             |
| ---------------------------------------------------- | ----------------------------------- |
| `MAJOR` (backwards incompatible) change on a dependency | `EXPIRED` — unpublished, score 0  |
| `MINOR` schema or glossary-definition change        | `SUSPECT` — score reduced           |
| Fingerprint moved with no timeline event            | `SUSPECT` — silent drift            |
| Ownership changed                                   | `VALID` — escalation re-routed      |
| Documentation edited on a dataset                   | `VALID` — small score penalty       |

Ownership changes never invalidate a memory. The facts are unaffected; only the
person to escalate to has moved.

## Workflow 4 — Explain a withdrawal

When a user asks why a memory disappeared:

```bash
halflife list          # current status of every memory
```

Then read the audit document, which is linked to both the memory and the asset
that changed. Give the user the causal chain — which dependency changed, what
kind of change it was, and when — not just the verdict.

---

## Reporting

State the status and the reason together; a status with no cause is not
actionable. Prefer:

> `Order Total is computed before discounts` is **SUSPECT** (70/100) — the
> "Order Total" glossary term was redefined on 4 Aug to exclude discounts, and
> this memory assumed they were included.

over "that memory is suspect".

When recall withholds something, say so explicitly. A silent gap looks like
"nothing is known", which is a materially different claim from "what was known
is no longer true".

---

## Cautions

- Never present a `SUSPECT` memory as fact.
- Never resurrect an `EXPIRED` memory. Re-derive, then record anew.
- Do not record a memory that merely restates the schema — it adds noise and
  will need maintaining.
- Do not record conclusions the user has not confirmed, especially ones derived
  from a `SUSPECT` memory. Poisoned memories compound.
