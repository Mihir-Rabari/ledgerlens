# The Alert Was a Relapse: Building a Fraud Investigator That Remembers

*My LedgerLens build story for WeMakeDevs × FalkorDB Graph Hacks 2026 — entered in Track 1 (Agents That Act on Connected Data) and Track 2 (Agent Memory and Coordination).*

In a live demo run, LedgerLens did the thing I built it for. A shared-device alert lands in the queue. Before touching today's transactions, the case investigator searches investigation memory — and surfaces a case that had been closed eight days earlier: the same ring pattern, overlapping device fingerprints, a full findings trail behind it. Today's alert isn't a new ring. It's a recurrence. The agent says so, cites the old case with the date it was learned, and today's investigation takes a different path than it would have on day one.

There's no trick behind that moment. No vector store, no sidecar database, no retrieval layer bolted onto a chatbot. The "memory" is a fulltext query over `Finding` and `Case` nodes in the same graph that holds the bank's data. LedgerLens is a fraud-ring investigator where one FalkorDB graph per bank is the entire context layer — data, memory, SOPs, and audit trail in a single graph.

The demo runs on three deterministic synthetic banks — roughly 190 persons, 280 accounts, and 1,130 transactions each — with two planted fraud rings and one planted trap I'll get to.

## Graphs, not retrieval

"Which accounts are linked to this flagged transaction?" is not a lookup. It's a traversal through shared devices, addresses, owners, and money edges. Text retrieval guesses at relevance from fragments; a graph follows recorded connections — and when an agent decides to freeze an account, the path it walked is the explanation it owes the compliance team.

So the core commitment: FalkorDB isn't a component of LedgerLens, it *is* the product's whole context. One instance hosts one graph per tenant (`bank_aurora`, `bank_nimbus`, `bank_verdant`) using FalkorDB's multigraph topology. Isolation is the graph key: every handle is `select_graph("bank_<slug>")` with the slug validated against a strict pattern, so no query can cross tenants and there's zero extra infrastructure. Remove FalkorDB and nothing survives — no data layer, no memory, no algorithms, no audit trail.

## Law one: the model never writes Cypher

A query-writing agent is an unexplainable agent: every answer would depend on a query nobody reviewed, generated under a prompt nobody fully controls. So the agent picks from a fixed menu of 26 tools — a person wrote the query inside each one — and `CYPHER.md` is generated from the live tool registry: every query the product depends on, published as a reviewable artifact.

Three enforcement layers keep the menu honest:

- **Arguments are validated against the graph before anything runs.** `validate_entities` checks ids first; a wrong id dies as an `unknown_entity` result, not a confident guess.
- **Reads go through one read-only path.** Every read tool runs via `GRAPH.RO_QUERY`, enforced in the runner.
- **Writes are audited.** `freeze_account` and `escalate_case` create an `Action` node with actor, reason, and timestamp, linked to the case. An investigation leaves a subgraph you can read back.

The agent is instructed to cite policy by section id in every freeze reason and report: the bank's compliance policies are chunked into the graph (`POL-14`, `POL-22`, `POL-31`…), fulltext-searchable alongside findings and playbooks, and it fetches exact chunks (`POL-31-C01`) to quote them. An answer with sources, or no answer.

## Law two: every answer has a shape

The final message of every session must carry a JSON verdict naming its answer shape, enforced by typed errors in the tool layer:

| Shape | Meaning |
|---|---|
| `with_path` | The graph held the relationship; the hops walked are shown alongside |
| `from_memory` | A past session established this; the date it was learned is attached |
| `not_in_graph` | Entities exist, but nothing connects them the way the question assumed — itself a finding |
| `unknown_entity` | The entity is not in the graph, so no query runs at all |
| `action` | A deliberate, audited write (freeze / escalate / open or close a case) |

Two of these are failure modes turned into protocol. `not_in_graph` blocks the classic "couldn't find a connection, everything looks fine" — a missing relationship is a finding, not an absence of findings. `unknown_entity` blocks hallucination at the source: if the id isn't in the graph, no query executes, so nothing can be invented around it. With shapes enforced, a demo can't produce a confident sentence nobody can check.

## Law three: the negative control

Every seeded bank includes a high-value, legitimate, completely isolated account — fresh device, fresh address, no ring links — exactly the kind of balance an over-eager agent would freeze to look busy. An agent that freezes everything is worthless; discipline matters as much as action. The investigator examines it and refuses to act: verdict `no_case`. The live-LLM test suite asserts the control stays untouched, every run.

## Algorithms as agent tools — and the projections that feed them

FalkorDB's graph algorithms are exposed to the agent like any other tool:

