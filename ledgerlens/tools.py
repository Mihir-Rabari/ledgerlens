"""The LedgerLens tool menu.

The agent never writes Cypher. Every tool here is a hand-written query with a
JSON schema; the model only picks a tool and fills validated arguments. This is
deliberate (see ARCHITECTURE.md): a query-writing agent is an unexplainable
agent, and a wrong argument should fail against the graph, not inside prose.

Conventions:
- Reads go through ``conn.read`` (``GRAPH.RO_QUERY``) — enforced by the runner.
- Writes are deliberate, audited mutations (case / memory / action tools).
- Every tool that receives an entity id first verifies the entity exists; a
  miss returns the ``unknown_entity`` shape instead of running anything.
- Results are plain JSON-serializable dicts with a one-line ``summary`` so the
  agent (and the console) can show exactly what walked.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .graph import LensConnection

ANSWER_SHAPES = ("with_path", "from_memory", "not_in_graph", "unknown_entity", "action")


class ToolError(Exception):
    """Structured tool failure. ``shape`` selects the answer protocol."""

    def __init__(self, shape: str, detail: str):
        super().__init__(detail)
        self.shape = shape
        self.detail = detail


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _rows(result) -> list[dict]:
    """Flatten a FalkorDB result into [{col: value}] with node properties expanded."""
    names = []
    for c in (result.header or []):
        if isinstance(c, (tuple, list)) and len(c) >= 2:
            names.append(str(c[1]))
        elif hasattr(c, "name"):
            names.append(str(c.name))
        else:
            names.append(str(c))
    out = []
    for row in result.result_set:
        item: dict[str, Any] = {}
        for name, value in zip(names, row, strict=False):
            if hasattr(value, "properties"):  # Node or Edge
                item[name] = dict(value.properties)
            else:
                item[name] = value
        out.append(item)
    return out


def _scalar(result, col: int = 0):
    row = result.result_set[0] if result.result_set else None
    return row[col] if row is not None else None


# ---------------------------------------------------------------------------
# Argument validation against the graph (the guide's law: validate before run)
# ---------------------------------------------------------------------------

_VALIDATE_QUERY = """
UNWIND $rows AS r
OPTIONAL MATCH (a:Account {id: r.id})
OPTIONAL MATCH (p:Person {id: r.id})
OPTIONAL MATCH (d:Device {fp: r.id})
RETURN r.id AS id,
       a.id IS NOT NULL AS is_account,
       p.id IS NOT NULL AS is_person,
       d.fp IS NOT NULL AS is_device
"""


def validate_entities(conn: LensConnection, tenant: str, ids: list[str]) -> list[dict]:
    """Return existence rows for each id. Used to enforce the unknown-entity shape."""
    if not ids:
        return []
    result = conn.read(tenant, _VALIDATE_QUERY, {"rows": [{"id": i} for i in ids]})
    return _rows(result)


def require_account(conn: LensConnection, tenant: str, account_id: str) -> None:
    rows = validate_entities(conn, tenant, [account_id])
    if not rows or not rows[0]["is_account"]:
        raise ToolError("unknown_entity", f"account {account_id!r} is not in this bank's graph")


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------

_Q_PROFILE = """
MATCH (a:Account {id: $id})
OPTIONAL MATCH (p:Person)-[:OWNS]->(a)
OPTIONAL MATCH (a)-[:ACCESSED_FROM]->(d:Device)
OPTIONAL MATCH (a)-[:REGISTERED_AT]->(x:Address)
OPTIONAL MATCH (al:Alert {status: 'open'})-[:ABOUT]->(a)
RETURN a.id AS id, a.name AS name, a.kind AS kind, a.kyc_risk AS kyc_risk, a.status AS status,
       a.opened_at AS opened_at, a.home_country AS country,
       collect(DISTINCT p.name) AS owners,
       collect(DISTINCT d.fp) AS devices,
       collect(DISTINCT x.city) AS cities,
       collect(DISTINCT al.id) AS open_alerts
"""


_Q_POLICIES = """
MATCH (d:PolicyDoc)-[:HAS_CHUNK]->(c:PolicyChunk)
WHERE c.id IN $ids
RETURN d.id AS policy, d.title AS title, d.version AS version, d.effective AS effective,
       c.id AS chunk, c.idx AS idx, c.text AS text
ORDER BY d.id, toInteger(c.idx)
"""


def t_get_policy_chunks(conn: LensConnection, tenant: str, args: dict) -> dict:
    """Fetch policy chunks by id (for citing a rule the agent must follow)."""
    rows = _rows(conn.read(tenant, _Q_POLICIES, {"ids": args["chunk_ids"]}))
    return {"data": {"chunks": rows},
            "summary": f"{len(rows)} policy section(s): "
                       + ", ".join(sorted({r['chunk'] for r in rows}))}


def t_search_policies(conn: LensConnection, tenant: str, args: dict) -> dict:
    """Company knowledge search: compliance policies by keyword. Answers cite
    the policy id, version and effective date."""
    rows = _rows(conn.read(tenant, _Q_FT_POLICY, {"text": args["text"]}))
    return {"data": {"sections": rows},
            "summary": f"policy recall for {args['text']!r}: {len(rows)} section(s)"}


_Q_FT_POLICY = """
CALL db.idx.fulltext.queryNodes('PolicyChunk', $text) YIELD node
MATCH (d:PolicyDoc)-[:HAS_CHUNK]->(node)
RETURN d.id AS policy, d.title AS title, d.version AS version, d.effective AS effective,
       node.id AS chunk, node.idx AS idx, node.text AS text
