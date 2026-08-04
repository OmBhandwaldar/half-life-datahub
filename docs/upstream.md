# Upstream findings

Behaviours found while building Half-Life against **DataHub Core v1.5.0.6** (GMS
`v1.5.0.6`, CLI `1.6.0.17`, quickstart on Docker). Each contradicts the published
documentation, each is reproducible from a clean quickstart, and each is worked
around in this repository with a test pinning the real behaviour.

They are written up here in the form a maintainer would want them.

---

## 1. Timeline API returns HTTP 500 for the `OWNERSHIP` category

**Severity:** high — the category is unusable.

[The Timeline docs](https://docs.datahub.com/docs/dev-guides/timeline) list
`OWNERSHIP` as the current category name with `OWNER` as a legacy alias. In
practice the relationship is inverted: `OWNERSHIP` returns a 500 for *every*
URN, and `OWNER` is the one that works.

### Reproduction

```bash
datahub docker quickstart
datahub datapack load showcase-ecommerce

URN='urn:li:dataset:(urn:li:dataPlatform:hive,DoesNotExist,PROD)'
ENC=$(python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=''))" "$URN")

curl -s -o /dev/null -w "OWNERSHIP -> %{http_code}\n" \
  "http://localhost:8080/openapi/v2/timeline/v1/${ENC}?categories=OWNERSHIP&start=1&end=9999999999999"
curl -s -o /dev/null -w "OWNER     -> %{http_code}\n" \
  "http://localhost:8080/openapi/v2/timeline/v1/${ENC}?categories=OWNER&start=1&end=9999999999999"
```

### Observed

```
OWNERSHIP -> 500     {"error":"Internal server error occurred"}
OWNER     -> 200     []
```

Reproduced on a non-existent URN as well as on real datapack entities, so it is
not data-dependent. A single unhealthy category also fails the whole request
when categories are combined, which takes down the other four.

### Expected

Either `OWNERSHIP` is accepted, or it is rejected with a 4xx naming the valid
values. A 500 on a URN that does not exist points at enum resolution rather than
anything to do with the entity.

### Workaround

`src/halflife/timeline.py` sends `OWNER` on the wire and normalises back to
`OWNERSHIP` internally, and retries categories individually when a combined
request fails.

---

## 2. Timeline API ignores the `start` parameter

**Severity:** high — silently wrong results rather than an error.

`start` and `end` are documented as the query window. `end` is respected;
`start` is not. The endpoint replays the entity's entire computed history
regardless of what `start` is set to.

### Reproduction

```bash
# Any datapack entity. Ask for changes since "now" - a window in which
# nothing can have happened.
NOW=$(python3 -c 'import time;print(int(time.time()*1000))')
curl -s "http://localhost:8080/openapi/v2/timeline/v1/${ENC}?categories=TECHNICAL_SCHEMA&start=${NOW}&end=${NOW}" \
  | python3 -c "import json,sys; print(len(json.load(sys.stdin)), 'transactions returned')"
```

### Observed

Every transaction since ingestion, including events with timestamps far below
`start`.

### Expected

Only transactions inside `[start, end]`.

### Why it matters

This is the failure mode that quietly destroys a caller's precision rather than
producing an error. Anything that watermarks its last check and asks "what
changed since then" gets back the entity's whole history, including the initial
ingestion. For Half-Life that meant every newly recorded memory was immediately
judged against the ingest that created its own dependencies, and marked suspect
on its first validation.

### Workaround

`src/halflife/timeline.py` filters `event.timestamp > start` client-side.

---

## 3. Timeline response shape differs from the documentation

**Severity:** low — cosmetic, but it breaks naive parsers.

The docs show:

```json
{ "changeTransactions": [ { "changeEvents": [ { "changeType": "...", "target": "...", "elementId": "..." } ] } ] }
```

The server returns a **bare array** of transactions, and events use different
keys:

| Documented | Actual |
|---|---|
| `{"changeTransactions": [...]}` | `[...]` |
| `changeType` | `operation` |
| `target` | `entityUrn` |
| `elementId` | `modifier` (a full `schemaField` URN), plus `parameters.fieldPath` |

Either the documentation or the response should move. `src/halflife/timeline.py`
accepts both shapes.

---

## 4. `relatedAssets` rejects `schemaField` URNs with a 422

**Severity:** medium — surprising interaction between two documented features.

Timeline schema events target a `schemaField` URN. Passing that URN into a
Document's `relatedAssets` fails:

```
ERROR :: /relatedAssets/0/asset :: "Provided urn urn:li:schemaField:(...)" is invalid:
Entity type for urn: ... is not a valid destination for field path: /relatedAssets/*/asset
```

So the natural move — link an audit document to the exact field that changed —
is not possible, and the caller has to parse the parent dataset URN out of the
field URN itself. Allowing `schemaField` as a related asset, or documenting the
accepted entity types, would close the gap.

**Workaround:** `_linkable_asset()` in `src/halflife/actions.py` folds a
`schemaField` URN up to its dataset.

---

## 5. Glossary definition edits are reported as `DOCUMENTATION`

**Severity:** low — a documentation clarification.

Editing a glossary term's `definition` produces a `DOCUMENTATION` change event,
not `GLOSSARY_TERM`; that category covers terms being *attached to* entities.
This is defensible, but it is worth stating explicitly, because "notify me when
a business definition changes" is a common need and the obvious category is the
wrong one.

---

## Suggested contributions

1. Fix the `OWNERSHIP` enum handling, or document `OWNER` as the accepted value.
2. Honour `start`, or document that it is ignored and that callers must filter.
3. Reconcile the Timeline response schema with the docs.
4. Document which entity types `relatedAssets` accepts.
5. Note the `DOCUMENTATION` category's role in glossary definition changes.

Half-Life carries a regression test for each behaviour
(`tests/test_timeline.py`, `tests/test_actions.py`), so the workarounds can be
removed cleanly once any of these are fixed upstream.
