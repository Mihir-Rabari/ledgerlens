# Graph Hacks 2026 — submission dossier

LedgerLens was built for **Graph Hacks: Give Your AI Agents Real Context**
(WeMakeDevs × FalkorDB, Oct 15–18, 2026). This page is for the event's
judges and staff — every rule requirement and where it lives, plus where each
track's key-focus criteria show up in the product. For the project itself,
start at the [README](README.md).

**Team 95Z5QJ "The Hybrid" — Mihirkumar Rabari (@mihirrabari), solo.**
**Tracks entered: 01 (Agents That Act on Connected Data) + 02 (Agent Memory
and Coordination).**

## Required artifacts → where they are

| Rule requirement | Location |
|---|---|
| Public source repository | you are here |
| README with setup instructions and graph data model | [README](README.md) quickstart · [GRAPH-MODEL.md](GRAPH-MODEL.md) for the full node/edge vocabulary |
| The Cypher queries and graph algorithms the product depends on | [CYPHER.md](CYPHER.md) — generated from the live tool registry, every query the agent can run |
| Demo video | [github.com/Mihir-Rabari/ledgerlens/releases/tag/v1.0-demo](https://github.com/Mihir-Rabari/ledgerlens/releases/tag/v1.0-demo) |
| Live deployment | **https://tries-breeding-unavailable-state.trycloudflare.com** — sign in `analyst@aurora` / `ledgerlens123` (admin: `admin@ledgerlens.io`). Served through a live tunnel; the README quickstart covers full local setup otherwise. |
| The track you are entering | both tracks — mapped below |

## Track 01 — Agents That Act on Connected Data

| Key-focus criterion | How LedgerLens meets it | Where to see it |
|---|---|---|
| Multi-hop reasoning | Association projection (`LINKED_TO`: shared device/address/owner) + aggregated money edges (`TRANSFER`); traversals follow recorded connections | Any investigation's evidence trail; `explain_connection` results with hops shown |
| Graph queries and algorithms as agent tools | `algo.WCC` (ring components), `algo.pageRank` (hubs), `algo.betweenness` (brokers), `algo.SPpaths` (money routes), `algo.maxFlow` (funnel capacity) — all behind the fixed 26-tool menu; the model never writes Cypher | Ring view in the console; `CYPHER.md` |
| Tool selection through MCP | `python -m ledgerlens.mcp_server` exposes the same registry over MCP stdio | `ledgerlens/mcp_server.py` |
| Actions based on what the graph shows | Freezes/escalations only on graph evidence; every write audited as an `Action` node; the isolated negative-control account is refused every run (`no_case`) | Watch any `froze_and_escalated` investigation end-to-end |
| Explainable results | Five typed answer shapes (`with_path`, `from_memory`, `not_in_graph`, `unknown_entity`, `action`); every answer carries its query trail | Final verdict card of any session |

## Track 02 — Agent Memory and Coordination

| Key-focus criterion | How LedgerLens meets it | Where to see it |
|---|---|---|
| Episodic, semantic, procedural memory | `Session` + persisted `Message` chains; `Finding` nodes (confidence-scored, fulltext-indexed); `Playbook`/`PlaybookStep` where closing a case can `learn_lesson` and append a sourced step | Sessions timeline in the console; `GRAPH-MODEL.md` |
| Persistent conversation history | Every session's message chain is graph structure — recall is a query, not a separate store | Ask about a past case in a fresh session; answers come back `from_memory` with the date learned |
| Shared state and handoffs between agents | Intake analyst (read-only + open case) hands off to case investigator (freeze/escalate/close) through a queryable `:HANDS_OFF` edge | Any investigation that escalates past triage |
| High-concurrency reads and writes | Redis-backed FalkorDB; test suite runs 24 parallel reads + concurrent writes; the demo runs 4 investigations in parallel with zero cross-talk | `tests/test_concurrency.py`; the admin bench button |
| Separate memory per user or tenant | One graph per bank (`bank_aurora`, `bank_nimbus`, `bank_verdant`) via multigraph topology; slugs validated; API 403s cross-tenant requests | Sign in as two different tenant analysts and compare |

The seeded data plants a closed case from eight days earlier whose ring
recurs today — the run in the demo video catches the recurrence via memory
search and says so, citing the old case and the date it was learned.

## A 10-minute judge walkthrough

1. Open the live deployment, sign in as `analyst@aurora` / `ledgerlens123`
2. Pick any severity-4/5 alert → watch the intake analyst triage, hand off, and the case investigator work the ring (WCC → pageRank → SPpaths → maxFlow all appear in the tool trail)
3. Open the ring view — hub and broker accounts ranked, exit nodes marked
4. Check the negative control: the isolated high-value account comes back `no_case`, and that refusal persists as a finding (discipline is memory too)
5. In the sessions timeline, find the closed case from eight days ago — then ask the console about it and watch the answer come back `from_memory`
6. (Optional) Sign in as `admin@ledgerlens.io` and run the 4-way parallel bench

## How FalkorDB is load-bearing

Remove FalkorDB and nothing survives: it is the data layer, the memory, the
SOP store, and the audit trail — there is no sidecar database in the stack.

- **Multi-tenant isolation via multigraph topology** — one instance, one graph per bank; isolation is the graph key
- **Memory as graph structure** — findings/cases/playbooks fulltext-searchable in the same graph as the data
- **Graph algorithms as ordinary tools** — WCC, pageRank, betweenness, SPpaths, maxFlow behind the tool menu
- **Honest read path** — every read via `GRAPH.RO_QUERY`; the agent cannot mutate on a read
- **Auth is graph-native** — users and login events are nodes too
- FalkorDB v6 algorithm signatures were mapped empirically against the running server (config-map vs positional forms); exact calls live in `CYPHER.md`

## Verified on real runs

- **Tests:** 44/44 passing, including 3 live-LLM agent tests asserting planted ground truth is found — and nothing that wasn't planted
- **Tool calls per investigation** (4-parallel bench): 11 to refuse a legitimate alert; 37–62 to take down a ring
- **Query latency** (seeded ~2,100-node graph, median of 25 runs): memory fulltext search 0.37 ms · 3-hop traversal 0.53 ms · `algo.pageRank` 1.94 ms · `algo.maxFlow` 46.9 ms
- All numbers measured on seeded synthetic banks (~192 persons, ~285 accounts, 1,133 transactions per tenant) — fully synthetic data, no real persons or transactions

## AI-assistance disclosure

This project was built with AI coding assistance, disclosed in detail in
[AI-DISCLOSURE.md](AI-DISCLOSURE.md) — including what was AI-drafted, what
was human-directed, and confirmation that the design, queries, and
architecture can be explained without the assistant present.
