# Half-Life

**Memory integrity for DataHub agents.** Agent memories decay when the data beneath them changes. Half-Life computes how much is left.

Built for [Build with DataHub: The Agent Hackathon](https://datahub.devpost.com/).

---

## The problem DataHub named and nobody solved

In [*AI Agent Memory: Why Quality Is a Data Problem*](https://datahub.com/blog/ai-agent-memory/), DataHub makes an argument that is easy to nod along to and hard to act on:

> An agent with access to incorrect memorized facts becomes **more risky than a stateless agent**, because errors lock in rather than expire.

The post lists four primitives needed for trustworthy agent memory — lineage, business glossary, change detection, ownership — and then names three problems it leaves open:

1. How to keep agent memory **invalidated** when upstream definitions change
2. Preventing **silent data drift** in agent memories
3. **Routing escalations** correctly when organizational ownership changes

Everything downstream of that is built. Agents can already write memories back to DataHub — a LangChain agent saving a query as a context document was demoed at DataHub's own town hall. What is missing is the other half: **nothing ever takes a memory away.**

So the catalog accumulates confident, well-formatted, permanently-wrong institutional knowledge. The column was renamed in March. The glossary redefined "Order Total" to exclude discounts. The engineer who owned the table left in June. The memory still reads exactly as authoritative as the day it was written, and the next agent inherits it.

Half-Life gives memories a lifespan.

## What it does

Memories are stored as DataHub Documents carrying **typed provenance**: the URNs they were derived from, and a fingerprint of that metadata's state at the moment of writing. Half-Life then continuously re-checks them:

- **Timeline API** — DataHub's own change history, which already grades every change for compatibility. A `MAJOR` (backwards incompatible) change to a dependency expires the memory outright.
- **Fingerprint drift** — a dependency whose state moved with *no* timeline event to explain it. This is the silent-drift case: lineage rewiring and unsupported entity types leave no timeline trail, so without this check a memory rots invisibly.

Verdicts are written back into the graph:

| Outcome | What happens |
|---|---|
| `VALID` | Score and validation watermark updated |
| `SUSPECT` | Tagged, score reduced, reason recorded, returned by recall **with a warning** |
| `EXPIRED` | **Unpublished** — recall can no longer return it — tagged, and an audit document written |

Expiry is structural, not advisory. An expired memory is removed from circulation, so the next agent physically cannot inherit a fact that stopped being true. It has to re-derive from the catalog, which is the correct behaviour.

Ownership changes never invalidate a memory — the facts are unaffected — but they **re-route escalation to whoever owns the dependency now**, not whoever recorded the memory.

## Precision matters more than recall

A tool that reddens everything is no more useful than one that reddens nothing. Verified against a live instance with the `showcase-ecommerce` datapack:

```
=== validate immediately after recording ===
  order-total-memory      VALID    score=100  events=0
  control-memory          VALID    score=100  events=0

=== after redefining the 'Order Total' glossary term ===
  order-total-memory      SUSPECT  score= 70  events=1
       - DOCUMENTATION MINOR :: Documentation of 'urn:li:glossaryTerm:...42266719...'
  control-memory          VALID    score=100  events=0
```

The memory that depended on the redefined term degraded. The one that didn't stayed green.

## Quickstart

Requires Docker (8 GB+ allocated), Python 3.10+.

```bash
# 1. DataHub Core + sample data
pip install acryl-datahub
datahub docker quickstart
datahub datapack load showcase-ecommerce

# 2. Half-Life
pip install -e .
export DATAHUB_GMS_URL=http://localhost:8080
halflife init            # creates the structured properties

# 3. Watch a memory die
halflife demo seed       # five memories against real datapack entities
halflife list            # all five VALID
halflife demo drift      # breaking schema change + glossary redefinition + ownership handover
halflife validate --apply
halflife list            # expired, suspect, re-routed — and two still green
```

`halflife recall "how do I compute order totals"` returns only memories still worth trusting, and tells you what it withheld.

## Architecture

```
src/halflife/
  models.py       Memory, ChangeEvent, Verdict, severity enums
  fingerprint.py  Canonical snapshots and drift comparison (pure)
  timeline.py     DataHub Timeline API client
  client.py       GraphQL + SDK wrapper
  properties.py   Structured property definitions
  validator.py    Severity mapping (pure, heavily tested)
  store.py        Memory <-> Document persistence
  actions.py      Write-back: status, unpublish, tag, re-route, audit
  recall.py       Retrieval with an integrity filter
  mcp_server.py   MCP tools for agents
  ledger/         Web ledger
```

Half-Life keeps **no database of its own**. A memory that lives in the catalog is already reachable by every agent and human through tools they use anyway, and its integrity verdict travels with it.

## Notes from building against DataHub v1.5.0.6

Behaviours found by running against a live instance rather than reading documentation. Each is handled in code and pinned by a test:

- The Timeline API **ignores the `start` parameter** and replays an entity's entire computed history. Without client-side filtering, every freshly recorded memory is judged against the ingestion that created its own dependencies, and is immediately marked suspect. This one silently destroys precision.
- Timeline responses are a **bare transaction array**, not the documented `{"changeTransactions": [...]}` wrapper, and events use `entityUrn` / `operation` / `modifier` rather than `target` / `changeType` / `elementId`.
- The **`OWNERSHIP` category returns HTTP 500** on every URN, including ones that do not exist. The "legacy" `OWNER` alias is the one that works — the reverse of what the docs say. *(Reported upstream; see [docs/upstream.md](docs/upstream.md).)*
- Editing a glossary term's **definition** is reported as `DOCUMENTATION`, not `GLOSSARY_TERM` — that category is reserved for terms being attached to entities. Redefining a term changes what every memory built on it means, so Half-Life treats documentation changes on glossary terms as semantic while the same edit on a dataset is not.

## Attribution

Third-party components used, per the hackathon's disclosure requirement:

- [DataHub](https://github.com/datahub-project/datahub) (Apache 2.0) — metadata platform, Python SDK, Timeline API
- `showcase-ecommerce` datapack from [datahub-project/static-assets](https://github.com/datahub-project/static-assets) — demo data
- Typer, Rich, FastAPI, httpx, Pydantic, MCP SDK

All Half-Life source in this repository was written during the hackathon submission period.

## License

Apache 2.0 — see [LICENSE](LICENSE).