"""


def t_account_profile(conn: LensConnection, tenant: str, args: dict) -> dict:
    require_account(conn, tenant, args["account_id"])
    rows = _rows(conn.read(tenant, _Q_PROFILE, {"id": args["account_id"]}))
    r = rows[0] if rows else {}
    return {"data": r, "summary": f"Profile of {r.get('name')} ({r.get('kind')}, kyc_risk {r.get('kyc_risk')})"}


_Q_ACTIVITY = """
MATCH (a:Account {id: $id})
OPTIONAL MATCH (a)-[t:TRANSFER]->(out:Account)
OPTIONAL MATCH (in:Account)-[t2:TRANSFER]->(a)
WITH a,
     collect(DISTINCT {to: out.id, name: out.name, amount: t.amount, at: t.at, count: t.count}) AS outs,
     collect(DISTINCT {from: in.id, name: in.name, amount: t2.amount, at: t2.at, count: t2.count}) AS ins
RETURN a.id AS id,
       [x IN outs WHERE x.to IS NOT NULL] AS outgoing,
       [x IN ins WHERE x.from IS NOT NULL] AS incoming
"""


def t_account_activity(conn: LensConnection, tenant: str, args: dict) -> dict:
    require_account(conn, tenant, args["account_id"])
    rows = _rows(conn.read(tenant, _Q_ACTIVITY, {"id": args["account_id"]}))
    r = rows[0] if rows else {"outgoing": [], "incoming": []}
    n_out = len(r["outgoing"])
    n_in = len(r["incoming"])
    return {
        "data": r,
        "summary": f"{n_in} distinct senders in, {n_out} distinct receivers out (aggregated per account pair)",
    }


_Q_LINKED = """
MATCH (a:Account {id: $id})-[l:LINKED_TO]-(b:Account)
RETURN b.id AS account, b.name AS name, b.status AS status,
       l.via AS via, l.via_id AS via_id
ORDER BY b.id
"""


def t_linked_accounts(conn: LensConnection, tenant: str, args: dict) -> dict:
    require_account(conn, tenant, args["account_id"])
    rows = _rows(conn.read(tenant, _Q_LINKED, {"id": args["account_id"]}))
    return {
        "data": {"associations": rows},
        "summary": f"{len(rows)} association links (shared device/address/owner) touching other accounts",
    }


_Q_WCC = """
CALL algo.WCC({nodeLabels: ['Account'], relationshipTypes: ['LINKED_TO']})
YIELD node, componentId
WITH componentId, collect(node) AS members
WHERE size(members) >= $min
RETURN componentId AS component_id, size(members) AS size, [m IN members | m.id] AS member_ids
ORDER BY size DESC
"""

_Q_COMPONENT_MONEY = """
UNWIND $members AS mid
MATCH (a:Account {id: mid})-[t:TRANSFER]->(b:Account)
WHERE b.id IN $members
RETURN count(t) AS internal_edges, coalesce(sum(t.amount), 0.0) AS internal_amount
"""


def t_find_rings(conn: LensConnection, tenant: str, args: dict) -> dict:
    """Component detection over the association projection (WCC), enriched with
    internal money-flow density so the agent can tell a fraud ring from a
    household that shares a device."""
    min_size = int(args.get("min_size", 3))
    comps = _rows(conn.read(tenant, _Q_WCC, {"min": min_size}))
    enriched = []
    for comp in comps:
        money = _rows(conn.read(tenant, _Q_COMPONENT_MONEY,
                                {"members": comp["member_ids"]}))
        m = money[0] if money else {"internal_edges": 0, "internal_amount": 0.0}
        enriched.append({
            "component_id": comp["component_id"],
            "size": comp["size"],
            "member_ids": comp["member_ids"],
            "internal_transfer_edges": m["internal_edges"],
            "internal_transfer_amount": m["internal_amount"],
        })
    return {
        "data": {"components": enriched},
        "summary": f"{len(enriched)} account group(s) of >= {min_size} linked accounts "
                   f"(shared device/address/owner); internal money flow shown per group",
    }


_Q_PAGERANK_MEMBERS = """
CALL algo.pageRank('Account', 'TRANSFER')
YIELD node, score
WHERE node.id IN $members
RETURN node.id AS account, node.name AS name, score
ORDER BY score DESC
"""

_Q_BETWEENNESS_MEMBERS = """
CALL algo.betweenness({nodeLabels: ['Account'], relationshipTypes: ['TRANSFER']})
YIELD node, score
WHERE node.id IN $members
RETURN node.id AS account, node.name AS name, score
ORDER BY score DESC
"""


def t_rank_ring_accounts(conn: LensConnection, tenant: str, args: dict) -> dict:
    members = args["member_ids"]
    existing = validate_entities(conn, tenant, members)
    missing = [m for m, row in zip(members, existing, strict=False) if not (row["is_account"] or row["is_person"] or row["is_device"])]
    if missing:
        raise ToolError("unknown_entity", f"not in graph: {', '.join(missing)}")
    pr = _rows(conn.read(tenant, _Q_PAGERANK_MEMBERS, {"members": members}))
    bt = _rows(conn.read(tenant, _Q_BETWEENNESS_MEMBERS, {"members": members}))
    return {
        "data": {"pagerank": pr, "betweenness": bt},
        "summary": "Hub ranking inside the group: pageRank = money-flow importance, "
                   "betweenness = pass-through broker position",
    }


_Q_TRACE = """
MATCH (a:Account {id: $from}), (b:Account {id: $to})
CALL algo.SPpaths({sourceNode: a, targetNode: b, relTypes: ['TRANSFER'],
                   relDirection: 'outgoing', maxLen: $max_len, pathCount: 3})
