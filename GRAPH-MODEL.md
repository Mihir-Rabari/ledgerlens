# The LedgerLens Graph Model

One graph per bank tenant (`bank_aurora`, `bank_nimbus`, `bank_verdant`) in a
single FalkorDB instance, plus one `ledgerlens_platform` graph for accounts
and login audit (below). Isolation is the graph key: no query can cross
tenants because every handle is `select_graph("bank_<slug>")` and the slug is
validated against a strict pattern.

The vocabulary below is the single source of truth (`ledgerlens/model.py`);
the seed (`seed.py`) instantiates it deterministically.

## Platform graph (`ledgerlens_platform`)

There is no sidecar database in LedgerLens — credentials live in the same
graph server as everything else:

- `(:User {id, username, full_name, tenant, role, password_hash, salt, created_at, last_login_at})`
  — `role` is `analyst` (pinned to their bank; every tenant-scoped API 403s
  cross-tenant requests) or `admin` (may switch tenants, runs the stress bench).
  Passwords are scrypt-hashed with per-user salts (stdlib `hashlib`); sessions
  are HMAC-SHA256 signed tokens in HttpOnly cookies (stdlib `hmac`) — the auth
  stack ships zero external dependencies.
- `(:User)-[:PERFORMED]->(:LoginEvent {id, at, ok, username})` — every login
  attempt is a graph event, successful or not, so the audit story the product
  tells about investigations extends to who signed in, when, and whether it
  worked. The console surfaces this per-user under the account menu.

## Data (the bank's world)

| Node | Properties | Role |
|---|---|---|
| `Bank` | name, code, country | tenant root |
| `Account` | id, name, kind, opened_at, kyc_risk, status, home_country | the investigated entity; `status` flips to `frozen` by audited action |
| `Person` | id, name, email, phone | account owner, ring organizer |
| `Device` | fp, os | fingerprints; shared devices are a top fraud signal |
| `Address` | id, city, country | shared registered addresses |
| `Merchant` | id, name, category | purchase destinations |
| `Transaction` | id, at, amount, currency, channel | the audit trail |
| `Alert` | id, kind, severity, at, amount, status, summary | work items from monitoring |

### Relationships (data)

| Edge | From → To | Meaning |
|---|---|---|
| `OWNS` | Person → Account | legal ownership |
| `ACCESSED_FROM` | Account → Device | device fingerprints seen on the account |
| `LIVES_AT` / `REGISTERED_AT` | Person/Account → Address | co-location signals |
| `FROM` / `TO` | Transaction → Account | record-level money movement |
| `AT` | Transaction → Merchant | purchase destination |
| `TRANSFER` | Account → Account {amount, at, channel, count} | **projection**: per-pair aggregation of the transaction records; feeds `algo.pageRank`, `algo.SPpaths`, `algo.maxFlow` (which requires simple adjacency) |
| `LINKED_TO` | Account → Account {via, via_id} | **projection**: association via shared device / address / owner; feeds `algo.WCC` ring detection |
| `ABOUT` | Alert → Account | which account the alert is on |

## Memory (what the agents keep)

The three memory types the briefs ask for, as first-class graph structure:

| Type | Where | How it is used |
|---|---|---|
| **Episodic** | `Session` nodes + `Message` chains (`SAID_IN`, `NEXT`) and per-case `Case → OPENED_IN → Session` | what happened, when, in which session — the handoff (`HANDS_OFF` edge) is episodic coordination state |
| **Semantic** | `Finding {id, text, at, confidence, source}` + `Case {outcome}` + fulltext indexes on `Finding.text`, `Case.title`, `Case.outcome`, `Alert.summary` | `search_memory` recalls prior conclusions; answers from memory carry the date they was learned |
| **Procedural** | `Playbook` + `PlaybookStep {order, action, instruction}` | the SOP the agents must follow for each alert kind — retrieved with `get_playbook`, before they act |

Findings link back to the entities they are about (`Finding -[:ABOUT]-> Account/Device`),
so a future session asking about an account finds everything concluded about it.

## Action (the audit trail)

| Node / Edge | Meaning |
|---|---|
| `Action {id, kind: freeze/escalate, at, by, reason}` | every deliberate act, with its evidence |
| `Action -[:ACTED_ON]-> Account` | what was acted on |
| `Action -[:RECORDED_IN]-> Case` | which case it belongs to |

## Case (the working unit)

`Case {id, title, status, severity, opened_at, closed_at, outcome}` with:
`INVESTIGATES → Alert`, `INVOLVES → Account`, `HAS_FINDING → Finding`.

The outcome text is written for fulltext recall: closing a case is how the
next session gets smarter.

## The fraud signals the graph is built to expose

| Signal | Graph shape | Tool that walks it |
|---|---|---|
| Shared device across "unrelated" accounts | Account → Device ← Account | `find_linked_accounts`, `find_rings` (WCC over `LINKED_TO`) |
| Shared address / owner clusters | Account → Address ← Account | `find_rings`, `explain_connection` |
| Structuring (repeated just-below-threshold) | many `TRANSFER` edges into one hub, small amounts | `get_account_activity`, `find_rings` (money density) |
| Funnel / hub control | hub tops pageRank + betweenness within the component | `rank_ring_accounts` |
| Money routes out of the ring | shortest paths along `TRANSFER` | `trace_money_path` (algo.SPpaths) |
| Funnel capacity | max-flow between two accounts | `money_flow_capacity` (algo.maxFlow) |
| Recurrence across sessions | today's alert matches a past `Finding`/`Case` via fulltext | `search_memory`, `get_case` |

## Seeded world (deterministic, synthetic)

`python seed.py --wipe` builds, per bank:

- ~190 persons, ~280 accounts, ~190 devices, 61 addresses, 12 merchants
- ~1,130 transactions (normal + purchases) plus per-pair `TRANSFER` edges
- **Ring A** (obvious): 1 hub + 6 mules, 2 shared ghost devices, one shared
  address, six sub-10k inbound legs — plus 3 mules secretly owned by two organizers
- **Ring B** (subtle): 5 senders structuring into a second hub, only 3 of 5
  sharing a device
- **Negative control**: a legitimate high-value account with a fresh device,
  fresh address, no ring links — the agent must *not* act on it
- **Past session**: a closed case from 8 days ago (with findings + actions +
  a `HANDS_OFF` handoff) whose ring *recurs* today — cross-session memory
  changes today's outcome
- Playbooks for every alert kind + fulltext indexes

Planted ground truth is written to `tests/fixtures/planted_<tenant>.json` and
the test suite asserts the tools find exactly what was planted — and nothing
that was not.
