# LedgerLens Architecture

One FalkorDB instance, one graph per bank, two agents, one fixed tool menu.
No vector store, no sidecar database, no retrieval layer — the graph is the
context layer, the memory, and the audit log.

```
                        ┌──────────────────────────────────────────────┐
                        │           FalkorDB (multigraph)              │
                        │                                              │
   bank_aurora ─┐       │   DATA          MEMORY            PROCEDURAL  │
   bank_nimbus ─┼──────▶│   Account       Case              Playbook    │
   bank_verdant ─┘       │   Person        Finding           PlaybookStep│
                        │   Device        Session                      │
                        │   Address       Message          EPISODIC    │
                        │   Merchant      (per-session     action/audit│
                        │   Transaction    chain)            trail      │
                        │   Alert           ▲                          │
                        │   Case            │ HANDS_OFF                 │
                        │   Action          │                          │
                        └──────┬───────────┴───────────────────────────┘
                               │  GRAPH.RO_QUERY (reads)
                               │  GRAPH.QUERY  (audited writes)
                    ┌──────────┴───────────┐
                    │    ledgerlens/tools  │   22 fixed tools, hand-written
                    │  (validated args,    │   Cypher, typed results
                    │   typed error shapes)│
                    └──────┬───────┬───────┘
                           │       └────────────────┐
                 ┌─────────▼──┐           ┌────────▼─────────┐
                 │  intake-   │ HANDS_OFF │ case-investigator │
                 │  analyst   │──────────▶│ freeze/escalate/  │
                 │  triage,   │  (edge)   │ findings/close    │
                 │  open_case │           └────────▲──────────┘
                 └────────────┘                    │
                           ▲        ┌───────────────┴──┐
                           └────────│  supervisor      │
                                    │ investigate_alert│
                                    │ ask_question     │
                                    └──────┬───────────┘
                     FastAPI /api/* ────────┤
                     MCP server (stdio) ────┤  same tool registry
                     console (static HTML) ──┘
```

## The agent loop

Both agents run the same loop (`ledgerlens/agents.py`):

1. The supervisor creates a `Session` node (episodic memory frame) and
   persists the assignment as the first message of the session's chain.
2. The agent gets its **role system prompt** and a **least-privilege subset of
   the tool menu**: the analyst can read everything and `open_case`, but cannot
   freeze; the investigator can act, but only after a handoff.
3. Loop (max 14 rounds): model → tool calls → validated arguments → typed
   results. Every call is appended to the session's message chain
   (`Message`-[:SAID_IN]→`Session`, chained with `NEXT`).
4. The final message must end with a JSON verdict that names its **answer
   shape**, confidence, and an evidence-citing summary.

### The handoff

`open_case` is the handoff trigger: it creates the `Case`, links the alerts
and accounts, and creates the case's session. The supervisor then writes the
`:HANDS_OFF` edge between the analyst's session and a fresh investigator
session — coordination state that any future session (or the console) can
query, not a hidden function call.

## Answer shapes

Every final answer carries one of five shapes, enforced by the tool layer's
typed errors and the prompts:

- `with_path` — the graph held the relationship; hops shown.
- `from_memory` — a past session established it; the date it was learned is attached.
- `not_in_graph` — entities exist, the relationship doesn't. A finding in itself,
  not "everything is fine".
- `unknown_entity` — the entity is not in the graph, so no query runs at all.
- `action` — an audited write happened (`Action` node linked to the case).

## Design laws (and why)

- **The model never writes Cypher.** A query-writing agent is an unexplainable
  agent. The menu is fixed, written by a person, reviewable in `CYPHER.md`.
- **Arguments are validated against the graph first.** `validate_entities`
  runs before any query touches an entity id — wrong ids die with
  `unknown_entity`, not with prose.
- **Reads use `GRAPH.RO_QUERY`.** Enforced in the runner: every read tool goes
  through one read-only path.
- **Writes are audited.** `freeze_account` / `escalate_case` create an `Action`
  node with actor, reason and timestamp, linked to the case. An investigation
  leaves a subgraph you can read back.
- **The negative control matters.** The seeded bank includes a high-value but
  legitimate, isolated account. An agent that freezes everything is worthless;
  the tests assert the control stays active (`tests/test_agent_llm.py`).

## Projections: why `TRANSFER` and `LINKED_TO` edges exist

FalkorDB algorithms (`algo.WCC`, `algo.pageRank`, `algo.maxFlow`, …) run over
direct node-to-node edges. The world is richer:

- `Transaction` **nodes** keep the audit trail (every transfer is a record).
- `TRANSFER` **edges** are the per-account-pair aggregation of those records
  (amount summed, count kept). One edge per ordered pair also satisfies
  `algo.maxFlow`'s simple-adjacency requirement.
- `LINKED_TO` **edges** are the association projection: two accounts share a
  device, address or owner. Fraud-ring components are found over these plus
  money flow; a household that shares a laptop is a component too — size and
  internal money flow separate them, and the agent is told to use both.

## Concurrency

FalkorDB is Redis-backed: high-concurrency reads and writes are native. The
test suite runs 24 parallel reads across the three tenants plus concurrent
case/finding writes (`tests/test_concurrency.py`) — each writer gets its own
case id, no cross-talk, no lock in application code.

## What LedgerLens deliberately does not do

- It does not invent entity names, balances, or links; an id the graph does
  not know produces `unknown_entity`, not a guess.
- It does not let the model write, edit, or compose queries.
- It does not rank people or teams; it ranks accounts by measured money-flow
  position (pageRank / betweenness) inside an evidenced component.
- It does not act without evidence: freezing requires an evidenced reason that
  is stored on the `Action` node.
- It is not a general chatbot: outside the tool menu, it has no opinions.

## Runtime

- **Local dev**: FalkorDB on `127.0.0.1:17287` (docker or the extracted
  binary), agent LLM via any OpenAI-compatible endpoint.
- **Deployment**: `docker-compose.yml` runs FalkorDB + the app on an internal
  network; the app is the only public surface (reverse-proxied), with
  `FALKORDB_HOST=falkordb` inside the compose network. The graph persists in
  the `falkordb-data` volume; seeding runs only when the instance is empty.