YIELD path, pathWeight, pathCost
RETURN [n IN nodes(path) | n.id] AS route,
       [r IN relationships(path) | r.amount] AS leg_amounts,
       pathWeight AS hops
"""


def t_trace_money_path(conn: LensConnection, tenant: str, args: dict) -> dict:
    require_account(conn, tenant, args["from_account_id"])
    require_account(conn, tenant, args["to_account_id"])
    rows = _rows(conn.read(tenant, _Q_TRACE,
                           {"from": args["from_account_id"], "to": args["to_account_id"],
                            "max_len": int(args.get("max_hops", 6))}))
    if not rows:
        raise ToolError("not_in_graph",
                        f"no transfer path of <= {args.get('max_hops', 6)} hops from "
                        f"{args['from_account_id']} to {args['to_account_id']} — the graph does not know "
                        f"this money relationship, which is itself a finding")
    return {
        "data": {"paths": rows},
        "summary": f"{len(rows)} shortest money route(s) traced "
                   f"({' -> '.join(rows[0]['route']) if rows else 'n/a'})",
    }


_Q_MAXFLOW = """
MATCH (a:Account {id: $from}), (b:Account {id: $to})
CALL algo.maxFlow({sourceNodes: [a], targetNodes: [b],
                   relationshipTypes: ['TRANSFER'], capacityProperty: 'amount'})
YIELD maxFlow
RETURN maxFlow
"""


def t_money_flow_capacity(conn: LensConnection, tenant: str, args: dict) -> dict:
    require_account(conn, tenant, args["from_account_id"])
    require_account(conn, tenant, args["to_account_id"])
    rows = _rows(conn.read(tenant, _Q_MAXFLOW,
                           {"from": args["from_account_id"], "to": args["to_account_id"]}))
    cap = rows[0]["maxFlow"] if rows else 0.0
    return {
        "data": {"max_flow": cap},
        "summary": f"Maximum amount that could funnel {args['from_account_id']} -> "
                   f"{args['to_account_id']} along current edges: {cap:,.2f}",
    }


_Q_EXPLAIN = """
MATCH p = (a:Account {id: $a})-[:LINKED_TO|TRANSFER*..5]-(b:Account {id: $b})
RETURN [n IN nodes(p) | coalesce(n.id, n.name)] AS via_nodes,
       [r IN relationships(p) | type(r)] AS via_edges,
       length(p) AS hops
ORDER BY hops ASC
LIMIT 3
"""


def t_explain_connection(conn: LensConnection, tenant: str, args: dict) -> dict:
    require_account(conn, tenant, args["account_id_a"])
    require_account(conn, tenant, args["account_id_b"])
    rows = _rows(conn.read(tenant, _Q_EXPLAIN, {"a": args["account_id_a"], "b": args["account_id_b"]}))
    if not rows:
        raise ToolError(
            "not_in_graph",
            f"the graph knows no relationship between {args['account_id_a']} and {args['account_id_b']} "
            f"within 5 hops — no shared device, address, owner or money edge was ever recorded",
        )
    return {
        "data": {"paths": rows},
        "summary": f"shortest connection: {len(rows[0]['via_edges'])} hops "
                   f"({' - '.join(rows[0]['via_nodes'])})",
    }


_Q_FT_FINDING = "CALL db.idx.fulltext.queryNodes('Finding', $text) YIELD node RETURN node.id AS id, node.text AS text, node.at AS learned_at, node.confidence AS confidence"
_Q_FT_CASE = "CALL db.idx.fulltext.queryNodes('Case', $text) YIELD node RETURN node.id AS id, node.title AS title, node.outcome AS outcome, node.status AS status, node.closed_at AS closed_at"
_Q_FT_ALERT = "CALL db.idx.fulltext.queryNodes('Alert', $text) YIELD node RETURN node.id AS id, node.summary AS summary, node.status AS status, node.at AS at"


def t_search_memory(conn: LensConnection, tenant: str, args: dict) -> dict:
    """Semantic memory recall: fulltext search over findings, cases and alert
    summaries recorded in past sessions. Answers from here carry learned_at."""
    text = args["text"]
    findings = _rows(conn.read(tenant, _Q_FT_FINDING, {"text": text}))
    cases = _rows(conn.read(tenant, _Q_FT_CASE, {"text": text}))
    alerts = _rows(conn.read(tenant, _Q_FT_ALERT, {"text": text}))
    n = len(findings) + len(cases) + len(alerts)
    return {
        "data": {"findings": findings, "cases": cases, "alerts": alerts},
        "summary": f"memory recall for {text!r}: {n} match(es) across findings, cases and past alerts",
    }


_Q_PLAYBOOK = """
MATCH (p:Playbook {kind: $kind})-[:STEP]->(s:PlaybookStep)
RETURN s.order AS step, s.action AS action, s.instruction AS instruction,
       s.source AS source, s.learned_at AS learned_at