- **`algo.WCC`** over the association projection → ring components
- **`algo.pageRank` + `algo.betweenness`** over money flow → hub and broker ranking inside a component
- **`algo.SPpaths`** → up to three shortest money routes, with leg amounts
- **`algo.maxFlow`** → funnel capacity between two accounts

```cypher
MATCH (a:Account {id: $from}), (b:Account {id: $to})
CALL algo.maxFlow({sourceNodes: [a], targetNodes: [b],
                   relationshipTypes: ['TRANSFER'], capacityProperty: 'amount'})
YIELD maxFlow
RETURN maxFlow
```

The algorithms want direct node-to-node edges, but the world is richer: every transfer is a `Transaction` node, because the audit trail matters. So there are two projections. `TRANSFER` edges aggregate transactions per ordered account pair (amount summed, count kept) — one edge per pair also satisfies `algo.maxFlow`'s simple-adjacency requirement. `LINKED_TO` edges are the association projection: two accounts share a device, an address, or an owner. Rings are found over `LINKED_TO` plus internal money density, because a household that shares a laptop is a connected component too — size and internal flow separate a ring from a family.

One v6 gotcha worth documenting: the algorithm API isn't uniform. Most procedures take a config map — `algo.WCC({nodeLabels: ['Account'], relationshipTypes: ['LINKED_TO']})` — but `algo.pageRank` still wants positional arguments: `algo.pageRank('Account', 'TRANSFER')`. I mapped the signatures empirically against the running server rather than trusting the docs; the exact forms all live in `CYPHER.md`.

## Memory as graph structure

The honest way to do persistent memory is to make it graph structure, not a pile of JSON:

- **Episodic** — `Session` nodes with persisted `Message` chains (`SAID_IN`, `NEXT`). Each case opens in its own session, and the console renders a sessions timeline.
- **Semantic** — `Finding` nodes with confidence and timestamps, linked back to the entities they're about, fulltext-indexed alongside case titles/outcomes and alert summaries. `search_memory` recalls prior conclusions; answers from memory carry the date they were learned.
- **Procedural** — `Playbook` + `PlaybookStep`: the SOP retrieved before acting on each alert kind. The part I like most: closing a case can call `learn_lesson`, which appends a new step to the playbook, sourced to the case that taught it, timestamped — every future investigation follows it. Procedural memory that evolves, with a paper trail.

Because all of it is graph structure, a new session recalls prior sessions purely by querying; there is no other store to recall from. The seed includes a closed case from eight days ago whose ring recurs today, and the run that opened this post caught the recurrence via memory search. On day one that alert was a new ring; on day nine it was a known one with a history.

## The handoff is an edge

Two agents run the same loop under different privileges: an intake analyst (triage, read anything, open cases — but cannot freeze) and a case investigator (freeze, escalate, close — but only after a handoff). `open_case` is the trigger: the supervisor writes a `:HANDS_OFF` edge from the analyst's session to a fresh investigator session. Coordination state is a queryable edge, not a hidden function call.

## Running FalkorDB without a daemon

My dev box has no Docker daemon and no root — and FalkorDB v6 ships no prebuilt binaries. The README's `docker run falkordb/falkordb` was not an option.

But a Docker image is just layers behind an HTTP API. So I did what a browser does: talked to the Docker Registry directly — requested a pull token, fetched the image manifest, downloaded each layer blob, untarred them. Out came redis-server 8.10.2, `falkordb.so`, and the bundled libraries: the exact bits from the official image, running natively. No daemon, no root, no VM. Browsers don't get to have all the fun. (Real deployments use `docker-compose.yml`; the daemonless path is just how this box runs the same image bits.)

## Where it stands

Forty-four pytest tests are green, including the live-LLM agent tests. The seeded banks have planted ground truth (`tests/fixtures/planted_<tenant>.json`), and the tests assert the tools find exactly what was planted — and nothing that wasn't. FalkorDB is Redis-backed, so concurrency comes free: the demo runs four parallel investigations across the three tenants; the test suite runs 24 parallel reads plus concurrent case/finding writes — no cross-talk, no application-level locks. The MCP server exposes the same tool registry over stdio, so tool selection works from any MCP client, not just the built-in console.

Next: temporal edges — recurrence needs time, not just pattern — and letting algorithm outputs feed alert prioritization.

The repo is [github.com/Mihir-Rabari/ledgerlens](https://github.com/Mihir-Rabari/ledgerlens): clone it, start FalkorDB, `python seed.py --wipe` the three banks, and the console walks an alert from triage to verdict with the hops behind every conclusion on screen.
