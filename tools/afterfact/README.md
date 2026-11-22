# AfterFact

The answer changed. Which late facts actually changed it?

AfterFact replays a small operational assignment using **what was effective** and
**what was known** at two different times. It then finds a small set of changed
facts that reproduces the new decision. Open the resulting HTML file to inspect
the assignments and the original event IDs behind the explanation.

No model, API key, server or private dataset. Python 3.11+ and its standard library.

## Run it

From this directory:

```sh
python main.py demo --out build/demo
python main.py replay examples/events.json --valid-at 50 --before 50 --after 100 --db build/facts.sqlite --out build/replay
python -m unittest discover -s tests -v
```

The first command writes `events.json`, `report.json` and `report.html`. The
second uses a persistent SQLite journal: repeating identical events is a no-op,
while reusing an ID with different contents rejects and rolls back the batch.
Without `--db`, replay uses a temporary journal and only the supplied events.
Optional editable install: `python -m pip install -e .`, then `afterfact --help`.

[Inspect the actual example report](examples/report.html) or
[read its JSON](examples/report.json).

## The example

Two maintenance crews can cover a panel and a pump. Later, an outage report arrives
that was effective before the decision, and another late record raises a valve's
priority. There is also an irrelevant label change.

Before: `panel -> crew-a`, `pump -> crew-b`, priority 16, travel cost 7.
After: `valve -> crew-b`, priority 8, travel cost 2.

Three facts changed. Only the outage and priority correction are needed to
reproduce the new assignment. Removing either retained correction gives a
different decision. This is demonstrated on synthetic input, not a real dispatch.

## Input contract

Input is a JSON array of complete state records, not partial patches:

```json
{"event_id":"pump-v1","kind":"job","entity":"pump","valid_at":10,"known_at":10,"payload":{"priority":6,"skill":"mechanical","deadline":10}}
```

- `kind`: `job` or `resource`. Identifiers use letters, digits, `.`, `_`, `-`.
- Times are nonnegative integer ticks in one consistent unit. `valid_at` is when
  a fact takes effect; `known_at` is when it becomes available in this replay.
  Imported knowledge times are supplied data, not an authenticated server clock.
- Job payload: positive `priority`, required `skill`, and nonnegative `deadline`.
- Resource payload: unique `skills`, boolean `available`, and `costs` mapping job
  IDs to nonnegative travel costs. A missing cost means no supported edge.
- Travel costs and deadlines must use the same unit. They are inputs, not routes
  computed by this program. Optional `label` is descriptive only.
- `payload: null` is a tombstone. Unknown fields and duplicate JSON keys fail.

At an effective cutoff and knowledge cutoff, the winning state is the greatest
`(valid_at, known_at, event_id)` visible on both axes. Event-ID lexical ordering
is an explicit deterministic tie rule, not a claim to resolve source authority.

## What is implemented

1. Atomic, idempotent SQLite event ingestion, conflict rejection and reopen.
2. Two-axis projection that does not leak late corrections into earlier knowledge.
3. Exact bitmask dynamic programming for one-resource/one-job assignment. First
   maximize covered priority, then minimize total travel cost, then choose the
   lexical assignment tuple. Availability, skills and deadlines are hard constraints.
4. Counterfactual replay of changed full-state facts. Repeated deletion finds a
   **deletion-1-minimal** explanation. That means no single retained correction can
   be removed, not that the set has globally minimum cardinality. It is an
   explanation relative to this model, not proof of real-world causality.
5. Offline, escaped HTML with source event IDs and the full replay JSON.

## Checks and limits

28 tests cover projection, exact matching, constraints, stable ties, duplicate
ingestion, rollback, persistence, malformed input, CLI replay and HTML escaping.
The optimizer is independently checked against exhaustive enumeration for
200 seeded, small assignment cases. The example's two-fact explanation is
replayed and each retained correction is individually tested for necessity.

Bounds: 10 resources, 32 active jobs, 10,000 journal events, 12 changed facts per
explanation and a 2 MB input file. Exceeding a bound fails rather than silently
using a heuristic. Complexity is exponential in resource count; this is an exact
small-case investigation tool, not a fleet-scale dispatch optimizer. No staffing
shifts, multi-job routes, stochastic travel times, authenticated ingestion,
multi-tenant service or production deployment is claimed.

## Where this fits

Temporal databases preserve history. An assignment solver chooses a plan. This
tool joins the two into a reproducible "why did yesterday's answer change?"
workflow and keeps the explanation attached to its source records. It is distinct
from FeedShrink's market-feed failure reduction and RuleSplit's packet-policy
equivalence checking, but lives beside them in the maintained tools collection.

The underlying ideas are established: see Martin Fowler's
[bitemporal history](https://martinfowler.com/articles/bitemporal-history.html),
SQLite's [atomic commit](https://www.sqlite.org/atomiccommit.html), and Andreas
Zeller's [delta debugging](https://www.debuggingbook.org/html/DeltaDebugger.html).
This project does not claim to have invented temporal databases, matching or
causal inference. Independent project built with AI assistance and executable
tests; no Palantir SDK, client data or employer affiliation.
