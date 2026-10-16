"""The LedgerLens agents: an intake analyst and a case investigator.

Two agents, one shared graph. The analyst triages an alert against the
playbooks and past memory, opens a case when evidence warrants it, and hands
off. The investigator deep-dives the case — ranks the ring, traces money,
freezes accounts with evidence attached, records findings, closes with an
outcome. The handoff itself is a first-class graph edge (:HANDS_OFF between
sessions), so coordination state is queryable, not implied.

Design rules (from the answer protocol):
- tools are a fixed menu; the model picks and fills arguments, never writes queries
- least privilege: each agent sees only the tools its role needs
- every final answer must state one of the answer shapes with the evidence it walked
- if the LLM endpoint is not configured, we fail loudly rather than pretend
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from openai import OpenAI

from .config import CONFIG
from .graph import LensConnection
from .tools import TOOLS, run_tool

ANALYST_TOOLS = [
    "get_alert", "get_account_profile", "get_account_activity", "find_linked_accounts",
    "find_rings", "search_memory", "get_playbook", "list_alerts", "get_case",
    "explain_connection", "graph_stats", "open_case",
]

INVESTIGATOR_TOOLS = [
    "get_alert", "get_account_profile", "get_account_activity", "find_linked_accounts",
    "find_rings", "rank_ring_accounts", "trace_money_path", "money_flow_capacity",
    "explain_connection", "search_memory", "get_playbook", "get_case",
    "add_finding", "freeze_account", "escalate_case", "close_case",
]

ANALYST_SYSTEM = """You are LedgerLens's intake analyst at a bank's financial-crime unit.

An alert is assigned to you. Investigate it ONLY through the provided tools. You never invent
accounts, balances or links: if the graph does not show it, it does not exist. Every claim you
make must come from a tool result you can cite.

Process (the playbooks in the graph are the SOP — follow them):
1. get_alert, then get_playbook for its kind, then follow the playbook's steps in order.
2. Build the evidence: profile, activity, linked accounts, rings, past memory (search_memory).
3. Decide with discipline:
   - A ring/group with internal money flow + memory matches (or a clear shared-device chain)
     => open_case (this hands off to the investigator) and recommend severity.
   - An isolated, high-value-but-legitimate pattern with no links and no memory matches
     => do NOT open a case. State the honest verdict.

The final message MUST end with a JSON object on its own line:
{"shape": "with_path" | "from_memory" | "not_in_graph" | "unknown_entity",
 "verdict": "open_case" | "no_case", "confidence": 0.0-1.0,
 "summary": "one paragraph, citing the tool evidence by name"}

Be terse. Numbers over adjectives."""

INVESTIGATOR_SYSTEM = """You are LedgerLens's case investigator at a bank's financial-crime unit.

You inherit an open case from the intake analyst — the shared graph carries the state, and the
handoff is an edge you can query. Work the case ONLY through the provided tools. You never
invent accounts, balances or links: if the graph does not show it, it does not exist.

Process:
1. get_case to see alerts, involved accounts and prior findings; get the playbook and follow it.
2. Deep-dive: find_rings, rank_ring_accounts (hub detection), trace_money_path (where the money
   went), money_flow_capacity (how much the funnel can move), explain_connection for the key pairs.
3. search_memory: has a past session already established something about these accounts, people
   or devices? Answers that come from memory must say when they were learned.
4. Act with evidence (audited writes):
   - freeze_account ONLY for accounts the graph shows inside the ring/funnel — cite the exact
     evidence in the reason. Never freeze the negative-control-style isolated account.
   - escalate_case for the hub or anything needing compliance review.
   - add_finding for each conclusion future sessions should remember (link the entities).
   - close_case with an outcome written for fulltext recall by future sessions.

The final message MUST end with a JSON object on its own line:
{"shape": "with_path" | "from_memory" | "not_in_graph" | "unknown_entity" | "action",
 "verdict": "froze_and_escalated" | "escalated_only" | "cleared" | "needs_more_evidence",
 "confidence": 0.0-1.0, "summary": "one paragraph, citing the tool evidence by name"}

