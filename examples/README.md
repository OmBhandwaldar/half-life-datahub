# Sample outputs

Captured from a real run against **DataHub Core v1.5.0.6** with the
`showcase-ecommerce` datapack (~1,050 entities across Snowflake, dbt, Looker,
PowerBI, Tableau, Spark, PostgreSQL and S3). Nothing here is mocked.

Reproduce with:

```bash
halflife demo reset && halflife demo seed
halflife demo drift
halflife validate --apply
```

## The run, in order

| File | What it shows |
|---|---|
| [`01-seed.txt`](01-seed.txt) | Five memories recorded, each with a fingerprint per dependency |
| [`02-ledger-before.txt`](02-ledger-before.txt) | All five `VALID`, score 100 |
| [`03-drift.txt`](03-drift.txt) | Three upstream changes: dropped column, redefined glossary term, ownership handover |
| [`04-validate.txt`](04-validate.txt) | Verdicts with the causal reason for each |
| [`05-ledger-after.txt`](05-ledger-after.txt) | 1 expired, 1 suspect, 3 valid |
| [`06-recall-withheld.txt`](06-recall-withheld.txt) | Recall refusing to return the expired memory |

## The outcome

Three changes landed. Exactly the memories resting on them reacted:

| Memory | Result | Cause |
|---|---|---|
| Inventory snapshots land nightly | **EXPIRED** (0/100) | `quantity_on_hand` dropped — `MAJOR`, backwards incompatible |
| Order Total is computed before discounts | **SUSPECT** (70/100) | "Order Total" redefined |
| Customer segmentation uses `customer_class` | VALID (100/100) | ownership moved → escalation re-routed |
| `order_details` is one row per order line | VALID (100/100) | untouched |
| Join orders to order_details on `order_id` | VALID (100/100) | untouched |

The three green rows are the point. A tool that reddens everything after any
upstream change is no more useful than one that reddens nothing — the value is
in flagging *only* what actually broke.

## Artefacts written back to DataHub

| File | What it is |
|---|---|
| [`memory-document.json`](memory-document.json) | A memory as stored: dependencies, per-dependency fingerprints, status, score, watermark |
| [`audit-document.md`](audit-document.md) | The audit document written on expiry, linked to both the dataset that changed and the memory that died |
| [`explain-expired-memory.json`](explain-expired-memory.json) | `explain_memory` MCP output — provenance and causal chain |
| [`ledger.json`](ledger.json) | `memory_ledger` MCP output |

The audit document is worth opening. It records the transition, the integrity
score, the exact `MAJOR` change event with its field path, and — because DataHub
also reported the field's description being removed — the secondary
`DOCUMENTATION` event alongside it. That is the trail a human follows six months
later when asking why a memory disappeared.
