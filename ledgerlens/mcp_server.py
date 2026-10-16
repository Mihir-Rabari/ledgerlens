"""MCP surface for the LedgerLens tool menu.

The same fixed menu the agent uses is exposed over MCP (stdio), so any MCP
client — Claude Desktop, IDE agents, other teams' agents — can drive the
investigator with the same discipline: validated arguments, hand-written
queries, typed answer shapes. Tool selection through MCP is a Track 1 key-focus
bullet; this is the same registry, not a parallel implementation.

Run:  python -m ledgerlens.mcp_server
"""

from __future__ import annotations

from .graph import connection
from .model import BANKS
from .tools import TOOLS, run_tool

try:
    from fastmcp import FastMCP
    from fastmcp.tools import FunctionTool
except ImportError as exc:  # pragma: no cover
    raise SystemExit("fastmcp is required for the MCP server: uv pip install fastmcp") from exc

TENANT_SCHEMA = {"type": "string",
                "description": "Bank tenant slug: one of " + ", ".join(b["slug"] for b in BANKS)}


def _schema_for(tool) -> dict:
    schema = dict(tool.schema or {"type": "object", "properties": {}})
    schema.setdefault("properties", {})
    schema["properties"] = dict(schema["properties"])
    schema["properties"]["tenant"] = TENANT_SCHEMA
    schema = dict(schema)
    required = list(schema.get("required", []))
    if "tenant" not in required:
        required.append("tenant")
    schema["required"] = required
    return schema


def build_mcp() -> FastMCP:
    mcp = FastMCP(name="LedgerLens", instructions=(
        "LedgerLens: graph-native fraud-ring investigator with persistent case memory, "
        "backed by FalkorDB. Every tool answers with a typed result; failures carry a "
        "shape (unknown_entity / not_in_graph) instead of running speculative queries."
    ))

    def make_handler(tool_name: str):
        def handler(**kwargs):
            kwargs = dict(kwargs)
            tenant = kwargs.pop("tenant", "")
            return run_tool(connection(), tenant, tool_name, kwargs)
        handler.__name__ = tool_name
        return handler

    for tool in TOOLS.values():
        fn = make_handler(tool.name)
        mcp.add_tool(FunctionTool(
            fn=fn,
            name=tool.name,
            description=tool.description,
            parameters=_schema_for(tool),
            tags={tool.kind},
        ))
    return mcp


mcp = build_mcp()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
