# AI-Assistance Disclosure

As required by Graph Hacks rule 11 (and in the spirit of rules 12–13), this
project was built with AI coding assistance, and the use is disclosed here in
detail.

## What AI assistance did

- **Implementation**: significant parts of the Python codebase (tool layer,
  agent loop, seed generator, FastAPI service, console UI, tests) were drafted
  with an AI coding agent (Claude/GLM-class models driven by Hermes Agent),
  working from the human's product direction and feedback.
- **Infrastructure work**: the local FalkorDB runtime for development was
  extracted from the official Docker image without a daemon (the dev machine
  has no root), and FalkorDB v6's algorithm API was mapped empirically
  (signatures verified against the running server, not assumed from docs).
- **Docs drafts**: this file, the README, ARCHITECTURE.md, GRAPH-MODEL.md and
  the generated CYPHER.md were drafted with AI assistance and reviewed.
- **Testing**: the pytest suite was drafted with AI assistance and — critically —
  every test was actually executed against the live FalkorDB instance, and the
  full agent tests were executed against the live LLM endpoint. All green at
  submission time (see the repo's README "Verification" claims).

## What the human did

- Chose the product direction (fraud-ring investigation with persistent case
  memory, Tracks 1 + 2), the domain, and the design laws the agent follows.
- Reviewed the graph model, the tool menu, and the queries the product depends
  on (CYPHER.md exists precisely so this review is possible).
- Set the honesty rules: fixed tool menu, no model-written Cypher, typed answer
  shapes, negative controls, and the "not in graph is a finding" protocol.
- Verified the end-to-end behaviour on the seeded banks and owns the submission.

## Understanding (rule 12)

I can explain, without the assistant present:

- the graph model above: every node/edge type, the two projections
  (`TRANSFER` and `LINKED_TO`) and why they exist (algorithms need direct
  edges; `algo.maxFlow` needs simple adjacency);
- every query in CYPHER.md: what it matches, what it returns, and where the
  product calls it;
- the agent architecture: the supervisor, the two roles, the least-privilege
  tool subsets, the `HANDS_OFF` edge as coordination state, and the answer
  shapes;
- the memory model: episodic (sessions/messages), semantic (findings + fulltext
  indexes), procedural (playbooks) — all in the same per-tenant graph;
- why FalkorDB is load-bearing: remove it and there is no data layer, no memory,
  no algorithms, no audit trail — nothing the product does survives.

The project would not qualify as "entirely generated without meaningful
participant contribution": the contribution is the design, the direction, the
verification, and the ownership of every decision above.
