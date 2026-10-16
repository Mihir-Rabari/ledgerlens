"""FastAPI service: the LedgerLens console API + static demo UI."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .agents import AgentError, ask_question, investigate_alert
from .config import CONFIG
from .graph import connection
from .tools import run_tool, tool_catalog

STATIC_DIR = Path(__file__).parent.parent / "static"


class InvestigateRequest(BaseModel):
    alert_id: str


class AskRequest(BaseModel):
    message: str
    session_id: str | None = None


def create_app() -> FastAPI:
    app = FastAPI(title="LedgerLens", version="0.1.0")
    conn = connection()

    @app.get("/healthz")
    def healthz() -> dict:
        try:
            tenants = conn.list_tenants()
            falkordb_ok = True
        except Exception:
            tenants, falkordb_ok = [], False
        return {"ok": falkordb_ok, "tenants": tenants, "llm_configured": CONFIG.llm_ready}

    @app.get("/api/tenants")
    def tenants() -> dict:
        return {"tenants": conn.list_tenants()}

    @app.get("/api/tenants/{tenant}/stats")
    def stats(tenant: str) -> dict:
        return run_tool(conn, tenant, "graph_stats", {})

    @app.get("/api/tenants/{tenant}/alerts")
    def alerts(tenant: str, status: str = "open") -> dict:
        return run_tool(conn, tenant, "list_alerts", {"status": status})

    @app.get("/api/tenants/{tenant}/cases")
    def cases(tenant: str, status: str = "all") -> dict:
        return run_tool(conn, tenant, "list_cases", {"status": status})

    @app.get("/api/tenants/{tenant}/case/{case_id}")
    def case(tenant: str, case_id: str) -> dict:
        return run_tool(conn, tenant, "get_case", {"case_id": case_id})

    @app.get("/api/tenants/{tenant}/graph")
    def graph(tenant: str, ids: str) -> dict:
        return run_tool(conn, tenant, "component_graph", {"member_ids": [i for i in ids.split(",") if i]})

    @app.get("/api/tools")
    def tools() -> dict:
        return {"tools": tool_catalog()}

    @app.post("/api/tenants/{tenant}/investigate")
    def investigate(tenant: str, req: InvestigateRequest) -> dict:
        try:
            result = investigate_alert(conn, tenant, req.alert_id)
        except AgentError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "tenant": result.tenant,
            "alert_id": result.alert_id,
            "handoff": result.handoff,
            "case_id": result.case_id,
            "analyst_session_id": result.analyst_session_id,
            "investigator_session_id": result.investigator_session_id,
            "analyst_final": result.analyst_final,
            "investigator_final": result.investigator_final,
            "turns": [vars(t) for t in result.turns],
        }

    @app.post("/api/tenants/{tenant}/ask")
    def ask(tenant: str, req: AskRequest) -> dict:
        try:
            return ask_question(conn, tenant, req.message, req.session_id)
        except AgentError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "console.html")

    return app