Be terse. Numbers over adjectives."""


class AgentError(Exception):
    pass


@dataclass
class ToolCallRecord:
    agent: str
    tool: str
    arguments: dict
    ok: bool
    summary: str
    data: dict | None = None
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))


@dataclass
class InvestigationResult:
    tenant: str
    alert_id: str
    analyst_session_id: str
    investigator_session_id: str | None = None
    case_id: str | None = None
    handoff: bool = False
    turns: list[ToolCallRecord] = field(default_factory=list)
    analyst_final: dict | None = None
    investigator_final: dict | None = None
    transcript: list[dict] = field(default_factory=list)


def _client() -> OpenAI:
    if not CONFIG.llm_ready:
        raise AgentError("LLM endpoint not configured (LLM_BASE_URL / LLM_API_KEY)")
    return OpenAI(base_url=CONFIG.llm_base_url, api_key=CONFIG.llm_api_key)


def _parse_final_json(text: str) -> dict | None:
    """Pull the required trailing JSON verdict out of the final message, leniently."""
    if not text:
        return None
    matches = re.findall(r"\{[^{}]*\}", text, re.S)
    for candidate in reversed(matches):
        try:
            parsed = json.loads(candidate)
            if "shape" in parsed:
                return parsed
        except json.JSONDecodeError:
            continue
    return None


def _allowed_tools(names: list[str]) -> list[dict]:
    return [{"type": "function",
             "function": {"name": TOOLS[n].name, "description": TOOLS[n].description,
                          "parameters": TOOLS[n].schema}}
            for n in names]


def _persist_turn(conn: LensConnection, tenant: str, session_id: str, agent: str, role: str, text: str) -> None:
    try:
        run_tool(conn, tenant, "record_message",
                 {"session_id": session_id, "role": role,
                  "text": f"[{agent}] {text}" if text else ""})
    except Exception:
        pass  # message persistence must never kill an investigation


def _run_agent_loop(conn: LensConnection, tenant: str, agent_name: str, allowed: list[str],
                    messages: list[dict], result: InvestigationResult) -> tuple[str, list[dict]]:
    """Run one agent to completion: tool-call rounds until a final message."""
    client = _client()
    tools = _allowed_tools(allowed)
    convo = list(messages)
    for _ in range(CONFIG.llm_max_tool_rounds):
        kwargs: dict[str, Any] = {
            "model": CONFIG.llm_model,
            "messages": convo,
            "tools": tools,
            "temperature": 0.2,
        }
        response = client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        assistant = choice.message
        if not (assistant.tool_calls and len(assistant.tool_calls) > 0):
            content = assistant.content or ""
            convo.append({"role": "assistant", "content": content})
            result.transcript.append({"agent": agent_name, "role": "assistant", "content": content})
            return content, convo
        convo.append({"role": "assistant", "tool_calls": [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in assistant.tool_calls]})
        for tc in assistant.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_res = run_tool(conn, tenant, tc.function.name, args)
            record = ToolCallRecord(agent=agent_name, tool=tc.function.name, arguments=args,
                                    ok=tool_res["ok"],
                                    summary=tool_res.get("summary") or tool_res.get("error", {}).get("detail", ""),
                                    data=tool_res.get("data"))
            result.turns.append(record)
            result.transcript.append({"agent": agent_name, "role": "tool",
                                      "tool": tc.function.name, "args": args,
                                      "ok": tool_res["ok"], "summary": record.summary})
            convo.append({"role": "tool", "tool_call_id": tc.id,
                          "content": json.dumps(tool_res)[:6000]})
    return "", convo


def _new_session(conn: LensConnection, tenant: str, agent: str) -> str:
    session_id = f"SES-{uuid.uuid4().hex[:10].upper()}"
    conn.write(tenant, "CREATE (s:Session {id: $id, agent: $agent, started_at: $now})",
               {"id": session_id, "agent": agent,
                "now": datetime.now(UTC).isoformat(timespec="seconds")})
    return session_id


ANSWERER_SYSTEM = """You are LedgerLens's graph answerer for a bank's financial-crime unit.

The user asks a question about this bank's graph. Answer ONLY through the provided tools.
You never invent accounts, balances or links: if the graph does not show it, it does not exist.

Rules:
- Follow connections across data with the tools; do not guess joins.
- If the answer was already established in a past session (search_memory / get_case), say so
  and attach the date it was learned — answers from memory must carry their learned date.
- If the entities exist but nothing connects them the way the question assumed, say exactly
  that: "the graph does not know this relationship", which is itself a finding.
- If an entity does not exist, say so; do not run speculative queries.

