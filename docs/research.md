# Why memory invalidation, and not something else

Before writing any code, we checked what DataHub already ships. Most of the
obvious ideas for building on a metadata platform turn out to be built already,
and rebuilding them would have produced something that looked useful and was
not. This document records what we found, because the case for Half-Life rests
on it.

## The first idea, and why it was abandoned

The initial plan was a **cross-platform breaking-change guard**: catch a schema
change at pull-request time, resolve the blast radius through column-level
lineage, and surface the BI assets that dbt-native tooling cannot see.

It is already built, by DataHub, several times over:

| Capability | Where it already exists |
|---|---|
| PR-time impact analysis for dbt | [`acryldata/dbt-impact-action`](https://github.com/acryldata/dbt-impact-action) — a maintained GitHub Action that comments on PRs with downstream impact |
| Impact analysis, UI and API | [Impact Analysis](https://docs.datahub.com/docs/act-on-metadata/impact-analysis) — explicitly framed as identifying "the impact of breaking schema changes", with `searchAcrossLineage` for automation |
| Breaking schema change alerts | [Schema Assertions](https://docs.datahub.com/docs/managed-datahub/observe/schema-assertions) — "get ahead of potentially breaking schema changes" |
| Change notifications | [Subscriptions & Notifications](https://docs.datahub.com/docs/1.1.0/managed-datahub/subscription-and-notification) — field removal and type change filters |
| Contract enforcement | Data Contracts — "prevents breaking changes" |

Whatever was left would have been a marginal improvement on a shipped DataHub
feature.

## Everything else that was checked and ruled out

| Idea | Already shipped as |
|---|---|
| Text-to-SQL / chat with the catalog | Analytics Agent — NL to SQL, execution, Vega-Lite charts, 1–5 context quality score |
| Agent that improves documentation | Analytics Agent's `/improve-context` — writes descriptions, glossary updates and Reference documents back |
| Glossary term and tag propagation | `datahub-enrich` skill; documentation propagation |
| Quality / assertion / incident agent | `datahub-quality` skill, Observability, Smart Assertions |
| ML lineage, target leakage detection | Claimed as existing use cases in [Data Lineage for ML](https://datahub.com/blog/data-lineage-for-ml/), plus Smart Assertions for anomaly detection |
| Connector scaffolding and review | `datahub-connector-planning`, `datahub-connector-pr-review`, 22 standards |
| Pulling unstructured knowledge into the graph | Data Context Graph (v1.4.0) — Notion, Confluence, Google Drive |
| Standardised metric definitions | Announced 2026 roadmap via Snowflake Open Semantic Interchange; dbt Semantic Layer owns this already |
| Agent saves an analysis back to DataHub | Demonstrated at DataHub's [December 2025 Town Hall](https://datahub.com/blog/datahub-town-hall-building-ai-agents/) — a LangChain agent saving a query as a context document |

That last row matters most. Agents writing memories *into* DataHub is a solved,
demonstrated pattern. Which raises the question this project is about.

## The gap

DataHub's own post, [*AI Agent Memory: Why Quality Is a Data
Problem*](https://datahub.com/blog/ai-agent-memory/), argues that memory quality
is downstream of data quality, and states the risk directly:

> An agent with access to incorrect memorized facts becomes **more risky than a
> stateless agent**, because errors lock in rather than expire.

It names four primitives for trustworthy agent memory — lineage, business
glossary, change detection, ownership — all four of which DataHub ships. Then it
names three problems it does **not** solve:

1. How to keep agent memory **invalidated** when upstream definitions change
2. Preventing **silent data drift** in agent memories
3. **Routing escalations** correctly when organizational ownership changes

So: writing memories in is solved and demonstrated. Taking them away is not.
Nothing in DataHub, and nothing in the general agent-memory ecosystem
(LangChain, Mem0, and similar), expires a memory because the data underneath it
changed. Memory stores are built to retain.

The result is a catalog that accumulates confident, well-formatted, permanently
wrong institutional knowledge. The column was renamed in March. The glossary
redefined "Order Total" to exclude discounts. The engineer who owned the table
left in June. The memory still reads exactly as authoritative as the day it was
written, and the next agent inherits it.

Half-Life closes that loop, and targets all three of the named problems:
invalidation (expiry on breaking change), silent drift (fingerprint comparison
where the Timeline API has no coverage), and escalation re-routing (ownership
changes move the notification target without touching the memory's validity).

## What we verified rather than assumed

The design depended on four things being true. Each was tested against a live
DataHub Core v1.5.0.6 before being built on:

| Assumption | Result |
|---|---|
| `document` is available in open-source Core, not Cloud-only | **True** — `entity-registry.yml`, `category: core` |
| Documents accept structured properties | **True** — `structuredProperties` is a document aspect; all 7 properties created |
| The Timeline API reports changes on datapack-loaded entities | **True** — field removal and type change both graded `MAJOR` |
| Timeline severity is usable as a verdict signal | **True**, with corrections — see [upstream.md](upstream.md) |

The fourth is where the design changed. The Timeline API ignores its `start`
parameter and replays an entity's entire history, so a naive implementation
marks every newly recorded memory as suspect on its first validation, against
the very ingestion that created its dependencies. That behaviour is not
documented, produces no error, and would have quietly destroyed the tool's
precision. Five such findings are written up in [upstream.md](upstream.md),
each with a reproduction and a regression test.

## The measure that matters

A memory-integrity tool is only useful if it is precise. Flagging everything
after any upstream change is indistinguishable from flagging nothing — users
learn to ignore it either way. So the demo is built to show restraint: three
upstream changes land, and of five memories, one expires, one becomes suspect,
one has its escalation re-routed, and **two stay untouched**.

The green rows are the claim.