ORDER BY toInteger(s.order)
"""


def t_get_playbook(conn: LensConnection, tenant: str, args: dict) -> dict:
    kind = args["playbook"].strip().lower().replace("_", "-")
    rows = _rows(conn.read(tenant, _Q_PLAYBOOK, {"kind": kind}))
    if not rows:
        raise ToolError("not_in_graph", f"no playbook named {args['playbook']!r} — this alert kind has no SOP yet")
    return {"data": {"playbook": kind, "steps": rows},
            "summary": f"procedural memory: {len(rows)}-step playbook for {kind}"}


_Q_ALERTS = """
MATCH (x:Alert)-[:ABOUT]->(a:Account)
WHERE x.status = $status
RETURN x.id AS id, x.kind AS kind, x.severity AS severity, x.at AS at, x.amount AS amount,
       x.status AS status, x.summary AS summary, a.id AS account, a.name AS account_name
ORDER BY x.severity DESC, x.at DESC
"""


def t_list_alerts(conn: LensConnection, tenant: str, args: dict) -> dict:
    rows = _rows(conn.read(tenant, _Q_ALERTS, {"status": args.get("status", "open")}))
    return {"data": {"alerts": rows}, "summary": f"{len(rows)} alert(s) with status {args.get('status', 'open')}"}


_Q_ALERT = """
MATCH (x:Alert {id: $id})-[:ABOUT]->(a:Account)
OPTIONAL MATCH (c:Case)-[:INVESTIGATES]->(x)
RETURN x.id AS id, x.kind AS kind, x.severity AS severity, x.at AS at, x.amount AS amount,
       x.status AS status, x.summary AS summary, a.id AS account, a.name AS account_name,
       collect(DISTINCT c.id) AS cases
"""


def t_get_alert(conn: LensConnection, tenant: str, args: dict) -> dict:
    rows = _rows(conn.read(tenant, _Q_ALERT, {"id": args["alert_id"]}))
    if not rows:
        raise ToolError("unknown_entity", f"alert {args['alert_id']!r} does not exist")
    return {"data": rows[0], "summary": f"alert {args['alert_id']} ({rows[0]['kind']}, severity {rows[0]['severity']})"}


_Q_CASE = """
MATCH (c:Case {id: $id})
OPTIONAL MATCH (c)-[:INVESTIGATES]->(x:Alert)
OPTIONAL MATCH (c)-[:INVOLVES]->(a:Account)
OPTIONAL MATCH (c)-[:HAS_FINDING]->(f:Finding)
OPTIONAL MATCH (ac:Action)-[:RECORDED_IN]->(c)
RETURN c.id AS id, c.title AS title, c.status AS status, c.severity AS severity,
       c.opened_at AS opened_at, c.closed_at AS closed_at, c.outcome AS outcome,
       collect(DISTINCT x.id) AS alerts, collect(DISTINCT a.id) AS accounts,
       collect(DISTINCT {text: f.text, at: f.at, confidence: f.confidence}) AS findings,
       collect(DISTINCT {kind: ac.kind, at: ac.at, reason: ac.reason, by: ac.by}) AS actions
"""


def t_get_case(conn: LensConnection, tenant: str, args: dict) -> dict:
    rows = _rows(conn.read(tenant, _Q_CASE, {"id": args["case_id"]}))
    if not rows:
        raise ToolError("unknown_entity", f"case {args['case_id']!r} does not exist")
    findings = [f for f in rows[0]["findings"] if f.get("text")]
    actions = [a for a in rows[0]["actions"] if a.get("kind")]
    rows[0]["findings"] = findings
    rows[0]["actions"] = actions
    return {"data": rows[0], "summary": f"case {args['case_id']}: {rows[0]['title']} ({rows[0]['status']})"}


_Q_CASES = """
MATCH (c:Case)
RETURN c.id AS id, c.title AS title, c.status AS status, c.severity AS severity,
       c.opened_at AS opened_at, c.closed_at AS closed_at
ORDER BY c.opened_at DESC
"""


def t_list_cases(conn: LensConnection, tenant: str, args: dict) -> dict:
    status = args.get("status", "all")
    if status and status != "all":
        rows = _rows(conn.read(tenant,
                               "MATCH (c:Case) WHERE c.status = $status "
                               "RETURN c.id AS id, c.title AS title, c.status AS status, c.severity AS severity, "
                               "c.opened_at AS opened_at, c.closed_at AS closed_at ORDER BY c.opened_at DESC",
                               {"status": status}))
    else:
        rows = _rows(conn.read(tenant, _Q_CASES))
    return {"data": {"cases": rows}, "summary": f"{len(rows)} case(s) with status {status}"}


_Q_STATS_NODES = """
MATCH (n)
RETURN labels(n)[0] AS label, count(n) AS count
ORDER BY count DESC
"""
_Q_STATS_EDGES = """
MATCH ()-[r]->()
RETURN type(r) AS edge, count(r) AS count
ORDER BY count DESC
"""


def t_graph_stats(conn: LensConnection, tenant: str, args: dict) -> dict:
    nodes = _rows(conn.read(tenant, _Q_STATS_NODES))
    edges = _rows(conn.read(tenant, _Q_STATS_EDGES))
    return {"data": {"nodes": nodes, "edges": edges},
            "summary": f"tenant graph: {sum(n['count'] for n in nodes)} nodes, "
                       f"{sum(e['count'] for e in edges)} edges across {len(nodes)} labels"}


_Q_COMPONENT_ADJ = """
UNWIND $members AS mid
MATCH (a:Account {id: mid})
OPTIONAL MATCH (a)-[l:LINKED_TO]-(b:Account)
WHERE b.id IN $members
WITH a, collect(DISTINCT {id: b.id, via: l.via, via_id: l.via_id}) AS assoc,
     [x IN collect(DISTINCT b.id) WHERE x IS NOT NULL] AS assoc_ids
