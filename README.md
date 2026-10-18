# LedgerLens

![License](https://img.shields.io/badge/license-MIT-blue)
![Tests](https://img.shields.io/badge/tests-44%2F44%20passing-brightgreen)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![FalkorDB](https://img.shields.io/badge/FalkorDB-v6-red)

**A fraud-ring investigator with a memory — one FalkorDB graph per bank is the entire context layer.**

An alert lands in the queue. Before touching today's transactions, the case investigator
searches investigation memory — and surfaces a case that was closed eight days earlier:
same ring pattern, overlapping device fingerprints, a full findings trail behind it.
Today's alert isn't a new ring. It's a recurrence. The agent says so, cites the old case
with the date it was learned, and today's investigation takes a different path than it
would have on day one.

There's no trick behind that moment. No vector store, no sidecar database, no retrieval
layer bolted onto a chatbot. The "memory" is a fulltext query over `Finding` and `Case`
nodes in the same graph that holds the bank's data. Data, memory, SOPs, and the audit
trail behind every answer — one graph per tenant, nothing else.

- 🎬 **Demo video:** [github.com/Mihir-Rabari/ledgerlens/releases/tag/v1.0-demo](https://github.com/Mihir-Rabari/ledgerlens/releases/tag/v1.0-demo)
- 📝 **Build story:** [BLOG.md](BLOG.md)

## Why a graph

"Which accounts are linked to this flagged transaction?" is not a lookup — it is a
traversal through shared devices, addresses, owners and money edges. A graph stores
those relationships as first-class things, so the agent follows recorded connections
instead of guessing, and the path it walked is the explanation it owes the compliance
team.

## How it thinks

The agent **never writes Cypher**. It picks from a fixed menu of 26 tools; a person
wrote the query inside each one, arguments are validated against the graph before
anything runs (a wrong id dies as `unknown_entity`, not a confident guess), and every
read goes through the read-only `GRAPH.RO_QUERY` path. The bank's compliance policies
are chunked into the graph (`POL-14`, `POL-22`, `POL-31`…), fulltext-searchable
alongside findings and playbooks; the agent is instructed to fetch exact chunks
(`POL-31-C01`) and cite them in freeze reasons and reports.

Every final answer carries one of five shapes, so the console can never produce a
confident sentence nobody can check:

| Shape | Meaning |
|---|---|
| `with_path` | The graph held the relationship; the hops walked are shown alongside |
| `from_memory` | A past session established this; the date it was learned is attached |
| `not_in_graph` | Entities exist but nothing connects them the way the question assumed — itself a finding |
| `unknown_entity` | The entity is not in the graph, so no query runs at all |
| `action` | A deliberate, audited write (freeze / escalate / open or close a case) |

Discipline counts as much as action: every seeded bank includes a high-value, legitimate,
completely isolated account — the kind an over-eager agent would freeze to look busy.
The investigator examines it and refuses: verdict `no_case`. And because a refusal is
also knowledge, clearances persist as `Finding` nodes — a later session recalls the
verdict, the finding id, and the date it was learned.

## What the graph does

- **Multi-hop reasoning** — shared-device/address/owner association projection
  (`LINKED_TO`) plus aggregated money-flow edges (`TRANSFER`), so a household that
  shares a laptop is distinguishable from a ring by size and internal flow
- **Graph algorithms as agent tools** — `algo.WCC` (ring components), `algo.pageRank`
  (hub ranking), `algo.betweenness` (broker accounts), `algo.SPpaths` (up to three
  money routes with leg amounts), `algo.maxFlow` (funnel capacity)
- **Memory across sessions** — episodic (sessions + persisted message chains),
  semantic (findings, fulltext-searchable, confidence-scored), procedural
  (investigation playbooks; closing a case can `learn_lesson` and append a sourced
  step every future investigation follows)
- **Two-agent handoff** — an intake analyst (read anything, open cases, cannot
  freeze) hands off to a case investigator (freeze, escalate, close) through a
  queryable `:HANDS_OFF` edge, not a hidden function call
- **Per-tenant isolation** — every bank is one graph inside a single FalkorDB
  instance (FalkorDB's multigraph topology); slugs are validated so no query can
  cross tenants and the API 403s cross-tenant requests
- **Auth is graph-native** — users and login events are nodes too (scrypt +
  HMAC session cookies, zero external auth dependencies); even the audit trail of
  who signed in is a query
- **Explainability** — every tool result carries its query trail; every write is
  audited as an `Action` node linked to its case

## Measured on real runs

All numbers below are from actual runs against seeded banks (~192 persons, ~285
accounts, 1,133 transactions per tenant) on a dev box — not spec-sheet promises.

**Tests:** 44/44 passing, including 3 live-LLM agent tests that assert planted
ground truth is found (and nothing that wasn't planted).

**Tool calls per investigation** (4-parallel bench across two tenants):

| Outcome | Tool calls | Wall time |
|---|---|---|
| `no_case` (refused to act) | 11 | 120s |
| `froze_and_escalated` (ring takedown) | 37–62 | 221–409s |

**Query latency** (median of 25 runs per query, seeded ~2,100-node graph):

| Query | Median | p95 |
|---|---|---|
| Memory fulltext search | 0.37 ms | 0.52 ms |
| 3-hop money-path traversal | 0.53 ms | 0.70 ms |
| 1-hop association links | 0.58 ms | 0.72 ms |
| `algo.pageRank` over TRANSFER | 1.94 ms | 2.85 ms |
| `algo.maxFlow` funnel capacity | 46.9 ms | 57.8 ms |
| `algo.WCC` ring components (whole graph) | 397.5 ms | 498.2 ms |

Memory recall is a sub-millisecond query — fast enough to run on every step of the
agent loop.

## Quickstart

```bash
# 1. Run FalkorDB (database + browser UI on :3000)
docker run --rm -p 17287:6379 -p 13000:3000 falkordb/falkordb:latest

# 2. Install + seed three synthetic banks (deterministic, fully synthetic data)
uv venv && uv pip install -e ".[dev]"
cp .env.example .env  # point FALKORDB_* at your instance, add LLM_* credentials
python seed.py --wipe

# 3. Serve the app (login screen + authenticated investigator console)
uvicorn app:app --reload --port 8788
```

Sign in at `http://localhost:8788` — demo accounts `analyst@aurora` /
`admin@ledgerlens.io`, password `ledgerlens123` (you can also register your own
analyst on the login screen). Analysts are pinned to their bank — the backend
403s any cross-tenant request — while admins can switch banks and run the
4-way parallel stress bench. Every login attempt lands as a `LoginEvent` node
in the platform graph; the account menu shows your audit trail.

The MCP server (`python -m ledgerlens.mcp_server`) exposes the same tool menu
over MCP for any client.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `FALKORDB_HOST` / `FALKORDB_PORT` | `127.0.0.1` / `17287` | FalkorDB instance |
| `FALKORDB_USERNAME` / `FALKORDB_PASSWORD` | empty | FalkorDB Cloud / auth deployments |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | — | Any OpenAI-compatible endpoint the agent uses |
| `LL_AUTH_SECRET` | dev default | HMAC secret for session cookies — override in any real deployment |

## Docs

- `GRAPH-MODEL.md` — the full node/edge vocabulary and why it is shaped that way
- `CYPHER.md` — every query the product depends on, generated from the live tool registry
- `ARCHITECTURE.md` — the agent loop, the handoff protocol, the honesty rules
- `BLOG.md` — the build story

## AI-assistance transparency

This project was built with AI coding assistance (implementation, testing, and
documentation drafts), reviewed, understood, and owned by the maintainer, who can
explain the graph model, the queries, and every architectural decision.
See [AI-DISCLOSURE.md](AI-DISCLOSURE.md) for the full breakdown of what was
AI-assisted and what was human-directed.

## License

MIT — see [LICENSE](LICENSE).
