# LedgerLens

**A graph-native fraud-ring investigator with persistent case memory, powered by FalkorDB.**

LedgerLens investigates suspicious-activity alerts at a bank. Its entire context — bank data,
investigation memory, SOPs, and the evidence behind every answer — lives in one FalkorDB graph
per tenant. The graph shapes what the agent does: it decides, acts (freeze / escalate / file),
and can show the exact hops behind each conclusion.

Built for the WeMakeDevs × FalkorDB **Graph Hacks 2026** hackathon, entered in **Track 1
(Agents That Act on Connected Data)** and **Track 2 (Agent Memory and Coordination)**.

- 🎬 **Demo video (3m55s):** [github.com/Mihir-Rabari/ledgerlens/releases/tag/v1.0-demo](https://github.com/Mihir-Rabari/ledgerlens/releases/tag/v1.0-demo)
- 📝 **Build-story blog post:** [BLOG.md](BLOG.md) (blog-prize entry)

## Why a graph

"Which accounts are linked to this flagged transaction?" is not a lookup — it is a traversal
through shared devices, addresses, owners and money edges. A graph stores those relationships
as first-class things, so the agent follows recorded connections instead of guessing, and the
path it walked is the explanation it owes you.

## How it thinks

The agent **never writes Cypher**. It picks from a fixed menu of 26 tools; a person wrote the
query inside each one, and arguments are validated against the graph before anything runs.
Every answer carries one of five shapes, so a demo can never produce a confident sentence
nobody can check:

| Shape | Meaning |
|---|---|
| `with_path` | The graph held the relationship; the hops walked are shown alongside |
| `from_memory` | A past session established this; the date it was learned is attached |
| `not_in_graph` | Entities exist but nothing connects them the way the question assumed — itself a finding |
| `unknown_entity` | The entity is not in the graph, so no query runs at all |
| `action` | A deliberate, audited write (freeze / escalate / open or close a case) |

### The graph does real work

- **Multi-hop reasoning**: shared-device/address/owner association projection + money-flow edges
- **Graph algorithms as agent tools**: `algo.WCC` (ring components), `algo.pageRank` (hub ranking),
  `algo.betweenness` (broker accounts), `algo.SPpaths` (money routes), `algo.maxFlow` (funnel capacity)
- **Memory across sessions** (Track 2): episodic (sessions + persisted message chains), semantic
  (findings, fulltext-searchable), procedural (investigation playbooks) — all in the graph
- **Multi-agent coordination** (Track 2): an intake analyst hands off to a case investigator
  through shared graph state; the handoff is an edge you can query
- **Per-tenant isolation** (Track 2): every bank is one graph inside a single FalkorDB instance —
  FalkorDB's multigraph topology, zero extra infrastructure
- **Explainability**: every tool result carries its query trail; every action is audited as an
  `Action` node linked to its case

## Quickstart

```bash
# 1. Run FalkorDB (database + browser UI on :3000)
docker run --rm -p 17287:6379 -p 13000:3000 falkordb/falkordb:latest

# 2. Install + seed three synthetic banks (deterministic, fully synthetic data)
uv venv && uv pip install -e ".[dev]"
cp .env.example .env  # point FALKORDB_* at your instance
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
The MCP server (`python -m ledgerlens.mcp_server`) exposes the same tool menu over
MCP for any client.

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
- `BLOG.md` — the build story (hackathon blog-post entry)

## AI-assistance disclosure

This project was built with AI coding assistance (disclosed per hackathon rule 11), including
implementation, testing, and documentation drafts — reviewed, understood, and owned by the
submitter, who can explain the graph model, the queries, and every architectural decision.
See `AI-DISCLOSURE.md`.

## License

MIT — see [LICENSE](LICENSE).