OPTIONAL MATCH (a)-[t:TRANSFER]->(m:Account)
WHERE m.id IN $members
WITH a, assoc, assoc_ids,
     collect(DISTINCT {id: m.id, amount: t.amount, count: t.count}) AS transfers_out
RETURN a.id AS account, a.name AS name, a.status AS status,
       [x IN assoc WHERE x.id IS NOT NULL] AS assoc,
       assoc_ids,
       [x IN transfers_out WHERE x.id IS NOT NULL] AS transfers_out
"""


def t_component_graph(conn: LensConnection, tenant: str, args: dict) -> dict:
    """Adjacency for the console's ring visualiser: association edges plus
    internal money-flow edges."""
    members = args["member_ids"]
    rows = _rows(conn.read(tenant, _Q_COMPONENT_ADJ, {"members": members}))
    nodes = [{"id": r["account"], "name": r["name"], "status": r["status"]} for r in rows]
    edges = []
    transfers = []
    for r in rows:
        for other in r["assoc_ids"]:
            edges.append({"source": r["account"], "target": other})
        for t in r["transfers_out"]:
            transfers.append({"source": r["account"], "target": t["id"],
                              "amount": t["amount"], "count": t["count"]})
    return {"data": {"nodes": nodes, "edges": edges, "transfers": transfers},
            "summary": f"component adjacency for {len(nodes)} accounts "
                       f"({len(edges)} associations, {len(transfers)} internal money edges)"}


# ---------------------------------------------------------------------------
# Write tools (audited mutations)
# ---------------------------------------------------------------------------

def t_open_case(conn: LensConnection, tenant: str, args: dict) -> dict:
    now = _now()
    case_id = f"CASE-{uuid.uuid4().hex[:10].upper()}"
    session_id = f"SES-{uuid.uuid4().hex[:10].upper()}"
    conn.write(tenant, "CREATE (c:Case {id: $id, title: $title, status: 'open', severity: $severity, "
                       "opened_at: $now, outcome: ''})",
               {"id": case_id, "title": args["title"], "severity": args.get("severity", 3), "now": now})
    conn.write(tenant, "CREATE (s:Session {id: $sid, agent: $agent, started_at: $now})",
               {"sid": session_id, "agent": args.get("agent", "case-investigator"), "now": now})
    conn.write(tenant, "MATCH (c:Case {id: $id}), (s:Session {id: $sid}) CREATE (c)-[:OPENED_IN]->(s)",
               {"id": case_id, "sid": session_id})
    if args.get("alert_ids"):
        conn.write(tenant, "UNWIND $rows AS r MATCH (c:Case {id: $id}), (x:Alert {id: r.x}) "
                           "CREATE (c)-[:INVESTIGATES]->(x)",
                   {"id": case_id, "rows": [{"x": a} for a in args["alert_ids"]]})
    if args.get("account_ids"):
        conn.write(tenant, "UNWIND $rows AS r MATCH (c:Case {id: $id}), (a:Account {id: r.a}) "
                           "CREATE (c)-[:INVOLVES]->(a)",
                   {"id": case_id, "rows": [{"a": a} for a in args["account_ids"]]})
    return {"data": {"case_id": case_id, "session_id": session_id},
            "summary": f"opened case {case_id}: {args['title']}"}


def t_add_finding(conn: LensConnection, tenant: str, args: dict) -> dict:
    now = _now()
    finding_id = f"FIND-{uuid.uuid4().hex[:10].upper()}"
    conn.write(tenant, "CREATE (f:Finding {id: $id, text: $text, at: $now, confidence: $confidence, source: $source})",
               {"id": finding_id, "text": args["text"], "now": now,
                "confidence": args.get("confidence", 0.7), "source": args.get("source", "live investigation")})
    conn.write(tenant, "MATCH (c:Case {id: $cid}), (f:Finding {id: $fid}) CREATE (c)-[:HAS_FINDING]->(f)",
               {"cid": args["case_id"], "fid": finding_id})
    conn.write(tenant, "MATCH (c:Case {id: $cid})-[:OPENED_IN]->(s:Session), (f:Finding {id: $fid}) "
                       "CREATE (s)-[:PRODUCED]->(f)",
               {"cid": args["case_id"], "fid": finding_id})
    if args.get("about_account_ids"):
        conn.write(tenant, "UNWIND $rows AS r MATCH (f:Finding {id: $fid}), (a:Account {id: r.a}) "
                           "CREATE (f)-[:ABOUT]->(a)",
                   {"fid": finding_id, "rows": [{"a": a} for a in args["about_account_ids"]]})
    if args.get("about_device_fps"):
        conn.write(tenant, "UNWIND $rows AS r MATCH (f:Finding {id: $fid}), (d:Device {fp: r.fp}) "
                           "CREATE (f)-[:ABOUT]->(d)",
                   {"fid": finding_id, "rows": [{"fp": f} for f in args["about_device_fps"]]})
    return {"data": {"finding_id": finding_id, "case_id": args["case_id"]},
            "summary": f"recorded finding {finding_id} in case {args['case_id']} (semantic memory)"}


def t_freeze_account(conn: LensConnection, tenant: str, args: dict) -> dict:
    require_account(conn, tenant, args["account_id"])
    now = _now()
    action_id = f"ACT-{uuid.uuid4().hex[:10].upper()}"
    conn.write(tenant, "MATCH (a:Account {id: $id}) SET a.status = 'frozen'",
               {"id": args["account_id"]})
    conn.write(tenant, "CREATE (x:Action {id: $aid, kind: 'freeze', at: $now, by: $by, reason: $reason})",
               {"aid": action_id, "now": now, "by": args.get("by", "case-investigator"),
                "reason": args["reason"]})
    conn.write(tenant, "MATCH (x:Action {id: $aid}), (a:Account {id: $acc}) CREATE (x)-[:ACTED_ON]->(a)",
               {"aid": action_id, "acc": args["account_id"]})
    if args.get("case_id"):
        conn.write(tenant, "MATCH (x:Action {id: $aid}), (c:Case {id: $cid}) CREATE (x)-[:RECORDED_IN]->(c)",
                   {"aid": action_id, "cid": args["case_id"]})
    return {"data": {"action_id": action_id, "account_id": args["account_id"]},
            "summary": f"froze {args['account_id']} — reason: {args['reason']}"}


def t_escalate_case(conn: LensConnection, tenant: str, args: dict) -> dict:
    now = _now()
    action_id = f"ACT-{uuid.uuid4().hex[:10].upper()}"
    conn.write(tenant, "CREATE (x:Action {id: $aid, kind: 'escalate', at: $now, by: $by, reason: $reason})",
               {"aid": action_id, "now": now, "by": args.get("by", "case-investigator"),
                "reason": args["reason"]})
    conn.write(tenant, "MATCH (x:Action {id: $aid}), (c:Case {id: $cid}) CREATE (x)-[:RECORDED_IN]->(c)",
               {"aid": action_id, "cid": args["case_id"]})
    conn.write(tenant, "MATCH (c:Case {id: $cid}) SET c.severity = 5", {"cid": args["case_id"]})
    return {"data": {"action_id": action_id, "case_id": args["case_id"]},
            "summary": f"escalated case {args['case_id']} to compliance — {args['reason']}"}


def t_close_case(conn: LensConnection, tenant: str, args: dict) -> dict:
    now = _now()
    conn.write(tenant, "MATCH (c:Case {id: $id}) SET c.status = 'closed', c.closed_at = $now, c.outcome = $outcome",
               {"id": args["case_id"], "now": now, "outcome": args["outcome"]})
    return {"data": {"case_id": args["case_id"], "outcome": args["outcome"]},
            "summary": f"closed case {args['case_id']}: {args['outcome']}"}


_Q_PLAYBOOK_APPEND = """
MATCH (p:Playbook {kind: $kind})
MATCH (c:Case {id: $case_id})
OPTIONAL MATCH (p)-[:STEP]->(s:PlaybookStep)
WITH p, c, coalesce(max(toInteger(s.order)), 0) AS highest
CREATE (step:PlaybookStep {order: highest + 1, action: 'learned', instruction: $text, source: $case_id, learned_at: $now})
CREATE (p)-[:STEP]->(step)
CREATE (step)-[:LEARNED_IN]->(c)
RETURN step.order AS order, step.instruction AS instruction
"""


def t_learn_lesson(conn: LensConnection, tenant: str, args: dict) -> dict:
    """Procedural memory evolution: append a learned step to a playbook, sourced
    to the case that taught it. Future investigations will follow it."""
    now = _now()
    case = _rows(conn.read(tenant, "MATCH (c:Case {id: $id}) RETURN c.id AS id", {"id": args["case_id"]}))
    if not case:
        raise ToolError("unknown_entity", f"case {args['case_id']!r} does not exist")
    kind = args["playbook"].strip().lower().replace("_", "-")
    rows = _rows(conn.write(tenant, _Q_PLAYBOOK_APPEND,
                            {"kind": kind, "case_id": args["case_id"], "text": args["text"], "now": now}))
    if not rows:
        raise ToolError("not_in_graph", f"no playbook named {args['playbook']!r} to learn into")
    return {"data": {"playbook": kind, "step": rows[0], "source_case": args["case_id"]},
            "summary": f"learned a new playbook step for {kind}: {args['text'][:80]}"
                       f" (sourced to case {args['case_id']})"}


def t_record_message(conn: LensConnection, tenant: str, args: dict) -> dict:
    """Persist a conversation turn as an episodic-memory node (chain per session)."""
    now = _now()
    msg_id = f"MSG-{uuid.uuid4().hex[:10].upper()}"
    conn.write(tenant, "CREATE (m:Message {id: $mid, role: $role, at: $now, text: $text})",
               {"mid": msg_id, "role": args["role"], "now": now, "text": args["text"][:4000]})
    conn.write(tenant, "MATCH (m:Message {id: $mid}), (s:Session {id: $sid}) CREATE (m)-[:SAID_IN]->(s)",
               {"mid": msg_id, "sid": args["session_id"]})
    conn.write(tenant, "MATCH (prev:Message)-[:SAID_IN]->(s:Session {id: $sid}) "
                       "WHERE NOT ()-[:NEXT]->(prev) AND prev.id <> $mid "
                       "CREATE (prev)-[:NEXT]->(m:Message {id: $mid})",
               {"sid": args["session_id"], "mid": msg_id})
    return {"data": {"message_id": msg_id}, "summary": f"persisted {args['role']} turn to session {args['session_id']}"}


_Q_SESSIONS = """
MATCH (s:Session)
OPTIONAL MATCH (prev:Session)-[:HANDS_OFF]->(s)
OPTIONAL MATCH (s)-[:PRODUCED]->(f:Finding)
OPTIONAL MATCH (s)<-[:SAID_IN]-(m:Message)
RETURN s.id AS id, s.agent AS agent, s.started_at AS started_at,
       collect(DISTINCT prev.id) AS handed_from,
       count(DISTINCT f) AS findings,
       count(m) AS messages