The final message MUST end with a JSON object on its own line:
{"shape": "with_path" | "from_memory" | "not_in_graph" | "unknown_entity",
 "confidence": 0.0-1.0, "summary": "the direct answer, one or two sentences"}

Be terse. Numbers over adjectives."""


def ask_question(conn: LensConnection, tenant: str, message: str,
                 session_id: str | None = None) -> dict:
    """One-agent Q&A loop over the read-only tool menu. The console's chat box."""
    if session_id is None:
        session_id = _new_session(conn, tenant, "graph-answerer")
    _persist_turn(conn, tenant, session_id, "graph-answerer", "user", message)
    holder = InvestigationResult(tenant=tenant, alert_id="", analyst_session_id=session_id)
    final_text, _ = _run_agent_loop(
        conn, tenant, "graph-answerer",
        [n for n in ANALYST_TOOLS if n != "open_case"],
        [{"role": "system", "content": ANSWERER_SYSTEM},
         {"role": "user", "content": message}],
        holder,
    )
    parsed = _parse_final_json(final_text) or {
        "shape": "not_in_graph", "confidence": 0.0, "summary": final_text[:500],
    }
    _persist_turn(conn, tenant, session_id, "graph-answerer", "assistant", final_text)
    return {
        "session_id": session_id,
        "answer_text": final_text,
        "answer": parsed,
        "turns": [vars(t) for t in holder.turns],
        "transcript": holder.transcript,
    }


def investigate_alert(conn: LensConnection, tenant: str, alert_id: str) -> InvestigationResult:
    """Supervisor: analyst triages; on evidence, hand off to the investigator."""
    alert = run_tool(conn, tenant, "get_alert", {"alert_id": alert_id})
    if not alert["ok"]:
        raise AgentError(alert["error"]["detail"])

    analyst_session = _new_session(conn, tenant, "intake-analyst")
    result = InvestigationResult(tenant=tenant, alert_id=alert_id, analyst_session_id=analyst_session)
    _persist_turn(conn, tenant, analyst_session, "intake-analyst", "user",
                  f"Investigate alert {alert_id}: {alert['data']['summary']}")

    analyst_messages = [
        {"role": "system", "content": ANALYST_SYSTEM},
        {"role": "user", "content": f"Alert {alert_id} is assigned to you. Investigate it now."},
    ]
    final_text, _ = _run_agent_loop(conn, tenant, "intake-analyst", ANALYST_TOOLS,
                                    analyst_messages, result)
    analyst_final = _parse_final_json(final_text)
    result.analyst_final = analyst_final
    _persist_turn(conn, tenant, analyst_session, "intake-analyst", "assistant", final_text)

    case_id = next((r.data.get("case_id") for r in result.turns
                    if r.tool == "open_case" and r.ok and r.data), None)
    if not case_id:
        result.analyst_final = analyst_final or {"shape": "not_in_graph", "verdict": "no_case",
                                                 "confidence": 0.0, "summary": final_text[:500]}
        return result

    result.case_id = case_id
    result.handoff = True
    investigator_session = _new_session(conn, tenant, "case-investigator")
    result.investigator_session_id = investigator_session
    conn.write(tenant, "MATCH (a:Session {id: $a}), (b:Session {id: $b}) CREATE (a)-[:HANDS_OFF]->(b)",
               {"a": analyst_session, "b": investigator_session})
    conn.write(tenant, "MATCH (c:Case {id: $c}), (s:Session {id: $s}) "
                       "CREATE (c)-[:OPENED_IN]->(s)",
               {"c": case_id, "s": investigator_session})

    investigator_messages = [
        {"role": "system", "content": INVESTIGATOR_SYSTEM},
        {"role": "user", "content": (
            f"You inherit case {case_id} from the intake analyst. "
            f"The case investigates alert {alert_id}: {alert['data']['summary']}. "
            f"Follow the playbook for alert kind {alert['data']['kind']}, deep-dive the evidence, "
            f"act with discipline, and close the case with an outcome future sessions can find."
        )},
    ]
    inv_text, _ = _run_agent_loop(conn, tenant, "case-investigator", INVESTIGATOR_TOOLS,
                                  investigator_messages, result)
    result.investigator_final = _parse_final_json(inv_text) or {
        "shape": "action", "verdict": "needs_more_evidence", "confidence": 0.0,
        "summary": inv_text[:500],
    }
    _persist_turn(conn, tenant, investigator_session, "case-investigator", "assistant", inv_text)
    return result