ORDER BY s.started_at DESC
LIMIT 30
"""


def t_list_sessions(conn: LensConnection, tenant: str, args: dict) -> dict:
    """Episodic memory timeline: sessions, who handed off to whom, what each
    session produced and said. This is the multi-agent coordination picture."""
    rows = _rows(conn.read(tenant, _Q_SESSIONS))
    return {"data": {"sessions": rows},
            "summary": f"{len(rows)} session(s); "
                       + str(sum(1 for r in rows if r["handed_from"])) + " received a handoff"}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

@dataclass
class Tool:
    name: str
    description: str
    handler: Callable
    kind: str  # 'read' | 'write'
    schema: dict = field(default_factory=dict)


TOOLS: dict[str, Tool] = {}


def _register(name: str, description: str, kind: str, schema: dict) -> Callable:
    def deco(fn):
        TOOLS[name] = Tool(name=name, description=description, handler=fn, kind=kind, schema=schema)
        return fn
    return deco


_register(
    "get_account_profile",
    "Profile of one account: owners, devices seen, registered cities, KYC risk, status, open alerts.",
    "read",
    {"type": "object", "properties": {"account_id": {"type": "string", "description": "Account id, e.g. AUR-ACC-0950"}},
     "required": ["account_id"]},
)(t_account_profile)

_register(
    "get_account_activity",
    "Money activity of one account: distinct senders in and receivers out, with aggregated amounts and dates.",
    "read",
    {"type": "object", "properties": {"account_id": {"type": "string"}}, "required": ["account_id"]},
)(t_account_activity)

_register(
    "find_linked_accounts",
    "All accounts sharing a device, address or owner with the given account (association projection).",
    "read",
    {"type": "object", "properties": {"account_id": {"type": "string"}}, "required": ["account_id"]},
)(t_linked_accounts)

_register(
    "find_rings",
    "Fraud-ring candidates: connected components over shared-device/address/owner associations, "
    "with internal money-flow density to separate rings from benign households. min_size >= 3 recommended.",
    "read",
    {"type": "object", "properties": {"min_size": {"type": "integer", "default": 3}},
     "required": []},
)(t_find_rings)

_register(
    "rank_ring_accounts",
    "Rank members of a suspected ring: pageRank (money-flow importance) and betweenness (broker position). "
    "Pass the member account ids returned by find_rings.",
    "read",
    {"type": "object", "properties": {"member_ids": {"type": "array", "items": {"type": "string"}}},
     "required": ["member_ids"]},
)(t_rank_ring_accounts)

_register(
    "trace_money_path",
    "Shortest money routes (up to 3) between two accounts along TRANSFER edges, with leg amounts.",
    "read",
    {"type": "object",
     "properties": {"from_account_id": {"type": "string"}, "to_account_id": {"type": "string"},
                    "max_hops": {"type": "integer", "default": 6}},
     "required": ["from_account_id", "to_account_id"]},
)(t_trace_money_path)

_register(
    "money_flow_capacity",
    "Maximum amount that could funnel from one account to another given current edge capacities (max-flow).",
    "read",
    {"type": "object",
     "properties": {"from_account_id": {"type": "string"}, "to_account_id": {"type": "string"}},
     "required": ["from_account_id", "to_account_id"]},
)(t_money_flow_capacity)

_register(
    "explain_connection",
    "Why are two accounts connected at all? Shortest relationship path (shared device/address/owner or money), if any.",
    "read",
    {"type": "object",
     "properties": {"account_id_a": {"type": "string"}, "account_id_b": {"type": "string"}},
     "required": ["account_id_a", "account_id_b"]},
)(t_explain_connection)

_register(
    "search_memory",
    "Search investigation memory from past sessions: findings, case outcomes, past alerts. "
    "Use simple keywords (e.g. 'device ring', a person or account name, 'structured').",
    "read",
    {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
)(t_search_memory)

_register(
    "search_policies",
    "Search the bank's compliance policies (company knowledge in the graph): thresholds, "
    "device rules, freeze authority. Multi-word queries need every word present — prefer "
    "one or two strong keywords ('freeze', 'structuring', 'device'). "
    "Cite the section id (e.g. POL-31-C01) in conclusions.",
    "read",
    {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
)(t_search_policies)

_register(
    "get_policy_chunks",
    "Fetch policy sections by chunk id (e.g. ['POL-31-C01', 'POL-22-C02']) to quote exactly.",
    "read",
    {"type": "object", "properties": {"chunk_ids": {"type": "array", "items": {"type": "string"}}},
     "required": ["chunk_ids"]},
)(t_get_policy_chunks)

_register(
    "get_playbook",
    "Get the procedural-memory playbook (SOP steps) for this alert kind, e.g. 'shared-device', 'structuring', 'rapid-velocity'.",
    "read",
    {"type": "object", "properties": {"playbook": {"type": "string"}}, "required": ["playbook"]},
)(t_get_playbook)

_register(
    "list_alerts",
    "List alerts by status ('open' default, or 'closed').",
    "read",
    {"type": "object", "properties": {"status": {"type": "string", "default": "open"}}, "required": []},
)(t_list_alerts)

_register(
    "get_alert",
    "One alert with its account and any cases that already investigate it.",
    "read",
    {"type": "object", "properties": {"alert_id": {"type": "string"}}, "required": ["alert_id"]},
)(t_get_alert)

_register(
    "get_case",
    "One case with alerts, involved accounts, findings and recorded actions.",
    "read",
    {"type": "object", "properties": {"case_id": {"type": "string"}}, "required": ["case_id"]},
)(t_get_case)

_register(
    "list_cases",
    "List cases by status ('open' or 'closed' or 'all').",
    "read",
    {"type": "object", "properties": {"status": {"type": "string", "default": "all"}}, "required": []},
)(t_list_cases)

_register(
    "list_sessions",
    "Episodic memory timeline: sessions with agents, handoffs received, findings produced, message counts.",
    "read",
    {"type": "object", "properties": {}, "required": []},
)(t_list_sessions)

_register(
    "graph_stats",
    "Node and edge counts for this tenant's graph.",
    "read",
    {"type": "object", "properties": {}, "required": []},
)(t_graph_stats)

_register(
    "component_graph",
    "Adjacency (nodes + association edges) for a set of account ids — used to visualise a ring.",
    "read",
    {"type": "object", "properties": {"member_ids": {"type": "array", "items": {"type": "string"}}},
     "required": ["member_ids"]},
)(t_component_graph)

_register(
    "open_case",
    "Open an investigation case (audited write): links alerts and accounts, creates the case's session.",
    "write",
    {"type": "object",
     "properties": {"title": {"type": "string"}, "severity": {"type": "integer", "default": 3},
                    "alert_ids": {"type": "array", "items": {"type": "string"}},
                    "account_ids": {"type": "array", "items": {"type": "string"}},
                    "agent": {"type": "string", "default": "case-investigator"}},
     "required": ["title"]},
)(t_open_case)

_register(
    "add_finding",
    "Record a finding in a case (semantic memory write). Findings persist for every future session.",
    "write",
    {"type": "object",
     "properties": {"case_id": {"type": "string"}, "text": {"type": "string"},
                    "confidence": {"type": "number", "default": 0.7},
                    "about_account_ids": {"type": "array", "items": {"type": "string"}},
                    "about_device_fps": {"type": "array", "items": {"type": "string"}}},
     "required": ["case_id", "text"]},
)(t_add_finding)

_register(
    "freeze_account",
    "Freeze an account (audited action write). Only act on evidence the graph shows.",
    "write",
    {"type": "object",
     "properties": {"account_id": {"type": "string"}, "reason": {"type": "string"}, "case_id": {"type": "string"}},
     "required": ["account_id", "reason"]},
)(t_freeze_account)

_register(
    "escalate_case",
    "Escalate a case to compliance review (audited action write).",
    "write",
    {"type": "object",
     "properties": {"case_id": {"type": "string"}, "reason": {"type": "string"}},
     "required": ["case_id", "reason"]},
)(t_escalate_case)

_register(
    "close_case",
    "Close a case with an outcome text. The outcome becomes searchable memory.",
    "write",
    {"type": "object", "properties": {"case_id": {"type": "string"}, "outcome": {"type": "string"}},
     "required": ["case_id", "outcome"]},
)(t_close_case)

_register(
    "learn_lesson",
    "Append a lesson learned to a playbook (procedural memory evolution). The step is "
    "sourced to the case that taught it and every future investigation will follow it. "
    "Use when closing a case taught you something the playbook lacked.",
    "write",
    {"type": "object",
     "properties": {"case_id": {"type": "string"},
                    "playbook": {"type": "string", "description": "playbook kind, e.g. 'rapid-velocity'"},
                    "text": {"type": "string", "description": "the step, written as an instruction"}},
     "required": ["case_id", "playbook", "text"]},
)(t_learn_lesson)

_register(
    "record_message",
    "Persist a conversation turn into the session's episodic message chain.",
    "write",
    {"type": "object", "properties": {"session_id": {"type": "string"}, "role": {"type": "string"},
                                      "text": {"type": "string"}},
     "required": ["session_id", "role", "text"]},
)(t_record_message)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_tool(conn: LensConnection, tenant: str, name: str, args: dict) -> dict:
    tool = TOOLS.get(name)
    if tool is None:
        return {"ok": False, "error": {"shape": "unknown_tool", "detail": f"no tool named {name!r}"}}
    try:
        result = tool.handler(conn, tenant, args or {})
        return {"ok": True, "tool": name, "kind": tool.kind, **result}
    except ToolError as exc:
        return {"ok": False, "error": {"shape": exc.shape, "detail": exc.detail}}


def tool_specs() -> list[dict]:
    """OpenAI-style function specs; the same menu is exposed over MCP."""
    return [
        {"type": "function",
         "function": {"name": t.name, "description": t.description, "parameters": t.schema}}
        for t in TOOLS.values()
    ]


def tool_catalog() -> list[dict]:
    """Machine-readable catalog for docs generation and the console."""
    return [{"name": t.name, "kind": t.kind, "description": t.description, "schema": t.schema}
            for t in TOOLS.values()]
